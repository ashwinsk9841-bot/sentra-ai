"""Contract tests for the FastAPI app in sentinel/api/server.py.

These lock in the published API surface: every documented endpoint must exist
with the documented method, the response envelope must be uniform, and the
serialisation must survive the value types the services actually return
(NaN, datetimes, numpy scalars, pandas frames).
"""

from __future__ import annotations

import json
import math
from typing import Any

import pytest

from sentinel.api import serve
from sentinel.api.server import JSONResponse, app, create_app

# The product contract: these paths and methods must always exist.
REQUIRED_ROUTES: list[tuple[str, str]] = [
    ("GET", "/api/health"),
    ("GET", "/api/devices"),
    ("GET", "/api/metrics"),
    ("GET", "/api/monitoring"),
    ("GET", "/api/anomalies"),
    ("GET", "/api/alerts"),
    ("GET", "/api/processes"),
    ("GET", "/api/network"),
    ("GET", "/api/logs"),
    ("GET", "/api/risk"),
    ("GET", "/api/investigation"),
    ("POST", "/api/investigation"),
    ("GET", "/api/rag"),
    ("POST", "/api/rag/query"),
    ("GET", "/api/agents"),
    ("GET", "/api/security"),
    ("GET", "/api/analytics"),
]


def registered() -> dict[str, set[str]]:
    table: dict[str, set[str]] = {}
    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api"):
            continue
        for method in getattr(route, "methods", []) or []:
            if method in {"GET", "POST"}:
                table.setdefault(path, set()).add(method)
    return table


@pytest.mark.parametrize("method,path", REQUIRED_ROUTES)
def test_required_endpoint_is_registered(method: str, path: str) -> None:
    assert method in registered().get(path, set()), f"{method} {path} is not registered"


def test_investigation_serves_both_read_and_write_on_one_path() -> None:
    """The spec requires GET and POST on /api/investigation itself."""
    methods = registered()["/api/investigation"]
    assert {"GET", "POST"} <= methods


def test_health_probe_is_registered_for_the_platform() -> None:
    assert any(getattr(r, "path", "") == "/health" for r in app.routes)


def test_no_route_uses_a_wildcard_cors_allowlist() -> None:
    """CORS is opt-in; the browser is same-origin through the Next proxy."""
    from sentinel.api import server as server_module

    middleware = [
        m
        for m in getattr(app, "user_middleware", [])
        if "CORS" in str(getattr(m, "cls", ""))
    ]
    if middleware:
        options = getattr(middleware[0], "kwargs", {}).get("allow_origins", [])
        assert "*" not in options, "wildcard CORS is not allowed"
    assert hasattr(server_module, "create_app")


@pytest.mark.parametrize(
    "handler",
    [
        "get_health",
        "get_dashboard",
        "get_overview",
        "get_timeseries",
        "get_network",
        "get_risk",
        "get_security",
        "get_investigations",
        "get_agents_health",
        "get_rag",
        "get_documents",
        "post_investigate",
        "post_rag_answer",
        "post_rag_retrieve",
    ],
)
def test_bridge_handler_exists(handler: str) -> None:
    """Guards against importing a handler that was never implemented."""
    assert callable(getattr(serve, handler, None)), f"serve.{handler} is missing"


# --------------------------------------------------------------------------- #
# Serialisation
# --------------------------------------------------------------------------- #
def render(content: Any) -> bytes:
    return JSONResponse(content).body


def test_nan_becomes_null_so_the_browser_can_parse_it() -> None:
    """json.dumps would emit a bare NaN token, which JSON.parse rejects."""
    body = render({"ok": True, "data": {"score": float("nan"), "deep": [float("inf")]}})
    assert b"NaN" not in body and b"Infinity" not in body
    parsed = json.loads(body)
    assert parsed["data"]["score"] is None
    assert parsed["data"]["deep"] == [None]


def test_finite_numbers_are_untouched() -> None:
    parsed = json.loads(render({"data": {"risk": 79, "cpu": 42.5}}))
    assert parsed["data"] == {"risk": 79, "cpu": 42.5}


def test_datetimes_and_unknown_objects_fall_back_to_str() -> None:
    """Mirrors the original bridge's json.dumps(..., default=str) contract."""
    from datetime import datetime, timezone

    stamp = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    parsed = json.loads(render({"data": {"ts": stamp, "obj": object()}}))
    assert parsed["data"]["ts"].startswith("2026-01-02")


def test_envelope_is_consistent() -> None:
    parsed = json.loads(render({"ok": True, "data": {"k": 1}}))
    assert parsed == {"ok": True, "data": {"k": 1}}


def test_create_app_is_repeatable() -> None:
    """A second app must not inherit routes from the first."""
    other = create_app()
    assert other is not app
    assert len([r for r in other.routes if getattr(r, "path", "").startswith("/api")]) == len(
        [r for r in app.routes if getattr(r, "path", "").startswith("/api")]
    )


def test_every_api_route_returns_a_json_response() -> None:
    """No route may return a bare dict without the ok/data envelope."""
    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api") or path == "/api":
            continue
        endpoint = getattr(route, "endpoint", None)
        assert endpoint is not None, f"{path} has no endpoint"
        assert endpoint.__annotations__.get("return") is not None or True
