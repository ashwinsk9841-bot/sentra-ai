"""Centralised configuration for Sentinel AI.

Resolution order for every setting (highest priority first):

1. Explicit runtime override (Streamlit ``st.session_state`` for UI settings,
   CLI flags for the agent).
2. Streamlit secrets (``st.secrets`` / ``.streamlit/secrets.toml``).
3. Process environment (``.env`` file loaded on demand, CI/CD, Docker).
4. Built-in default.

Secrets are read from the environment only. They are never written to disk by
this module and are only ever surfaced to the UI through
:meth:`Settings.public_summary`, which returns redacted metadata.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, Mapping

from .exceptions import ConfigurationError

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent

#: Values that are obviously documentation placeholders rather than real
#: configuration. Treating them as "unset" prevents a copied ``.env.example``
#: from producing a confusing authentication error.
_PLACEHOLDERS: Final[frozenset[str]] = frozenset(
    {
        "",
        "-",
        "none",
        "null",
        "changeme",
        "todo",
        "xxx",
        "your-key-here",
        "your-key",
        "your-api-key",
        "your_supabase_url",
        "your_supabase_key",
        "your-supabase-url",
        "your-supabase-key",
        "your-supabase-anon-key",
        "your-supabase-service-key",
        "your-llm-api-key",
        "your-embedding-api-key",
        "your-project.supabase.co",
        "your-agent-ingest-key",
        "your-backend.onrender.com",
    }
)

#: Labels that mark a hostname as an obvious placeholder, e.g.
#: ``https://your-project.supabase.co`` or ``https://your-backend.onrender.com``.
#: Exact token matching above cannot catch these because of the scheme, so a
#: URL whose hostname carries one of these labels is treated as unset too.
#: Without this, a fresh clone reports an unreachable backend as "configured".
#:
#: Deliberately narrow. "test", "fake" and "staging" are excluded because real
#: deployments use them in hostnames, and silently falling back to local SQLite
#: in production is a worse failure than a visible configuration warning.
#: "example" is safe to include as the domain is reserved for documentation.
_PLACEHOLDER_HOST_LABELS: Final[frozenset[str]] = frozenset(
    {"your", "example", "placeholder", "changeme", "replaceme"}
)


def _is_placeholder_url(text: str) -> bool:
    """True when *text* is a URL whose hostname is clearly a placeholder."""
    match = re.match(r"^[a-z][a-z0-9+.\-]*://([^/]+)", text, re.IGNORECASE)
    if not match:
        return False
    authority = match.group(1).rsplit("@", 1)[-1].split(":")[0].strip("[]")
    return any(
        label in _PLACEHOLDER_HOST_LABELS
        for label in re.split(r"[.\-]", authority.lower())
    )

_TRUE_TOKENS: Final[frozenset[str]] = frozenset({"1", "true", "t", "yes", "y", "on"})
_FALSE_TOKENS: Final[frozenset[str]] = frozenset({"0", "false", "f", "no", "n", "off"})


# --------------------------------------------------------------------------- #
# Primitive coercion helpers
# --------------------------------------------------------------------------- #
def coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    token = str(value).strip().lower()
    if token in _TRUE_TOKENS:
        return True
    if token in _FALSE_TOKENS:
        return False
    return default


def coerce_int(value: Any, default: int, *, low: int | None = None, high: int | None = None) -> int:
    try:
        result = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default
    if low is not None:
        result = max(low, result)
    if high is not None:
        result = min(high, result)
    return result


def coerce_float(
    value: Any, default: float, *, low: float | None = None, high: float | None = None
) -> float:
    try:
        result = float(str(value).strip())
    except (TypeError, ValueError):
        return default
    if result != result:  # NaN
        return default
    if low is not None:
        result = max(low, result)
    if high is not None:
        result = min(high, result)
    return result


def sanitize(value: Any) -> str | None:
    """Normalise a configuration token, mapping placeholders to ``None``."""
    if value is None:
        return None
    text = str(value).strip().strip('"').strip("'")
    if text.lower() in _PLACEHOLDERS:
        return None
    if _is_placeholder_url(text):
        return None
    return text or None


# --------------------------------------------------------------------------- #
# Secret / env lookup
# --------------------------------------------------------------------------- #
def _load_dotenv_once() -> None:
    """Load ``.env`` into ``os.environ`` once, without overriding real env vars."""
    if os.environ.get("SENTINEL_DOTENV_LOADED"):
        return
    os.environ["SENTINEL_DOTENV_LOADED"] = "1"
    for candidate in (REPO_ROOT / ".env", Path.cwd() / ".env"):
        try:
            if not candidate.is_file():
                continue
            for raw_line in candidate.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                if key and key not in os.environ:
                    os.environ[key] = val.strip().strip('"').strip("'")
        except OSError:
            continue


@lru_cache(maxsize=1)
def _secrets_snapshot() -> Mapping[str, Any]:
    """Read Streamlit secrets once, returning an empty mapping when absent."""
    try:  # pragma: no cover - depends on runtime
        from streamlit.runtime import exists

        if not exists():
            return {}
        import streamlit as st

        return dict(st.secrets)
    except Exception:
        return {}


def _lookup(name: str) -> str | None:
    """Resolve a single configuration key from env, dotenv or Streamlit secrets."""
    _load_dotenv_once()
    token = sanitize(os.environ.get(name))
    if token is not None:
        return token

    secrets = _secrets_snapshot()
    if not secrets:
        return None
    # Supports both flat keys and one level of nesting (e.g. [supabase] url = ...)
    direct = sanitize(secrets.get(name))
    if direct is not None:
        return direct
    for container in secrets.values():
        if isinstance(container, Mapping):
            nested = sanitize(container.get(name))
            if nested is not None:
                return nested
    return None


def _lookup_bool(name: str, default: bool) -> bool:
    token = _lookup(name)
    return default if token is None else coerce_bool(token, default)


def _lookup_int(name: str, default: int, **bounds: int | None) -> int:
    return coerce_int(_lookup(name), default, **bounds)


def _lookup_float(name: str, default: float, **bounds: float | None) -> float:
    return coerce_float(_lookup(name), default, **bounds)


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Settings:
    """Immutable snapshot of resolved configuration."""

    # -- Supabase ---------------------------------------------------------- #
    supabase_url: str | None = None
    supabase_key: str | None = None
    supabase_service_key: str | None = None

    # -- LLM --------------------------------------------------------------- #
    llm_api_key: str | None = None
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_timeout_s: float = 45.0
    llm_temperature: float = 0.2

    # -- Embeddings --------------------------------------------------------- #
    embedding_api_key: str | None = None
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_model: str = "text-embedding-3-small"

    # -- Agent ingest ------------------------------------------------------- #
    agent_ingest_url: str | None = None
    agent_ingest_key: str | None = None
    agent_update_interval: int = 10
    agent_max_retries: int = 3

    # -- Pipeline ----------------------------------------------------------- #
    monitoring_interval: int = 5
    alert_risk_threshold: int = 31
    contamination: float = 0.05
    min_train_samples: int = 60
    history_window: int = 5000

    # -- RAG ---------------------------------------------------------------- #
    chunk_size: int = 900
    chunk_overlap: int = 150
    rag_top_k: int = 5
    rag_min_score: float = 0.15

    # -- Storage / paths ----------------------------------------------------- #
    data_dir: Path = field(default_factory=lambda: REPO_ROOT / "data")
    device_id: str | None = None

    # -- Feature flags ------------------------------------------------------- #
    demo_mode: bool = False
    enable_local_store: bool = True
    enable_llm: bool = True
    enable_rag: bool = True

    # ------------------------------------------------------------------ #
    # Derived state
    # ------------------------------------------------------------------ #
    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_key)

    @property
    def supabase_service_configured(self) -> bool:
        return bool(self.supabase_url and (self.supabase_service_key or self.supabase_key))

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_api_key) and self.enable_llm

    @property
    def remote_embeddings_configured(self) -> bool:
        return bool(self.embedding_api_key)

    @property
    def agent_ingest_configured(self) -> bool:
        return bool(self.agent_ingest_url and self.agent_ingest_key)

    @property
    def embeddings_provider(self) -> str:
        return "remote" if self.remote_embeddings_configured else "local"

    @property
    def llm_provider(self) -> str:
        if not self.enable_llm:
            return "disabled"
        return "remote" if self.llm_api_key else "local-deterministic"

    @property
    def primary_backend(self) -> str:
        if self.supabase_configured:
            return "supabase"
        return "local-sqlite"

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "sentinel_local.db"

    @property
    def vector_store_dir(self) -> Path:
        return self.data_dir / "vectors"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    def ensure_directories(self) -> None:
        for path in (
            self.data_dir,
            self.models_dir,
            self.vector_store_dir,
            self.uploads_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def validate_runtime(self) -> list[ConfigurationError]:
        """Return configuration problems that degrade (but do not stop) the app."""
        problems: list[ConfigurationError] = []
        if self.supabase_url and not self.supabase_key:
            problems.append(
                ConfigurationError(
                    "SUPABASE_URL is set but SUPABASE_KEY is missing.",
                    hint="Set SUPABASE_KEY (anon key) or unset SUPABASE_URL to use the local store.",
                )
            )
        if self.chunk_overlap >= self.chunk_size:
            problems.append(
                ConfigurationError(
                    "RAG chunk overlap must be smaller than the chunk size.",
                    hint="Set RAG_CHUNK_OVERLAP to a value below RAG_CHUNK_SIZE.",
                )
            )
        if self.alert_risk_threshold < 0 or self.alert_risk_threshold > 100:
            problems.append(
                ConfigurationError(
                    "ALERT_RISK_THRESHOLD must be between 0 and 100.",
                    hint="Set ALERT_RISK_THRESHOLD to an integer in [0, 100].",
                )
            )
        if not self.enable_local_store and not self.supabase_configured:
            problems.append(
                ConfigurationError(
                    "No database backend is available.",
                    hint=(
                        "Configure SUPABASE_URL and SUPABASE_KEY, or set "
                        "ENABLE_LOCAL_STORE=true to use the on-disk SQLite store."
                    ),
                )
            )
        return problems

    def public_summary(self) -> list[dict[str, str]]:
        """Configuration rows safe to render in the UI (never exposes secrets)."""
        return [
            {"Setting": "SUPABASE_URL", "Value": _mask(self.supabase_url), "Status": _ok(self.supabase_configured)},
            {"Setting": "SUPABASE_KEY", "Value": _mask(self.supabase_key), "Status": _ok(bool(self.supabase_key))},
            {
                "Setting": "SUPABASE_SERVICE_KEY",
                "Value": _mask(self.supabase_service_key),
                "Status": _ok(bool(self.supabase_service_key)),
            },
            {"Setting": "LLM_API_KEY", "Value": _mask(self.llm_api_key), "Status": _ok(self.llm_configured)},
            {"Setting": "LLM_MODEL", "Value": self.llm_model, "Status": _ok(self.llm_configured)},
            {"Setting": "LLM_BASE_URL", "Value": self.llm_base_url, "Status": "INFO"},
            {"Setting": "EMBEDDING_API_KEY", "Value": _mask(self.embedding_api_key), "Status": _ok(self.remote_embeddings_configured)},
            {"Setting": "EMBEDDING_MODEL", "Value": self.embedding_model, "Status": _ok(self.remote_embeddings_configured)},
            {"Setting": "Embedding provider", "Value": self.embeddings_provider, "Status": _ok(True)},
            {"Setting": "AI provider", "Value": self.llm_provider, "Status": _ok(self.llm_configured)},
            {"Setting": "Database backend", "Value": self.primary_backend, "Status": _ok(True)},
            {"Setting": "Agent ingest URL", "Value": _mask(self.agent_ingest_url), "Status": _ok(self.agent_ingest_configured)},
            {"Setting": "DEMO_MODE", "Value": str(self.demo_mode), "Status": "INFO"},
            {"Setting": "Monitoring interval", "Value": f"{self.monitoring_interval}s", "Status": "INFO"},
            {"Setting": "Alert risk threshold", "Value": str(self.alert_risk_threshold), "Status": "INFO"},
            {"Setting": "Data directory", "Value": str(self.data_dir), "Status": "INFO"},
        ]


def _mask(value: str | None) -> str:
    """Show only the shape of a secret - never any of its content."""
    if not value:
        return "not set"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:3]}...{value[-2:]} ({len(value)} chars)"


def _ok(flag: bool) -> str:
    return "OK" if flag else "MISSING"


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #
def build_settings(overrides: Mapping[str, Any] | None = None) -> Settings:
    """Resolve configuration from the environment, applying optional overrides."""
    data_dir = Path(_lookup("SENTINEL_DATA_DIR") or (REPO_ROOT / "data")).expanduser()
    settings = Settings(
        supabase_url=_lookup("SUPABASE_URL"),
        supabase_key=_lookup("SUPABASE_KEY") or _lookup("SUPABASE_ANON_KEY"),
        supabase_service_key=_lookup("SUPABASE_SERVICE_KEY"),
        llm_api_key=_lookup("LLM_API_KEY") or _lookup("OPENAI_API_KEY"),
        llm_base_url=_lookup("LLM_BASE_URL") or "https://api.openai.com/v1",
        llm_model=_lookup("LLM_MODEL") or "gpt-4o-mini",
        llm_timeout_s=_lookup_float("LLM_TIMEOUT_S", 45.0, low=5.0, high=300.0),
        llm_temperature=_lookup_float("LLM_TEMPERATURE", 0.2, low=0.0, high=2.0),
        embedding_api_key=_lookup("EMBEDDING_API_KEY") or _lookup("OPENAI_API_KEY"),
        embedding_base_url=_lookup("EMBEDDING_BASE_URL")
        or _lookup("LLM_BASE_URL")
        or "https://api.openai.com/v1",
        embedding_model=_lookup("EMBEDDING_MODEL") or "text-embedding-3-small",
        agent_ingest_url=_lookup("AGENT_INGEST_URL") or _lookup("SENTINEL_INGEST_URL"),
        agent_ingest_key=_lookup("AGENT_INGEST_KEY") or _lookup("SENTINEL_INGEST_KEY"),
        agent_update_interval=_lookup_int("AGENT_UPDATE_INTERVAL", 10, low=1, high=3600),
        agent_max_retries=_lookup_int("AGENT_MAX_RETRIES", 3, low=0, high=10),
        monitoring_interval=_lookup_int("MONITORING_INTERVAL", 5, low=1, high=3600),
        alert_risk_threshold=_lookup_int("ALERT_RISK_THRESHOLD", 31, low=0, high=100),
        contamination=_lookup_float("CONTAMINATION", 0.05, low=0.001, high=0.5),
        min_train_samples=_lookup_int("MIN_TRAIN_SAMPLES", 60, low=20, high=100000),
        history_window=_lookup_int("HISTORY_WINDOW", 5000, low=100, high=1000000),
        chunk_size=_lookup_int("RAG_CHUNK_SIZE", 900, low=120, high=8000),
        chunk_overlap=_lookup_int("RAG_CHUNK_OVERLAP", 150, low=0, high=4000),
        rag_top_k=_lookup_int("RAG_TOP_K", 5, low=1, high=50),
        rag_min_score=_lookup_float("RAG_MIN_SCORE", 0.15, low=0.0, high=1.0),
        data_dir=data_dir,
        device_id=_lookup("SENTINEL_DEVICE_ID"),
        demo_mode=_lookup_bool("DEMO_MODE", False),
        enable_local_store=_lookup_bool("ENABLE_LOCAL_STORE", True),
        enable_llm=_lookup_bool("ENABLE_LLM", True),
        enable_rag=_lookup_bool("ENABLE_RAG", True),
    )
    if overrides:
        return _apply_overrides(settings, overrides)
    return settings


_OVERRIDE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "monitoring_interval",
        "alert_risk_threshold",
        "contamination",
        "min_train_samples",
        "history_window",
        "chunk_size",
        "chunk_overlap",
        "rag_top_k",
        "rag_min_score",
        "demo_mode",
        "enable_local_store",
        "enable_llm",
        "enable_rag",
        "llm_model",
        "embedding_model",
        "device_id",
    }
)


def _apply_overrides(settings: Settings, overrides: Mapping[str, Any]) -> Settings:
    from dataclasses import replace

    clean: dict[str, Any] = {}
    for key, value in overrides.items():
        if key not in _OVERRIDE_FIELDS or value is None:
            continue
        current = getattr(settings, key)
        try:
            if isinstance(current, bool):
                clean[key] = coerce_bool(value, current)
            elif isinstance(current, int):
                clean[key] = coerce_int(value, current)
            elif isinstance(current, float):
                clean[key] = coerce_float(value, current)
            else:
                clean[key] = str(value)
        except Exception:
            continue
    return replace(settings, **clean) if clean else settings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached process-wide settings snapshot."""
    return build_settings()


def reload_settings() -> Settings:
    """Invalidate the settings cache (used after in-app configuration edits)."""
    get_settings.cache_clear()
    _secrets_snapshot.cache_clear()
    return get_settings()
