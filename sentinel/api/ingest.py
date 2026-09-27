"""Agent ingest API.

Run with::

    uvicorn sentinel.api.ingest:app --host 0.0.0.0 --port 8080

Endpoints
---------
``GET  /health``               liveness + backend health (no auth)
``POST /api/v1/devices/register``  pair/refresh a device (bearer key)
``POST /api/v1/ingest``         telemetry batch (bearer key)
``GET  /api/v1/devices``        authorised device list (bearer key)

Authorisation: every write requires ``Authorization: Bearer <AGENT_INGEST_KEY>``
and the device must be ``AUTHORIZED`` in the repository. An agent cannot
register itself without a valid pairing code, and it cannot report data for a
device it is not paired with.

Note: this module deliberately does **not** use ``from __future__ import
annotations``. The request models below are defined inside :func:`create_app` to
keep pydantic an optional dependency, and postponed annotations would leave
FastAPI unable to resolve ``body: IngestRequest`` - it would fall back to
treating the payload as a query parameter and every POST would return 422.
"""

import hmac
from datetime import datetime, timezone
from typing import Any

from ..config import Settings, get_settings
from ..database import get_repository
from ..database.repository import SentinelRepository
from ..exceptions import DeviceNotAuthorizedError
from ..logger import get_logger

log = get_logger("api.ingest")

__all__ = ["app", "create_app", "ingest_batch", "register_device"]


def _require_fastapi() -> None:
    try:
        import fastapi  # noqa: F401
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "FastAPI is required for the ingest service. Install it with: pip install fastapi uvicorn"
        ) from exc


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Core operations (kept free of FastAPI types so they are unit-testable)
# --------------------------------------------------------------------------- #
def register_device(repo: SentinelRepository, payload: dict[str, Any]) -> dict[str, Any]:
    """Register (or re-register) a device from an agent payload."""
    required = ("device_id", "name", "os_name", "os_version", "hostname", "arch", "agent_version")
    missing = [key for key in required if not payload.get(key)]
    if missing:
        raise ValueError(f"Missing required registration fields: {', '.join(missing)}")

    record = repo.register_device(
        device_id=str(payload["device_id"]),
        name=str(payload["name"]),
        os_name=str(payload["os_name"]),
        os_version=str(payload["os_version"]),
        hostname=str(payload["hostname"]),
        arch=str(payload["arch"]),
        agent_version=str(payload["agent_version"]),
        pairing_code=payload.get("pairing_code"),
        python_version=str(payload.get("python_version") or "unknown"),
        interval_s=int(payload.get("interval_s") or 5),
        metadata=payload.get("metadata") or {},
    )
    log.info(
        "Device %s registered with status %s", payload.get("device_id"), record.get("status")
    )
    return {
        "device_id": record.get("device_id"),
        "status": record.get("status"),
        "authorized": record.get("status") == "AUTHORIZED",
        "message": record.get("message") or "Registered.",
        "interval_s": int(payload.get("interval_s") or 5),
    }


def ingest_batch(
    repo: SentinelRepository, payload: dict[str, Any], *, max_rows: int = 5000
) -> dict[str, Any]:
    """Persist one telemetry batch for an authorised device."""
    device_id = str(payload.get("device_id") or "").strip()
    if not device_id:
        raise ValueError("device_id is required")

    device = repo.get_device(device_id)
    if not device:
        raise ValueError(f"Unknown device '{device_id}'. Register it first.")
    if str(device.get("status")) != "AUTHORIZED":
        raise DeviceNotAuthorizedError(
            f"Device '{device_id}' is {device.get('status')}; present a valid pairing code."
        )

    device_pk = repo.resolve_device_pk(device_id)
    if not device_pk:
        raise ValueError(f"Could not resolve internal id for '{device_id}'.")

    system = _rows(payload.get("system_metrics"), max_rows)
    network = _rows(payload.get("network_metrics"), max_rows)
    processes = _rows(payload.get("process_snapshots"), max_rows)
    logs = _rows(payload.get("logs"), max_rows)

    accepted = 0
    if system:
        accepted += repo.insert_system_metrics([_with_pk(r, device_pk) for r in system])
    if network:
        accepted += repo.insert_network_metrics([_with_pk(r, device_pk) for r in network])
    if processes:
        accepted += repo.insert_process_snapshots([_with_pk(r, device_pk) for r in processes])
    if logs:
        accepted += repo.insert_logs([_with_pk(r, device_pk) for r in logs])

    repo.touch_device(
        device_id,
        cpu_percent=_latest(system, "cpu_percent"),
        disk_percent=_latest(system, "disk_percent"),
        agent_version=payload.get("agent_version"),
    )

    return {
        "device_id": device_id,
        "accepted": accepted,
        "counts": {
            "system_metrics": len(system),
            "network_metrics": len(network),
            "process_snapshots": len(processes),
            "logs": len(logs),
        },
        "received_at": _now().isoformat(),
    }


def _rows(value: Any, max_rows: int) -> list[dict[str, Any]]:
    if not value or not isinstance(value, (list, tuple)):
        return []
    rows: list[dict[str, Any]] = []
    for item in list(value)[:max_rows]:
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _with_pk(row: dict[str, Any], device_pk: str) -> dict[str, Any]:
    payload = dict(row)
    payload["device_pk"] = device_pk
    payload.setdefault("ts", _now().isoformat())
    return payload


def _latest(rows: list[dict[str, Any]], key: str) -> float | None:
    if not rows:
        return None
    value = rows[-1].get(key)
    return float(value) if isinstance(value, (int, float)) else None


# --------------------------------------------------------------------------- #
# FastAPI application
# --------------------------------------------------------------------------- #
def create_app(settings: Settings | None = None, repo: SentinelRepository | None = None) -> Any:
    """Build the ASGI app. Raises a clear error if FastAPI is missing."""
    _require_fastapi()
    from fastapi import Depends, FastAPI, Header, HTTPException
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel, Field

    cfg = settings or get_settings()
    repository = repo or get_repository(settings=cfg)

    class IngestItem(BaseModel):
        device_id: str
        agent_version: str | None = None
        system_metrics: list[dict[str, Any]] = Field(default_factory=list)
        network_metrics: list[dict[str, Any]] = Field(default_factory=list)
        process_snapshots: list[dict[str, Any]] = Field(default_factory=list)
        logs: list[dict[str, Any]] = Field(default_factory=list)

    class IngestRequest(BaseModel):
        sent_at: str | None = None
        batch_size: int | None = None
        items: list[IngestItem] = Field(default_factory=list)

    class RegisterRequest(BaseModel):
        device_id: str
        name: str
        os_name: str
        os_version: str
        hostname: str
        arch: str
        agent_version: str
        pairing_code: str | None = None
        python_version: str | None = None
        interval_s: int = 5
        metadata: dict[str, Any] = Field(default_factory=dict)

    application = FastAPI(
        title="Sentinel AI Ingest API",
        version="1.0.0",
        description="Authorised telemetry ingest for Sentinel AI agents.",
    )

    def require_key(authorization: str | None = Header(default=None)) -> None:
        """Bearer-key auth with a constant-time comparison."""
        expected = cfg.agent_ingest_key
        if not expected:
            raise HTTPException(
                status_code=503,
                detail="AGENT_INGEST_KEY is not configured; set it before exposing this service.",
            )
        token = (authorization or "").removeprefix("Bearer ").strip()
        if not token or not hmac.compare_digest(token, expected):
            raise HTTPException(status_code=401, detail="Invalid or missing agent API key.")

    @application.get("/health")
    def health() -> dict[str, Any]:
        backend = repository.health()
        return {
            "status": "ok" if backend.connected else "degraded",
            "backend": backend.as_dict(),
            "ingest_key_configured": bool(cfg.agent_ingest_key),
            "time": _now().isoformat(),
        }

    @application.post("/api/v1/devices/register", dependencies=[Depends(require_key)])
    def register(body: RegisterRequest) -> JSONResponse:
        try:
            result = register_device(repository, body.model_dump())
        except DeviceNotAuthorizedError as exc:
            return JSONResponse(status_code=403, content={"detail": str(exc)})
        except ValueError as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc)})
        code = 200 if result["authorized"] else 202
        return JSONResponse(status_code=code, content=result)

    @application.post("/api/v1/ingest", dependencies=[Depends(require_key)])
    def ingest(body: IngestRequest) -> JSONResponse:
        accepted = 0
        errors: list[dict[str, str]] = []
        for item in body.items:
            try:
                result = ingest_batch(repository, item.model_dump())
                accepted += int(result["accepted"])
            except DeviceNotAuthorizedError as exc:
                errors.append({"device_id": item.device_id, "error": str(exc)})
            except ValueError as exc:
                errors.append({"device_id": item.device_id, "error": str(exc)})
        if errors and accepted == 0:
            return JSONResponse(
                status_code=403 if all("AUTHORIZED" in e["error"] or "not" in e["error"] for e in errors) else 400,
                content={"accepted": 0, "errors": errors},
            )
        return JSONResponse(status_code=202, content={"accepted": accepted, "errors": errors})

    @application.get("/api/v1/devices", dependencies=[Depends(require_key)])
    def devices() -> dict[str, Any]:
        frame = repository.list_devices()
        records = frame.to_dict("records") if not frame.empty else []
        return {
            "count": len(records),
            "devices": [
                {
                    "device_id": r.get("device_id"),
                    "name": r.get("name"),
                    "status": r.get("status"),
                    "last_seen": r.get("last_seen"),
                    "risk_score": r.get("risk_score"),
                }
                for r in records
            ],
        }

    return application


class _LazyApp:
    """Defers app construction so importing this module never needs FastAPI."""

    def __init__(self) -> None:
        self._app: Any | None = None

    def _resolve(self) -> Any:
        if self._app is None:
            self._app = create_app()
        return self._app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> Any:  # pragma: no cover
        return await self._resolve()(scope, receive, send)


#: ASGI entrypoint: ``uvicorn sentinel.api.ingest:app``
app = _LazyApp()
