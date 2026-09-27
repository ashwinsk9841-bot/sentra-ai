#!/usr/bin/env python
"""Start the whole SENTRA AI stack locally with one command.

    python scripts/dev.py

Launches two processes:

  1. the FastAPI backend on 127.0.0.1:8787
  2. the Next.js frontend on 127.0.0.1:3000

Only the frontend port is for humans. The browser loads the frontend and calls
same-origin ``/api/*``, which the Next route handler proxies to the backend, so
the product behaves like the deployed single-URL setup.

Environment:

  SENTRA_API_URL          override the backend origin the proxy uses
  SENTRA_FRONTEND_PORT    override the frontend port (default 3000)
  SENTRA_BACKEND_PORT     override the backend port (default 8787)
  SKIP_BACKEND=1          frontend only, for frontend-only work

Ctrl+C stops both, including the whole process tree on Windows.
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

REPO = Path(__file__).resolve().parent.parent
FRONTEND = REPO / "frontend"

BACKEND_PORT = int(os.environ.get("SENTRA_BACKEND_PORT", "8787"))
FRONTEND_PORT = int(os.environ.get("SENTRA_FRONTEND_PORT", "3000"))
BACKEND_HOST = "127.0.0.1"
BACKEND_URL = os.environ.get("SENTRA_API_URL") or f"http://{BACKEND_HOST}:{BACKEND_PORT}"

IS_WINDOWS = os.name == "nt"
IS_POSIX = os.name == "posix"

# ANSI colours, disabled when the output is piped or NO_COLOR is set.
_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _paint(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def info(message: str) -> None:
    print(_paint(f"[dev] {message}", "36"), flush=True)


def ok(message: str) -> None:
    print(_paint(f"[dev] {message}", "32"), flush=True)


def warn(message: str) -> None:
    print(_paint(f"[dev] {message}", "33"), flush=True)


def fail(message: str) -> None:
    print(_paint(f"[dev] ERROR: {message}", "31"), file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- #
# Preflight
# --------------------------------------------------------------------------- #
def check_python() -> None:
    if sys.version_info < (3, 10):
        fail(f"Python 3.10+ required, found {sys.version.split()[0]}")
        raise SystemExit(1)


def check_backend_deps() -> None:
    missing = []
    for module, package in (
        ("fastapi", "fastapi"),
        ("uvicorn", "uvicorn"),
        ("pandas", "pandas"),
        ("numpy", "numpy"),
        ("sklearn", "scikit-learn"),
    ):
        try:
            __import__(module)
        except ImportError:
            missing.append(package)
    if missing:
        fail(f"Missing backend packages: {', '.join(missing)}")
        fail("Install them with:  pip install -r requirements.txt")
        raise SystemExit(1)


def check_node() -> str:
    """Return the npm executable path, exiting if it is unusable."""
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if npm is None:
        fail("npm was not found on PATH. Install Node.js 18 or newer.")
        raise SystemExit(1)
    if not (FRONTEND / "node_modules").is_dir():
        fail("frontend/node_modules is missing.")
        fail("Install it with:  cd frontend && npm install")
        raise SystemExit(1)
    return npm


def port_available(port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((BACKEND_HOST, port))
        except OSError:
            return False
    return True


def wait_for_health(url: str, timeout: float = 90.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=4) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, OSError, ValueError):
            time.sleep(1.0)
    return False


# --------------------------------------------------------------------------- #
# Child process management
# --------------------------------------------------------------------------- #
class ProcessGroup:
    """Owns child processes and tears down their whole tree on exit."""

    def __init__(self) -> None:
        self._children: list[subprocess.Popen[bytes]] = []

    def spawn(
        self,
        label: str,
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str] | None = None,
    ) -> subprocess.Popen[bytes]:
        info(f"starting {label}: {' '.join(command)}")
        # Own process group on POSIX so Ctrl+C reaches the children too.
        popen_kwargs: dict[str, object] = {}
        if IS_POSIX:
            popen_kwargs["start_new_session"] = True
        elif IS_WINDOWS:
            popen_kwargs["creationflags"] = getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0
            )

        try:
            process = subprocess.Popen(
                command,
                cwd=str(cwd),
                env=env,
                stdout=None,
                stderr=None,
                **popen_kwargs,
            )
        except OSError as exc:
            fail(f"could not start {label}: {exc}")
            raise SystemExit(1) from exc

        self._children.append(process)
        return process

    def alive(self) -> list[subprocess.Popen[bytes]]:
        return [child for child in self._children if child.poll() is None]

    def terminate(self) -> None:
        for child in self.alive():
            _terminate_tree(child)


def _terminate_tree(process: subprocess.Popen[bytes]) -> None:
    """Stop a child and every process it spawned."""
    if IS_WINDOWS:
        # taskkill /T also kills grandchildren, which uvicorn reloaders and
        # `npm run dev` both create.
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            capture_output=True,
            check=False,
        )
    else:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            process.terminate()

    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        if IS_WINDOWS:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
                check=False,
            )
        else:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except OSError:
                process.kill()


# --------------------------------------------------------------------------- #
# Entrypoint
# --------------------------------------------------------------------------- #
def main() -> int:
    check_python()
    check_backend_deps()
    npm = check_node()

    if not port_available(BACKEND_PORT):
        warn(f"port {BACKEND_PORT} is busy; another Sentra backend may be running.")
        warn(f"reusing it at {BACKEND_URL}")

    skip_backend = os.environ.get("SKIP_BACKEND") == "1"
    group = ProcessGroup()
    interrupted = False

    def on_interrupt(*_: object) -> None:
        nonlocal interrupted
        interrupted = True
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGINT, on_interrupt)
    if IS_POSIX:
        try:
            signal.signal(signal.SIGHUP, on_interrupt)
        except (AttributeError, ValueError):
            pass

    try:
        if skip_backend:
            warn("SKIP_BACKEND=1, not starting the backend")
        else:
            group.spawn(
                "backend",
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "sentinel.api.server:app",
                    "--host",
                    BACKEND_HOST,
                    "--port",
                    str(BACKEND_PORT),
                    "--reload",
                ],
                cwd=REPO,
            )
            if wait_for_health(f"{BACKEND_URL}/health"):
                ok(f"backend healthy at {BACKEND_URL}")
            else:
                fail(f"backend did not become healthy at {BACKEND_URL}/health")
                warn("check the traceback above; the frontend will show 502s")

        frontend_env = dict(os.environ)
        frontend_env["SENTRA_API_URL"] = BACKEND_URL
        group.spawn(
            "frontend",
            [npm, "run", "dev", "--", "--port", str(FRONTEND_PORT)],
            cwd=FRONTEND,
            env=frontend_env,
        )

        print()
        ok(f"SENTRA AI is starting -> http://localhost:{FRONTEND_PORT}")
        info(f"the browser uses this one URL; /api/* proxies to {BACKEND_URL}")
        print()
        info("press Ctrl+C to stop both processes")
        print(flush=True)

        # Poll so an unexpected child exit is reported instead of hanging.
        while True:
            time.sleep(1.0)
            children = group.alive()
            if not children:
                break
            for child in children:
                if child.poll() is not None:
                    fail(
                        f"{'backend' if child is group._children[0] else 'frontend'} "
                        f"exited with code {child.returncode}"
                    )

    except KeyboardInterrupt:
        if interrupted:
            print()
            info("shutting down")
    finally:
        signal.signal(signal.SIGINT, previous)
        group.terminate()
        ok("stopped")

    return 0


if __name__ == "__main__":
    sys.exit(main())
