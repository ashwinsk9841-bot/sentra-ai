"""AI subsystem: LLM access, prompt templates, grounded RAG answers, investigator."""

from __future__ import annotations

from .investigator import DETERMINISTIC, Investigation, Investigator, anomaly_row_to_note
from .llm import LLMClient, LLMResponse, Message, clear_cache, get_llm, llm_health
from .prompts import (
    INVESTIGATOR_SYSTEM,
    anomaly_prompt,
    chat_prompt,
    chat_system,
    health_prompt,
    rag_prompt,
    report_prompt,
    safe_json,
)
from .rag_answer import answer_from_chunks, extractive_answer

__all__ = [
    "DETERMINISTIC",
    "INVESTIGATOR_SYSTEM",
    "Investigation",
    "Investigator",
    "LLMClient",
    "LLMResponse",
    "Message",
    "anomaly_prompt",
    "anomaly_row_to_note",
    "answer_from_chunks",
    "chat_prompt",
    "chat_system",
    "clear_cache",
    "extractive_answer",
    "get_llm",
    "health_prompt",
    "llm_health",
    "rag_prompt",
    "report_prompt",
    "safe_json",
]
