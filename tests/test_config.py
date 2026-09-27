"""Regression tests for sentinel.config placeholder handling.

A fresh clone copies ``.env.example`` to ``.env``. Any value that is still an
obvious placeholder must resolve to "unset", otherwise the app reports an
unreachable backend as configured, or warns that SUPABASE_URL is set without a
key. Real credentials must never be suppressed.
"""

from __future__ import annotations

import pytest

from sentinel.config import sanitize


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        None,
        "your-key",
        "your-api-key",
        "your-supabase-anon-key",
        "your-supabase-key",
        "your-supabase-service-key",
        "your-llm-api-key",
        "your-agent-ingest-key",
        "your-project.supabase.co",
        "your-backend.onrender.com",
        "https://your-project.supabase.co",
        "https://your-backend.onrender.com",
        "https://example.com",
        "https://placeholder.app",
        "https://changeme.internal",
        "none",
        "null",
        "changeme",
    ],
)
def test_placeholders_are_treated_as_unset(raw: object) -> None:
    assert sanitize(raw) is None


@pytest.mark.parametrize(
    "raw",
    [
        # Real project hosts, including ones that merely look suspicious.
        "https://abcdefghijklmnop.supabase.co",
        "https://prod-db.abc.supabase.co",
        "https://sentra-api.onrender.com",
        "https://staging-api.onrender.com",
        # "test"/"fake" are common in real hostnames and must survive, because
        # silently falling back to SQLite in production is worse than a warning.
        "https://test-abc.supabase.co",
        "https://fake-data.onrender.com",
        "https://api.openai.com/v1",
        "sk-proj-abc123",
        "gpt-4o-mini",
    ],
)
def test_real_values_are_preserved(raw: str) -> None:
    assert sanitize(raw) == raw


def test_surrounding_whitespace_and_quotes_are_stripped() -> None:
    assert sanitize('  "https://sentra-api.onrender.com"  ') == "https://sentra-api.onrender.com"


def test_env_example_produces_no_configuration_problems(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Copying .env.example verbatim must yield a clean local configuration."""
    import pathlib

    from sentinel.config import build_settings, reload_settings

    source = pathlib.Path(__file__).resolve().parent.parent / ".env.example"
    (pathlib.Path(str(tmp_path)) / ".env").write_text(
        source.read_text(encoding="utf-8"), encoding="utf-8"
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SENTINEL_DOTENV_LOADED", raising=False)
    monkeypatch.setattr("sentinel.config.Path.cwd", lambda: pathlib.Path(str(tmp_path)))
    settings = reload_settings()
    try:
        assert settings.validate_runtime() == []
        assert settings.supabase_configured is False
        assert settings.llm_configured is False
        assert settings.agent_ingest_configured is False
        assert settings.primary_backend == "local-sqlite"
    finally:
        reload_settings()
