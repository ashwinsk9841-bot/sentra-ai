"""Database access layer.

Exposes a single factory, :func:`get_repository`, that returns either the
Supabase-backed or the local SQLite-backed implementation. Callers never branch
on which backend is active.
"""

from __future__ import annotations

import threading
from typing import Literal

from ..config import Settings, get_settings
from ..exceptions import ConfigurationError, DatabaseError
from ..logger import get_logger
from .local import LocalRepository
from .repository import BackendHealth, SentinelRepository
from .supabase import SupabaseRepository

log = get_logger("database")

BackendName = Literal["supabase", "local"]

_lock = threading.Lock()
_cache: dict[tuple[str, str], SentinelRepository] = {}


def _key(name: BackendName, settings: Settings) -> tuple[str, str]:
    if name == "supabase":
        return ("supabase", settings.supabase_url or "")
    return ("local", str(settings.db_path))


def build_repository(name: BackendName | None = None, settings: Settings | None = None) -> SentinelRepository:
    """Construct a repository instance (no caching)."""
    cfg = settings or get_settings()
    resolved = name or ("supabase" if cfg.supabase_configured else "local")
    if resolved == "supabase":
        if not cfg.supabase_configured:
            raise ConfigurationError(
                "Supabase backend requested but not configured.",
                hint="Set SUPABASE_URL and SUPABASE_KEY, or use the local backend.",
            )
        repo = SupabaseRepository(
            cfg.supabase_url or "",
            cfg.supabase_key or "",
            service_key=cfg.supabase_service_key,
        )
    else:
        if not cfg.enable_local_store:
            raise ConfigurationError(
                "Local store is disabled and Supabase is not configured.",
                hint="Set ENABLE_LOCAL_STORE=true or configure Supabase credentials.",
            )
        cfg.ensure_directories()
        repo = LocalRepository(cfg.db_path)
    repo.initialise()
    return repo


def get_repository(
    name: BackendName | None = None, *, settings: Settings | None = None
) -> SentinelRepository:
    """Return a cached repository for the requested (or auto-selected) backend."""
    cfg = settings or get_settings()
    resolved = name or ("supabase" if cfg.supabase_configured else "local")
    cache_key = _key(resolved, cfg)  # type: ignore[arg-type]
    with _lock:
        existing = _cache.get(cache_key)
        if existing is not None:
            return existing
    repo = build_repository(resolved, cfg)  # type: ignore[arg-type]
    with _lock:
        _cache[cache_key] = repo
    return repo


def active_backend_name(settings: Settings | None = None) -> str:
    cfg = settings or get_settings()
    return "supabase" if cfg.supabase_configured else "local"


def local_repository(settings: Settings | None = None) -> LocalRepository:
    """Convenience accessor used by the vector store and demo seeder."""
    cfg = settings or get_settings()
    cfg.ensure_directories()
    repo = get_repository("local", settings=cfg)
    if not isinstance(repo, LocalRepository):
        raise DatabaseError("Expected the local backend.")
    return repo


def repository_health(settings: Settings | None = None) -> dict[str, BackendHealth]:
    """Health of every backend, primary first. Never raises."""
    cfg = settings or get_settings()
    results: dict[str, BackendHealth] = {}
    order: list[BackendName] = ["supabase", "local"] if cfg.supabase_configured else ["local"]
    for name in order:
        try:
            results[name] = get_repository(name, settings=cfg).health()
        except Exception as exc:
            results[name] = BackendHealth(
                name=name, connected=False, detail="backend could not be initialised", error=str(exc)[:300]
            )
    return results


def reset_cache() -> None:
    """Drop cached repository instances (used after config changes / in tests)."""
    with _lock:
        for repo in _cache.values():
            try:
                repo.close()
            except Exception:
                pass
        _cache.clear()


__all__ = [
    "BackendHealth",
    "BackendName",
    "LocalRepository",
    "SentinelRepository",
    "SupabaseRepository",
    "active_backend_name",
    "build_repository",
    "get_repository",
    "local_repository",
    "repository_health",
    "reset_cache",
]
