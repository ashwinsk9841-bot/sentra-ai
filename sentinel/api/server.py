"""SENTRA AI production API — FastAPI application.

This is the backend service behind the SENTRA AI website. The browser never talks
to it directly: the Next.js server-side proxy forwards ``/api/*`` here, so the
public product stays a single origin.

Design notes
------------
* Every endpoint delegates to the existing Sentra services (``MonitoringService``,
  ``AgentService``, ``AnalyticsService``, ``NotificationService``,
  ``DemoService``) through the service graph in :mod:`sentinel.api.serve`. No ML,
  RAG or AI logic is reimplemented here.
* Responses use the same envelope as the rest of the product:
  ``{"ok": true, "data": ...}`` so the frontend contract is unchanged.
* The canonical REST names required by the product spec are the primary routes.
  The earlier bridge names (``/api/series``, ``/api/investigate`` ...) are kept as
  aliases so existing pages keep working.
* Persistence is chosen by :mod:`sentinel.database`: Supabase when
  ``SUPABASE_URL`` + ``SUPABASE_KEY`` are set, otherwise local SQLite for
  development and demos. Callers never branch on it.

Run locally::

    python -m uvicorn sentinel.api.server:app --host 0.0.0.0 --port 8787
"""

from __future__ import annotations

import json
import math
import os
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse as _JSONResponse

from .serve import (
    build_dashboard,
    build_network,
    build_risk,
    build_series,
    build_timeline,
    get_agent,
    get_agents_health,
    get_alerts,
    get_analytics,
    get_anomalies,
    get_dashboard,
    get_devices,
    get_documents,
    get_fleet,
    get_health,
    get_investigations,
    get_logs,
    get_network,
    get_overview,
    get_processes,
    get_rag,
    get_risk,
    get_security,
    get_series,
    get_timeline,
    get_timeseries,
    post_ack_anomaly,
    post_alert_status,
    post_demo_clear,
    post_demo_seed,
    post_device_status,
    post_investigate,
    post_investigate_anomaly,
    post_pairing_code,
    post_rag_answer,
    post_rag_retrieve,
    post_run_cycle,
    post_train_model,
    services,
)

__all__ = ["app", "create_app"]

Handler = Callable[[dict[str, list[str]], dict[str, Any]], Any]


def _finite(value: Any) -> Any:
    """Replace non-finite floats with ``None``.

    Telemetry can legitimately contain NaN/Infinity, which ``json.dumps`` would
    emit as the bare tokens ``NaN``/``Infinity``. Those are invalid JSON and
    ``JSON.parse`` in the browser rejects them, so they are normalised to
    ``null`` before serialisation.
    """
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _finite(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite(v) for v in value]
    return value


class JSONResponse(_JSONResponse):
    """Serialise exactly like the original bridge.

    Sentra services return datetimes, numpy scalars, pandas frames and
    ``Decimal`` values, so ``default=str`` is required. This mirrors
    ``sentinel.api.serve``'s ``json.dumps(payload, default=str)`` while also
    guaranteeing strictly valid JSON for the browser.
    """

    def render(self, content: Any) -> bytes:
        return json.dumps(
            _finite(content),
            default=str,
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Warm the service graph once so the first request is not slow."""
    try:
        services()
    except Exception:  # pragma: no cover - surfaced per-request instead
        pass
    yield


def _qs(**params: Any) -> dict[str, list[str]]:
    """Adapt FastAPI query parameters to the bridge's ``parse_qs`` shape."""
    out: dict[str, list[str]] = {}
    for key, value in params.items():
        if value is None:
            continue
        out[key] = [str(value)]
    return out


def create_app() -> FastAPI:
    app = FastAPI(
        title="SENTRA AI API",
        version="1.0.0",
        summary="Backend service for the SENTRA AI website.",
        lifespan=lifespan,
        # Docs are useful for operators; they are never linked from the UI.
        docs_url="/docs",
        redoc_url=None,
    )

    # The browser is same-origin: the Next.js route handler at
    # frontend/src/app/api/[...path] fetches this service server-side, so no
    # CORS headers are required for the product to work.
    #
    # CORS is therefore opt-in via SENTRA_CORS_ORIGINS (comma-separated) purely
    # so the API can be poked directly from another origin during development.
    # With no origins configured the middleware is not installed at all.
    cors_origins = [
        origin.strip()
        for origin in (os.environ.get("SENTRA_CORS_ORIGINS") or "").split(",")
        if origin.strip()
    ]
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["*"],
        )

    def route(
        path: str,
        handler: Handler,
        method: str | tuple[str, ...] = "GET",
    ) -> None:
        """Register one handler at one path for one or more HTTP methods."""
        methods = (method,) if isinstance(method, str) else method
        base = path.strip("/").replace("/", "_").replace("-", "_") or "root"

        async def endpoint(
            request: Request,
            window: str | None = Query(default=None),
            device: str | None = Query(default=None),
            limit: int | None = Query(default=None),
        ) -> JSONResponse:
            body: dict[str, Any] = {}
            if "POST" in methods:
                try:
                    body = await request.json()
                except Exception:
                    body = {}
                if not isinstance(body, dict):
                    body = {}
            qs = _qs(window=window, device=device, limit=limit)
            try:
                data = handler(qs, body)
            except Exception as exc:  # pragma: no cover - defensive
                return JSONResponse(
                    {"ok": False, "error": f"{type(exc).__name__}: {exc}"},
                    status_code=500,
                )
            return JSONResponse({"ok": True, "data": data}, status_code=200)

        for verb in methods:
            name = f"{verb.lower()}_{base}"
            app.add_api_route(
                path,
                endpoint,
                methods=[verb],
                name=name,
                summary=(handler.__doc__ or "").strip().split("\n")[0] or None,
            )

    # -- Core product surface ------------------------------------------- #
    route("/api/health", get_health)
    route("/api/dashboard", get_dashboard)
    route("/api/devices", get_devices)
    route("/api/metrics", get_series)
    route("/api/series", get_series)
    route("/api/timeseries", get_timeseries)
    route("/api/monitoring", get_dashboard)
    route("/api/overview", get_overview)
    route("/api/anomalies", get_anomalies)
    route("/api/alerts", get_alerts)
    route("/api/processes", get_processes)
    route("/api/network", get_network)
    route("/api/logs", get_logs)
    route("/api/risk", get_risk)
    route("/api/timeline", get_timeline)
    route("/api/analytics", get_analytics)
    route("/api/agents", get_agents_health)
    route("/api/agent", get_agent)
    route("/api/fleet", get_fleet)
    route("/api/security", get_security)
    route("/api/rag", get_rag)
    route("/api/documents", get_documents)

    # -- Investigation (AI) --------------------------------------------- #
    # One path serves both the history and the run action, as specified.
    route("/api/investigation", get_investigations, "GET")
    route("/api/investigation", post_investigate, "POST")
    route("/api/investigations", post_investigate, "POST")
    route("/api/investigate", post_investigate, "POST")
    route("/api/investigate-anomaly", post_investigate_anomaly, "POST")

    # -- RAG ------------------------------------------------------------- #
    route("/api/rag/query", post_rag_answer, "POST")
    route("/api/rag/retrieve", post_rag_retrieve, "POST")
    route("/api/rag-answer", post_rag_answer, "POST")
    route("/api/rag-retrieve", post_rag_retrieve, "POST")

    # -- Mutations ------------------------------------------------------- #
    route("/api/ack-anomaly", post_ack_anomaly, "POST")
    route("/api/anomalies/acknowledge", post_ack_anomaly, "POST")
    route("/api/alert-status", post_alert_status, "POST")
    route("/api/alerts/status", post_alert_status, "POST")
    route("/api/device-status", post_device_status, "POST")
    route("/api/devices/status", post_device_status, "POST")
    route("/api/run-cycle", post_run_cycle, "POST")
    route("/api/train-model", post_train_model, "POST")
    route("/api/pairing-code", post_pairing_code, "POST")
    route("/api/demo/seed", post_demo_seed, "POST")
    route("/api/demo/clear", post_demo_clear, "POST")

    @app.get("/api", include_in_schema=False)
    def api_index() -> dict[str, Any]:
        """Machine-readable endpoint index for the single-URL product."""
        return {
            "ok": True,
            "data": {
                "product": "SENTRA AI",
                "docs": "/docs",
                "endpoints": sorted(
                    r.path
                    for r in app.routes
                    if getattr(r, "path", "").startswith("/api") and r.path != "/api"
                ),
            },
        }

    @app.get("/health", include_in_schema=False)
    def liveness() -> dict[str, Any]:
        """Liveness/readiness probe for the platform (Render/Railway/Fly).

        Always answers 200 so the process is not killed while a dependency is
        briefly unavailable; the payload reports whether the store is actually
        connected so a deploy can assert on it.
        """
        try:
            backend = services()["repo"].health()
            payload = {
                "ok": True,
                "status": "healthy" if backend.connected else "degraded",
                "store": backend.name,
                "mode": backend.mode,
                "latency_ms": round(float(backend.latency_ms), 2),
            }
            if backend.error:
                payload["error"] = backend.error
        except Exception as exc:  # pragma: no cover - defensive
            payload = {"ok": True, "status": "degraded", "error": f"{type(exc).__name__}: {exc}"}
        return payload

    return app


app = create_app()
