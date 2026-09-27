"""LLM client.

Targets any OpenAI-compatible ``/chat/completions`` endpoint (OpenAI, Azure
OpenAI, Groq, Together, Ollama, LiteLLM, vLLM, ...), configured entirely through
environment variables:

===========================  ================================================
``LLM_API_KEY``              bearer token (omit for local servers)
``LLM_BASE_URL``             defaults to ``https://api.openai.com/v1``
``LLM_MODEL``                defaults to ``gpt-4o-mini``
===========================  ================================================

When no key is configured the platform does **not** fabricate model output.
:func:`get_llm` returns a client whose ``available`` flag is ``False`` and the
calling layer falls back to a deterministic, clearly-labelled analysis path.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Iterator, Sequence

from ..config import Settings, get_settings
from ..exceptions import LLMError
from ..logger import get_logger

log = get_logger("ai.llm")

__all__ = ["LLMClient", "LLMResponse", "get_llm", "llm_health"]


@dataclass(slots=True)
class LLMResponse:
    """A single completion."""

    text: str
    provider: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(slots=True)
class Message:
    role: str
    content: str

    def as_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


SYSTEM_PROMPT = (
    "You are Sentinel AI, a careful system-reliability analyst. You explain "
    "measured system telemetry and anomaly detections. Rules you always follow:\n"
    "1. Base every claim on the evidence provided. Never invent measurements.\n"
    "2. An anomaly is anomalous behaviour, not a confirmed attack. Use that wording.\n"
    "3. State uncertainty explicitly and say what additional data would raise confidence.\n"
    "4. Give concrete, ordered investigation steps an operator can take.\n"
    "5. Never reveal credentials, tokens or configuration secrets, and never repeat "
    "any string that looks like a secret even if it appears in the evidence."
)


class LLMClient:
    """Minimal, dependency-free chat-completions client."""

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str,
        model: str,
        timeout: float = 45.0,
        temperature: float = 0.2,
        max_tokens: int = 1400,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = float(timeout)
        self.temperature = float(temperature)
        self.max_tokens = int(max_tokens)
        self._lock = threading.Lock()
        self._last_error: str | None = None
        self._last_success: float | None = None

    # -- state -------------------------------------------------------------- #
    @property
    def available(self) -> bool:
        """True when a request can actually be attempted."""
        return bool(self.api_key)

    @property
    def provider(self) -> str:
        return "remote-llm" if self.available else "disabled"

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def describe(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model if self.available else "not configured",
            "base_url": self.base_url,
            "available": self.available,
            "last_error": self._last_error,
        }

    def health(self) -> dict[str, Any]:
        """Cheap availability check. Never raises."""
        if not self.available:
            return {
                "connected": False,
                "detail": "LLM_API_KEY not set; using deterministic analysis.",
                "provider": "disabled",
            }
        return {
            "connected": True,
            "detail": f"Configured for {self.base_url} ({self.model}).",
            "provider": self.provider,
        }

    # -- generation --------------------------------------------------------- #
    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        history: Sequence[Message] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Single-shot completion. Raises :class:`LLMError` on any failure."""
        if not self.available:
            raise LLMError(
                "No LLM is configured.",
                hint="Set LLM_API_KEY (and optionally LLM_BASE_URL / LLM_MODEL) to enable AI answers.",
            )
        messages = [Message("system", system or SYSTEM_PROMPT)]
        for item in history or []:
            messages.append(item if isinstance(item, Message) else Message(item[0], item[1]))
        messages.append(Message("user", prompt))

        import time

        payload = json.dumps(
            {
                "model": self.model,
                "messages": [m.as_dict() for m in messages],
                "temperature": self.temperature if temperature is None else float(temperature),
                "max_tokens": max_tokens or self.max_tokens,
            }
        ).encode("utf-8")

        request = urllib.request.Request(
            self._endpoint(),
            data=payload,
            headers=self._headers(),
            method="POST",
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            self._last_error = f"HTTP {exc.code}: {detail}"
            raise LLMError(
                f"The LLM provider returned HTTP {exc.code}.",
                hint="Check LLM_MODEL is valid for the configured endpoint and that the key has access.",
            ) from exc
        except urllib.error.URLError as exc:
            self._last_error = f"network error: {exc.reason}"
            raise LLMError(
                f"Could not reach the LLM provider at {self.base_url}.",
                hint="Check network access and LLM_BASE_URL.",
            ) from exc
        except Exception as exc:
            self._last_error = str(exc)[:300]
            raise LLMError(f"LLM request failed: {exc}") from exc

        self._last_error = None
        with self._lock:
            self._last_success = time.time()

        try:
            text = body["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("The LLM provider returned an unexpected response shape.") from exc

        usage = body.get("usage") or {}
        return LLMResponse(
            text=str(text).strip(),
            provider=self.provider,
            model=str(body.get("model") or self.model),
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            latency_ms=(time.perf_counter() - started) * 1000,
            raw=body if len(json.dumps(body)) < 4000 else {},
        )

    def stream(self, prompt: str, **kwargs: Any) -> Iterator[str]:
        """Yield the completion in sentence-sized pieces for UI streaming.

        The HTTP call itself is not incremental (that requires SSE parsing per
        provider), so this yields the finished answer in readable segments
        instead of pretending to stream tokens.
        """
        response = self.complete(prompt, **kwargs)
        for segment in _segments(response.text):
            yield segment

    # -- internals ---------------------------------------------------------- #
    def _endpoint(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return f"{self.base_url}/chat/completions"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers


def _segments(text: str, limit: int = 160) -> list[str]:
    """Split text into readable chunks on sentence/line boundaries."""
    if not text:
        return []
    segments: list[str] = []
    buffer = ""
    for token in text.replace("\n", " \n ").split(" "):
        buffer = f"{buffer} {token}".strip() if buffer else token
        if len(buffer) >= limit and token.endswith((".", "!", "?", ":", ",", ";")):
            segments.append(buffer)
            buffer = ""
    if buffer:
        segments.append(buffer)
    return segments


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #
_clients: dict[tuple[str, str, str], LLMClient] = {}
_lock = threading.Lock()


def get_llm(settings: Settings | None = None) -> LLMClient:
    """Return a cached client for the current configuration."""
    cfg = settings or get_settings()
    key = (cfg.llm_api_key or "", cfg.llm_base_url, cfg.llm_model)
    with _lock:
        cached = _clients.get(key)
        if cached is not None:
            return cached
    client = LLMClient(
        api_key=cfg.llm_api_key,
        base_url=cfg.llm_base_url,
        model=cfg.llm_model,
        timeout=cfg.llm_timeout_s,
        temperature=cfg.llm_temperature,
    )
    with _lock:
        _clients[key] = client
    return client


def llm_health(settings: Settings | None = None) -> dict[str, Any]:
    """Availability report for the dashboard header."""
    return get_llm(settings).health()


def clear_cache() -> None:
    with _lock:
        _clients.clear()
