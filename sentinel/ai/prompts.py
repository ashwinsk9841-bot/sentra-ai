"""Prompt templates.

Kept in one module so the exact wording sent to a model is reviewable, and so
the UI can show an operator what was asked. Every template takes data that
already exists in the platform - prompts never ask a model to invent
measurements.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

__all__ = [
    "INVESTIGATOR_SYSTEM",
    "anomaly_prompt",
    "chat_system",
    "chat_prompt",
    "health_prompt",
    "rag_prompt",
    "report_prompt",
    "safe_json",
]


def safe_json(payload: Any, *, limit: int = 6000) -> str:
    """Serialise evidence for a prompt, bounded so prompts stay affordable."""
    text = json.dumps(payload, indent=2, default=str)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n... [truncated {len(text) - limit} characters]"


# --------------------------------------------------------------------------- #
# RAG
# --------------------------------------------------------------------------- #
def rag_prompt(
    question: str,
    sources: Sequence[Mapping[str, Any]],
    *,
    include_runbook_context: str | None = None,
) -> str:
    """Answer a question using only the supplied sources."""
    blocks: list[str] = []
    for index, source in enumerate(sources, start=1):
        blocks.append(
            f"[{index}] {source.get('label') or 'source'} "
            f"(relevance {float(source.get('score') or 0):.2f})\n"
            f"{(source.get('content') or '').strip()}"
        )
    context = "\n\n".join(blocks) or "(no sources retrieved)"

    prompt = (
        "Answer the operator's question using ONLY the numbered sources below.\n\n"
        f"QUESTION:\n{question.strip()}\n\n"
        f"SOURCES:\n{context}\n"
    )
    if include_runbook_context:
        prompt += f"\nRUNBOOK CONTEXT:\n{include_runbook_context.strip()}\n"
    prompt += (
        "\nRULES:\n"
        "- Cite every factual claim with its source number, like [1] or [2][3].\n"
        "- If the sources do not contain the answer, say exactly what is missing.\n"
        "- Do not speculate about causes the sources do not mention.\n"
        "- Do not repeat any credential, token or key that appears in a source.\n\n"
        "Respond in this structure:\n"
        "**Answer** - 2-4 sentences, cited.\n"
        "**Key evidence** - bullet list, each with a citation.\n"
        "**Next actions** - 3-5 ordered, concrete steps.\n"
        "**Confidence** - high / medium / low, with one clause of justification."
    )
    return prompt


# --------------------------------------------------------------------------- #
# Anomaly investigation
# --------------------------------------------------------------------------- #
INVESTIGATOR_SYSTEM = (
    "You are a senior site-reliability engineer reviewing an automated anomaly "
    "detection. You are given measured telemetry, the ensemble's model scores, "
    "and the detector's own explanation.\n"
    "Write an investigation note with these sections:\n"
    "1. **What happened** - state the measured deviation with numbers and units.\n"
    "2. **Why it was flagged** - tie the model scores to the observation.\n"
    "3. **Likely explanations** - ranked hypotheses, each tagged with the evidence "
    "that supports or weakens it. Label them as hypotheses, not conclusions.\n"
    "4. **Checks to run now** - ordered, non-destructive commands or UI steps.\n"
    "5. **Escalation** - whether and when to escalate, and to whom.\n"
    "6. **Confidence and gaps** - your confidence plus the data that is missing.\n\n"
    "Hard constraints: an anomaly is anomalous behaviour, not a confirmed attack. "
    "Never claim root cause certainty. Never invent a measurement, a file path, a "
    "process name, or a CVE. Never output credentials, tokens or configuration "
    "secrets, and redact any secret-looking string you are shown. Prefer reversible "
    "diagnostics over remediation."
)


def anomaly_prompt(verdict: Mapping[str, Any], *, device: Mapping[str, Any] | None = None) -> str:
    """Turn a stored anomaly into an investigation note request."""
    evidence = {
        "anomaly": {
            "timestamp": verdict.get("ts"),
            "metric": verdict.get("metric"),
            "observed_value": verdict.get("observed_value"),
            "expected_value": verdict.get("expected_value"),
            "baseline_std": verdict.get("baseline_std"),
            "delta": verdict.get("delta"),
            "ratio": verdict.get("ratio"),
            "risk_score": verdict.get("risk_score"),
            "severity": verdict.get("severity"),
            "primary_model": verdict.get("model"),
            "anomaly_score": verdict.get("anomaly_score"),
        },
        "model_scores": verdict.get("model_scores") or {},
        "detector_explanation": verdict.get("explanation") or "",
        "metric_contributions": (verdict.get("evidence") or {}).get("contributors") or [],
        "recent_processes": (verdict.get("evidence") or {}).get("top_processes") or [],
        "recent_logs": (verdict.get("evidence") or {}).get("recent_logs") or [],
        "composite_risk": (verdict.get("evidence") or {}).get("composite") or {},
    }
    if device:
        evidence["device"] = {
            "name": device.get("name"),
            "platform": f"{device.get('os_name') or ''} {device.get('os_version') or ''}".strip(),
            "hostname": device.get("hostname"),
            "agent_version": device.get("agent_version"),
        }

    return (
        "Investigate the anomaly below and write the investigation note.\n\n"
        f"EVIDENCE:\n{safe_json(evidence)}\n\n"
        "If the evidence is thin, say so explicitly in the confidence section "
        "instead of padding the note."
    )


# --------------------------------------------------------------------------- #
# Free-form chat over telemetry
# --------------------------------------------------------------------------- #
def chat_system() -> str:
    return (
        "You are Sentinel AI, the analyst inside a system-monitoring console. "
        "Answer questions about the operator's own authorised devices using the "
        "supplied telemetry. Cite metrics and timestamps. If the telemetry does "
        "not contain the answer, say so and name the metric or time range that "
        "would be needed. Treat an anomaly as anomalous behaviour, not a "
        "confirmed attack. Never reveal secrets."
    )


def chat_prompt(
    question: str,
    *,
    telemetry: Mapping[str, Any] | None = None,
    open_alerts: Sequence[Mapping[str, Any]] | None = None,
    history: Sequence[tuple[str, str]] | None = None,
) -> str:
    sections: list[str] = []
    if telemetry:
        sections.append(f"CURRENT TELEMETRY:\n{safe_json(telemetry, limit=4000)}")
    if open_alerts:
        rows = [
            {
                "ts": a.get("ts"),
                "metric": a.get("metric"),
                "severity": a.get("severity"),
                "risk_score": a.get("risk_score"),
                "title": a.get("title"),
            }
            for a in list(open_alerts)[:10]
        ]
        sections.append(f"OPEN ALERTS:\n{safe_json(rows, limit=3000)}")
    if history:
        transcript = "\n".join(f"{role.upper()}: {text}" for role, text in history[-6:])
        sections.append(f"EARLIER IN THIS CONVERSATION:\n{transcript}")

    context = "\n\n".join(sections) or "No telemetry is available for this request."
    return (
        f"{context}\n\n"
        f"QUESTION:\n{question.strip()}\n\n"
        "Answer in 2-5 sentences. Reference specific metrics and timestamps from "
        "the telemetry above. End with a short bulleted list of suggested next "
        "checks. If the data does not support an answer, say that plainly."
    )


# --------------------------------------------------------------------------- #
# Health / report
# --------------------------------------------------------------------------- #
def health_prompt(summary: Mapping[str, Any]) -> str:
    return (
        "Write a short system health briefing from this monitoring summary.\n\n"
        f"SUMMARY:\n{safe_json(summary)}\n\n"
        "Structure: **Overall** (one sentence), **Watches** (bullets, worst first), "
        "**Recommended focus** (2-3 bullets). Reference risk scores and metrics. "
        "Do not claim a root cause the data does not support."
    )


def report_prompt(summary: Mapping[str, Any], *, window_label: str) -> str:
    return (
        f"Write an operator report for the {window_label} monitoring window.\n\n"
        f"SUMMARY:\n{safe_json(summary)}\n\n"
        "Structure: **Headline**, **What changed** (metrics that moved), "
        "**Anomalies** (severity ordered), **Follow-ups**. Keep it factual and "
        "numeric. No speculation presented as fact."
    )
