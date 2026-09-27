#!/usr/bin/env python
"""Container entrypoint: run the whole SENTRA AI stack as one process tree.

Responsibilities
----------------
1. Start FastAPI on an INTERNAL port bound to ``0.0.0.0``.
2. Wait until ``/health`` answers before starting Next.js, so the first visitor
   never sees a 502 from the API proxy.
3. Start Next.js bound to ``$PORT`` - the single public port Render assigns.
4. Export ``SENTRA_API_URL`` for the Next.js server only, so its existing
   ``/api/*`` route handler can reach the backend server-side.
5. Forward SIGTERM/SIGINT and tear the whole tree down, so the container stops
   promptly and Render does not have to SIGKILL it.
6. Exit non-zero if either process dies, so a crashed service is not reported
   as healthy.

The browser only ever calls same-origin ``/api/*`` on the public URL. No
hostname, port or secret is ever sent to the client, and no browser-side
request is made to localhost.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
FRONTEND = APP / "frontend"

# Render injects PORT. 3000 is only a local-container fallback and is never
# baked into an image or a browser request.
PUBLIC_PORT = int(os.environ.get("PORT") or 3000)
API_PORT = int(os.environ.get("SENTRA_API_PORT") or 8000)
BIND = "0.0.0.0"
API_URL = f"http://127.0.0.1:{API_PORT}"

# Keep the local SQLite/Chroma store off the read-only app code path. Render
# mounts a persistent disk here when one is attached.
os.environ.setdefault("SENTINEL_DATA_DIR", str(APP / "data"))
Path(os.environ["SENTINEL_DATA_DIR"]).mkdir(parents=True, exist_ok=True)

_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _paint(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def info(message: str) -> None:
    print(_paint(f"[sentra] {message}", "36"), flush=True)


def ok(message: str) -> None:
    print(_paint(f"[sentra] {message}", "32"), flush=True)


def warn(message: str) -> None:
    print(_paint(f"[sentra] {message}", "33"), flush=True)


def fail(message: str) -> None:
    print(_paint(f"[sentra] ERROR: {message}", "31"), file=sys.stderr, flush=True)


def npm_exe() -> str:
    exe = shutil.which("npm") or shutil.which("npm.cmd")
    if exe is None:
        fail("npm not found on PATH; the runtime image must include Node.js")
        raise SystemExit(1)
    return exe


def wait_for_health(url: str, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, OSError, ValueError):
            time.sleep(1.5)
    return False


class Supervisor:
    """Starts both processes and keeps them alive as one unit."""

    def __init__(self) -> None:
        self._children: list[subprocess.Popen[bytes]] = []
        self._labels: dict[int, str] = {}
        self._stopping = False

    def spawn(self, label: str, command: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.Popen[bytes]:
        info(f"starting {label}: {' '.join(command)}")
        kwargs: dict[str, object] = {}
        if os.name == "posix":
            # Own process group, so one signal reaps the whole subtree
            # (npm -> next -> node).
            kwargs["start_new_session"] = True
        try:
            process = subprocess.Popen(command, cwd=str(cwd), env=env, **kwargs)
        except OSError as exc:
            fail(f"could not start {label}: {exc}")
            raise SystemExit(1) from exc
        self._children.append(process)
        self._labels[process.pid] = label
        return process

    def alive(self) -> list[subprocess.Popen[bytes]]:
        return [child for child in self._children if child.poll() is None]

    def request_stop(self, *_args: object) -> None:
        """SIGTERM/SIGINT lands here; start the ordered shutdown once."""
        if self._stopping:
            return
        self._stopping = True
        print(flush=True)
        info("shutdown requested, stopping both processes")
        for child in reversed(self.alive()):
            self._terminate_tree(child)

    @staticmethod
    def _terminate_tree(process: subprocess.Popen[bytes]) -> None:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except OSError:
                process.kill()


def main() -> int:
    if sys.version_info < (3, 10):
        fail("Python 3.10+ is required")
        return 1

    build_id = FRONTEND / ".next" / "BUILD_ID"
    if not build_id.is_file():
        fail("no Next.js production build found at frontend/.next/BUILD_ID")
        warn("run `npm run build` in frontend/ before starting the container")
        return 1

    frontend_env = dict(os.environ)
    # Read only by the server-side /api/* route handler. Never NEXT_PUBLIC_*,
    # so it can never be inlined into the client bundle.
    frontend_env["SENTRA_API_URL"] = API_URL
    frontend_env["NODE_ENV"] = "production"
    # Render injects PORT for the public listener; Next.js is told the exact
    # port explicitly on the command line, so this only stops an inherited
    # value from confusing other tooling.
    frontend_env.pop("PORT", None)

    supervisor = Supervisor()
    signal.signal(signal.SIGTERM, supervisor.request_stop)
    signal.signal(signal.SIGINT, supervisor.request_stop)

    info(f"data directory: {os.environ['SENTINEL_DATA_DIR']}")
    info(f"public port: {PUBLIC_PORT} (this is the only published port)")
    info(f"internal API port: {API_PORT} (loopback only)")

    # --- Backend: internal only ------------------------------------------- #
    backend = supervisor.spawn(
        "backend",
        [
            sys.executable, "-m", "uvicorn", "sentinel.api.server:app",
            "--host", BIND, "--port", str(API_PORT),
            "--timeout-keep-alive", "65",
            "--no-access-log",
        ],
        cwd=APP,
        env=dict(os.environ),
    )

    if not wait_for_health(f"{API_URL}/health", timeout=180):
        fail(f"backend did not answer /health on {API_URL} within 180s")
        if backend.poll() is not None:
            fail(f"backend exited early with code {backend.returncode}")
        supervisor.request_stop()
        return 1
    ok(f"backend healthy on {BIND}:{API_PORT} (internal)")

    # --- Frontend: the single public listener ------------------------------ #
    supervisor.spawn(
        "frontend",
        [npm_exe(), "run", "start", "--", "-H", BIND, "-p", str(PUBLIC_PORT)],
        cwd=FRONTEND,
        env=frontend_env,
    )

    print(flush=True)
    ok(f"SENTRA AI is live on port {PUBLIC_PORT}")
    info(f"  /       -> Next.js (all UI pages)")
    info(f"  /api/*  -> FastAPI via the in-app proxy (no second public port)")
    print(flush=True)

    exit_code = 0
    try:
        while True:
            time.sleep(1.0)
            if supervisor._stopping:
                break
            for child in supervisor.alive():
                if child.poll() is not None:
                    fail(
                        f"{supervisor._labels.get(child.pid, 'process')} exited "
                        f"with code {child.returncode}"
                    )
                    exit_code = child.returncode or 1
            if not supervisor.alive():
                break
    except KeyboardInterrupt:
        supervisor.request_stop()
    finally:
        supervisor.request_stop()

    ok("stopped")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
