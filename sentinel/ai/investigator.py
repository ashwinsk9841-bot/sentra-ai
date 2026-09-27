"""Investigator: the AI features the dashboard exposes.

Every method returns a result object that states *how* the text was produced,
so the UI can badge a model-written note differently from a deterministic
one. When no LLM is configured the investigator composes its answer from
measurements already in the database - it does not simulate a model.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from ..config import Settings, get_settings
from ..constants import CORE_METRICS, METRIC_LABELS, METRIC_UNITS, SEVERITIES
from ..database.repository import SentinelRepository
from ..exceptions import LLMError
from ..logger import get_logger
from .llm import LLMClient, get_llm
from .prompts import (
    INVESTIGATOR_SYSTEM,
    anomaly_prompt,
    chat_prompt,
    chat_system,
    health_prompt,
    report_prompt,
)

log = get_logger("ai.investigator")

DETERMINISTIC = "local-deterministic"

__all__ = ["Investigator", "Investigation", "anomaly_row_to_note"]


@dataclass(slots=True)
class Investigation:
    """A generated analysis plus its provenance."""

    text: str
    provider: str
    model: str
    grounded: bool
    confidence: float
    citations: list[dict[str, Any]] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "provider": self.provider,
            "model": self.model,
            "grounded": self.grounded,
            "confidence": self.confidence,
            "citations": self.citations,
            "latency_ms": round(self.latency_ms, 1),
            "note": self.note,
        }


class Investigator:
    """Anomaly notes, telemetry chat, and health briefings."""

    def __init__(
        self,
        repository: SentinelRepository,
        settings: Settings | None = None,
        *,
        client: LLMClient | None = None,
    ) -> None:
        self.repo = repository
        self.settings = settings or get_settings()
        self._client = client

    @property
    def client(self) -> LLMClient:
        if self._client is None:
            self._client = get_llm(self.settings)
        return self._client

    @property
    def llm_enabled(self) -> bool:
        return bool(self.settings.enable_llm and self.client.available)

    # ------------------------------------------------------------------ #
    # Anomaly investigation
    # ------------------------------------------------------------------ #
    def investigate(
        self,
        anomaly_id: str,
        *,
        question: str | None = None,
        persist: bool = True,
    ) -> Investigation:
        """Produce an investigation note for a stored anomaly."""
        anomaly = self.repo.get_anomaly(anomaly_id)
        if not anomaly:
            return Investigation(
                text=f"Anomaly {anomaly_id} was not found in the database.",
                provider="none",
                model="none",
                grounded=False,
                confidence=0.0,
                note="Unknown anomaly id.",
            )

        device = self._device_for(anomaly.get("device_id"))
        evidence = dict(anomaly.get("evidence") or {})
        prompt = anomaly_prompt(anomaly, device=device)
        if question:
            prompt += (
                "\n\nThe operator asked a follow-up question about this anomaly. Address it "
                f"explicitly after the standard sections:\n{question.strip()}"
            )
        result = self._generate(prompt=prompt, system=INVESTIGATOR_SYSTEM, fallback=lambda: anomaly_row_to_note(anomaly))
        if question and result.provider == DETERMINISTIC:
            result.text += f"\n\n**Operator question**\n{question.strip()}\n\n{_deterministic_followup(anomaly, question)}"
        if persist:
            try:
                self.repo.insert_investigation(
                    device_id=anomaly.get("device_id"),
                    anomaly_id=anomaly_id,
                    question=question or "Investigate this anomaly.",
                    answer=result.text,
                    provider=result.provider,
                    model=result.model,
                    evidence=evidence,
                    confidence=result.confidence,
                    citations=result.citations,
                )
            except Exception as exc:  # history write must not break the answer
                log.warning("Could not persist investigation: %s", exc)
        return result

    # ------------------------------------------------------------------ #
    # Telemetry chat
    # ------------------------------------------------------------------ #
    def ask(
        self,
        question: str,
        *,
        device_id: str | None = None,
        history: Sequence[tuple[str, str]] | None = None,
        persist: bool = True,
    ) -> Investigation:
        """Answer a free-form question about the monitored devices."""
        telemetry = self.telemetry_snapshot(device_id)
        alerts = self.repo.fetch_alerts(device_id=device_id, statuses=["NEW", "ACKNOWLEDGED"], limit=10)
        alert_rows = alerts.to_dict("records") if not alerts.empty else []

        result = self._generate(
            prompt=chat_prompt(
                question, telemetry=telemetry, open_alerts=alert_rows, history=history
            ),
            system=chat_system(),
            fallback=lambda: _telemetry_note(question, telemetry, alert_rows),
        )
        if persist:
            try:
                self.repo.insert_investigation(
                    device_id=device_id,
                    anomaly_id=None,
                    question=question,
                    answer=result.text,
                    provider=result.provider,
                    model=result.model,
                    evidence={"telemetry_keys": sorted(telemetry.get("latest", {}) or {})},
                    confidence=result.confidence,
                    citations=result.citations,
                )
            except Exception as exc:
                log.warning("Could not persist question: %s", exc)
        return result

    # ------------------------------------------------------------------ #
    # Briefings
    # ------------------------------------------------------------------ #
    def health_brief(self, device_id: str | None = None) -> Investigation:
        summary = self.telemetry_snapshot(device_id)
        return self._generate(
            prompt=health_prompt(summary),
            system=chat_system(),
            fallback=lambda: _health_note(summary),
        )

    def window_report(self, device_id: str | None, *, window_label: str) -> Investigation:
        summary = self.telemetry_snapshot(device_id)
        anomalies = self.repo.fetch_anomalies(device_id=device_id, limit=20)
        summary["recent_anomalies"] = (
            anomalies[
                ["ts", "metric", "severity", "risk_score", "explanation"]
            ].to_dict("records")
            if not anomalies.empty
            else []
        )
        return self._generate(
            prompt=report_prompt(summary, window_label=window_label),
            system=chat_system(),
            fallback=lambda: _report_note(summary, window_label),
        )

    # ------------------------------------------------------------------ #
    # Telemetry
    # ------------------------------------------------------------------ #
    def telemetry_snapshot(self, device_id: str | None = None) -> dict[str, Any]:
        """Everything the prompts are allowed to see about current state."""
        latest = self.repo.latest_system_metrics(device_id) or {}
        network = self.repo.latest_network_metrics(device_id) or {}
        network.pop("raw", None)
        risk = self.repo.fetch_risk_events(device_id=device_id, limit=1)
        processes = self.repo.fetch_process_snapshots(device_id=device_id, limit=5)
        logs = self.repo.fetch_logs(device_id=device_id, levels=["ERROR", "CRITICAL"], limit=5)

        device = self._device_for_public(device_id)
        return {
            "device": device,
            "latest": {k: v for k, v in latest.items() if k not in ("device_id", "raw")},
            "network": network,
            "latest_risk": risk.iloc[0].to_dict() if not risk.empty else None,
            "top_processes": processes.to_dict("records") if not processes.empty else [],
            "recent_errors": [
                {"ts": r.get("ts"), "level": r.get("level"), "message": r.get("message")}
                for r in (logs.to_dict("records") if not logs.empty else [])
            ],
            "metric_labels": dict(METRIC_LABELS),
            "metric_units": dict(METRIC_UNITS),
        }

    def _device_for(self, device_pk: Any) -> dict[str, Any] | None:
        """Resolve an internal device FK (as returned on anomaly rows)."""
        if not device_pk:
            return None
        devices = self.repo.list_devices()
        if devices.empty or "id" not in devices.columns:
            return None
        matched = devices[devices["id"] == device_pk]
        if matched.empty:
            return None
        record = matched.iloc[0].to_dict()
        return {
            "name": record.get("name"),
            "os_name": record.get("os_name"),
            "os_version": record.get("os_version"),
            "hostname": record.get("hostname"),
            "agent_version": record.get("agent_version"),
        }

    def _device_for_public(self, device_id: str | None) -> dict[str, Any] | None:
        if not device_id:
            devices = self.repo.list_devices()
            if devices.empty:
                return None
            record = devices.iloc[0].to_dict()
        else:
            record = self.repo.get_device(device_id) or {}
        if not record:
            return None
        return {
            "name": record.get("name"),
            "device_id": record.get("device_id"),
            "os_name": record.get("os_name"),
            "os_version": record.get("os_version"),
            "hostname": record.get("hostname"),
            "agent_version": record.get("agent_version"),
            "status": record.get("status"),
        }

    # ------------------------------------------------------------------ #
    # generation
    # ------------------------------------------------------------------ #
    def _generate(
        self, *, prompt: str, system: str, fallback: Any
    ) -> Investigation:
        """Try the LLM; on any failure use the supplied deterministic path."""
        if not self.llm_enabled:
            result = fallback()
            result.note = result.note or "Generated from stored measurements (no LLM configured)."
            return result

        started = time.perf_counter()
        try:
            response = self.client.complete(prompt, system=system)
            return Investigation(
                text=response.text,
                provider=response.provider,
                model=response.model,
                grounded=True,
                confidence=0.6,
                citations=[],
                latency_ms=(time.perf_counter() - started) * 1000,
                note=f"{response.total_tokens} tokens via {response.model}.",
            )
        except LLMError as exc:
            log.warning("LLM generation failed: %s", exc)
            result = fallback()
            result.note = f"LLM unavailable ({exc}); used measured-data analysis instead."
            return result


# --------------------------------------------------------------------------- #
# Deterministic builders
# --------------------------------------------------------------------------- #
def anomaly_row_to_note(anomaly: Mapping[str, Any]) -> Investigation:
    """Compose a note purely from a stored anomaly row."""
    metric = str(anomaly.get("metric") or "metric")
    label = METRIC_LABELS.get(metric, metric.replace("_", " ").title())
    unit = METRIC_UNITS.get(metric, "")
    observed = anomaly.get("observed_value")
    expected = anomaly.get("expected_value")
    risk = int(anomaly.get("risk_score") or 0)
    severity = str(anomaly.get("severity") or "LOW")
    scores = anomaly.get("model_scores") or {}
    evidence = anomaly.get("evidence") or {}

    facts = []
    if observed is not None:
        facts.append(f"{label} measured {_num(observed)}{_suffix(unit)}")
    if expected is not None:
        facts.append(f"baseline {_num(expected)}{_suffix(unit)}")
    if anomaly.get("delta") is not None:
        facts.append(f"delta {_signed(anomaly['delta'])}{_suffix(unit)}")
    if anomaly.get("ratio") is not None:
        facts.append(f"ratio {_num(anomaly['ratio'])}x baseline")

    ranked = sorted(
        ((k, float(v)) for k, v in scores.items() if isinstance(v, (int, float))),
        key=lambda item: item[1],
        reverse=True,
    )
    score_line = (
        ", ".join(f"{name} {value:.2f}" for name, value in ranked[:3]) if ranked else "no model scores"
    )
    threshold_line = _threshold_line(evidence)
    contributors = evidence.get("contributors") or []
    contributor_lines = [
        f"- {METRIC_LABELS.get(str(c.get('metric')), c.get('metric'))}: "
        f"{c.get('direction')} ({c.get('z', c.get('z_score', 'n/a'))} sigma)"
        for c in contributors[:3]
        if isinstance(c, Mapping)
    ]
    processes = evidence.get("top_processes") or []
    process_lines = [
        f"- {p.get('name')} (pid {p.get('pid')}): cpu {_num(p.get('cpu_percent'))}%, "
        f"mem {_num(p.get('memory_percent'))}%"
        for p in processes[:3]
        if isinstance(p, Mapping)
    ]
    logs = evidence.get("recent_logs") or []
    log_lines = [
        f"- [{l.get('level')}] {l.get('message')}" for l in logs[:3] if isinstance(l, Mapping)
    ]

    def section(title: str, lines: list[str]) -> str:
        return f"**{title}**\n" + ("\n".join(lines) if lines else "- No data recorded.")

    text = "\n\n".join(
        [
            section(
                "What happened",
                [f"At {anomaly.get('ts')}, {', '.join(facts) or 'no numeric values were recorded'}."]
                + ([f"Risk score {risk}/100 ({severity})."] if risk else []),
            ),
            section(
                "Why it was flagged",
                [
                    f"Ensemble scores: {score_line}.",
                    f"Detector explanation: {anomaly.get('explanation') or 'not recorded'}",
                ]
                + ([threshold_line] if threshold_line else []),
            ),
            section(
                "Likely explanations (hypotheses)",
                [
                    "1. Resource saturation on the device - supported if the metric tracks a "
                    "sustained rise rather than a single spike.",
                    "2. A new or changed workload on the host - supported if top processes "
                    "changed alongside the metric.",
                    "3. Measurement noise from a short window - weaken this if the baseline "
                    "sample count is small.",
                ],
            ),
            section("Contributing metrics", contributor_lines),
            section("Processes at detection time", process_lines),
            section("Recent errors", log_lines),
            section(
                "Checks to run now",
                [
                    "1. Re-read the metric over a longer window to confirm it is sustained.",
                    "2. Correlate with process CPU and memory for the same timestamps.",
                    "3. Check the ERROR/CRITICAL log entries within the anomaly window.",
                    "4. Compare against the last known-good baseline for this device.",
                ],
            ),
            section(
                "Escalation",
                [
                    f"Escalate now if risk stays above {risk} and the metric does not recover "
                    "within two collection intervals.",
                    f"Current band: {severity} (risk {risk}/100).",
                ],
            ),
            section(
                "Confidence and gaps",
                [
                    f"Confidence: {'medium' if scores else 'low'} - the note is derived from "
                    "stored measurements only.",
                    f"Gaps: {', '.join(evidence.get('missing') or ['process attribution', 'log correlation'])}.",
                ],
            ),
        ]
    )

    return Investigation(
        text=text,
        provider=DETERMINISTIC,
        model="measured-evidence",
        grounded=True,
        confidence=0.7 if scores else 0.4,
        citations=[],
        evidence=evidence,
        note="Composed from stored anomaly evidence.",
    )


def _deterministic_followup(anomaly: Mapping[str, Any], question: str) -> str:
    """Answer a follow-up question using only the stored anomaly row."""
    terms = {w for w in re.findall(r"[a-z0-9_]+", question.lower()) if len(w) > 3}
    metric = str(anomaly.get("metric") or "")
    label = METRIC_LABELS.get(metric, metric)
    scores = anomaly.get("model_scores") or {}
    lowered = question.lower()

    if any(word in lowered for word in ("why", "cause", "reason", "explain")):
        detail = ", ".join(f"{k} {float(v):.2f}" for k, v in scores.items() if isinstance(v, (int, float)))
        return (
            f"The stored detector explanation is: {anomaly.get('explanation') or 'not recorded'}. "
            f"Model scores were {detail or 'not recorded'}. "
            "Root cause is not established by these measurements alone - the checks above are "
            "the way to narrow it down."
        )
    if any(word in lowered for word in ("how bad", "severity", "risk", "score")):
        return (
            f"Risk score {int(anomaly.get('risk_score') or 0)}/100, band "
            f"{anomaly.get('severity') or 'LOW'}, on {label}."
        )
    if any(word in lowered for word in ("value", "measured", "observed", "number")):
        return (
            f"{label} measured {_num(anomaly.get('observed_value'))}"
            f"{_suffix(METRIC_UNITS.get(metric, ''))} against a baseline of "
            f"{_num(anomaly.get('expected_value'))}{_suffix(METRIC_UNITS.get(metric, ''))}."
        )
    if terms and metric in terms:
        return f"This anomaly is on {label}; its evidence is summarised in the sections above."
    return (
        f"The stored record for this anomaly covers {label} only. A question about "
        f"{', '.join(sorted(terms)[:3]) or 'anything else'} needs telemetry that was not "
        "captured with this anomaly - check the device directly or re-run a wider window."
    )


def _telemetry_note(
    question: str, telemetry: Mapping[str, Any], alerts: Sequence[Mapping[str, Any]]
) -> Investigation:
    latest = telemetry.get("latest") or {}
    lines: list[str] = []
    for metric in CORE_METRICS:
        if metric in latest and latest[metric] is not None:
            lines.append(
                f"- {METRIC_LABELS.get(metric, metric)}: {_num(latest[metric])}"
                f"{_suffix(METRIC_UNITS.get(metric, ''))}"
            )
    risk = telemetry.get("latest_risk") or {}
    severity = str(risk.get("severity") or "LOW")
    text = (
        f"**{question.strip()}**\n\n"
        "I can only answer from stored telemetry. Current readings:\n"
        + ("\n".join(lines) if lines else "- No telemetry has been collected yet.")
        + (
            f"\n\nLatest composite risk: {int(risk.get('risk_score') or 0)}/100 ({severity})."
            if risk
            else "\n\nNo risk events have been recorded yet."
        )
        + (
            f"\n\nOpen alerts: {len(alerts)} (worst "
            f"{max((str(a.get('severity')) for a in alerts), key=lambda s: SEVERITIES.index(s) if s in SEVERITIES else 0, default='n/a')})."
            if alerts
            else "\n\nNo open alerts."
        )
        + "\n\n**Next checks**\n"
        "1. Widen the selected time range on Live Monitoring.\n"
        "2. Open the Anomalies page for per-metric evidence.\n"
        "3. Ask again with a metric name such as cpu_percent for a focused answer."
    )
    return Investigation(
        text=text,
        provider=DETERMINISTIC,
        model="telemetry-summary",
        grounded=True,
        confidence=0.5,
        evidence={"latest": latest, "open_alerts": len(alerts)},
        note="Answered from stored telemetry (no LLM configured).",
    )


def _health_note(telemetry: Mapping[str, Any]) -> Investigation:
    latest = telemetry.get("latest") or {}
    risk = telemetry.get("latest_risk") or {}
    risk_score = int(risk.get("risk_score") or 0)
    severity = str(risk.get("severity") or "LOW")
    errors = telemetry.get("recent_errors") or []

    watches: list[str] = []
    for metric in CORE_METRICS:
        value = latest.get(metric)
        if value is None:
            continue
        band = _metric_band(metric, float(value))
        if band:
            watches.append(f"- **{METRIC_LABELS.get(metric, metric)}** is {band} ({_num(value)}{_suffix(METRIC_UNITS.get(metric, ''))})")
    watches.sort()
    watches = watches[:4]
    if not watches:
        watches = ["- No metric is currently outside its normal band."]

    text = (
        f"**Overall**\nComposite risk is {risk_score}/100 ({severity})"
        f"{' with ' + str(len(errors)) + ' recent error log entries' if errors else ' with no recent errors'}.\n\n"
        f"**Watches**\n" + "\n".join(watches) + "\n\n"
        "**Recommended focus**\n"
        f"1. {'Investigate the highest-severity alert first.' if severity in ('HIGH', 'CRITICAL') else 'Keep the current collection cadence.'}\n"
        f"2. {'Correlate the recent error logs with the flagged metric.' if errors else 'Confirm collection is healthy for every device.'}\n"
        "3. Record findings as investigations so the audit trail stays complete."
    )
    return Investigation(
        text=text,
        provider=DETERMINISTIC,
        model="health-summary",
        grounded=True,
        confidence=0.65,
        evidence={"risk": risk, "latest": latest},
        note="Computed from stored telemetry (no LLM configured).",
    )


def _report_note(telemetry: Mapping[str, Any], window_label: str) -> Investigation:
    anomalies = telemetry.get("recent_anomalies") or []
    counts = {severity: 0 for severity in SEVERITIES}
    for anomaly in anomalies:
        band = str(anomaly.get("severity") or "LOW")
        if band in counts:
            counts[band] += 1
    worst = max((a for a in anomalies), key=lambda a: int(a.get("risk_score") or 0), default=None)

    text = (
        f"**Headline**\n{len(anomalies)} anomal{'y' if len(anomalies) == 1 else 'ies'} recorded "
        f"in the {window_label} window"
        + (
            f"; worst was {METRIC_LABELS.get(str(worst.get('metric')), worst.get('metric'))} at "
            f"risk {int(worst.get('risk_score') or 0)}/100."
            if worst
            else "."
        )
        + "\n\n**Anomalies**\n"
        + (
            "\n".join(
                f"- [{a.get('severity')}] {METRIC_LABELS.get(str(a.get('metric')), a.get('metric'))} "
                f"- risk {int(a.get('risk_score') or 0)}"
                for a in sorted(anomalies, key=lambda a: int(a.get("risk_score") or 0), reverse=True)[:6]
            )
            if anomalies
            else "- None recorded in this window."
        )
        + "\n\n**Follow-ups**\n"
        "1. Acknowledge or resolve every alert still marked NEW.\n"
        "2. Attach an investigation note to each remaining anomaly.\n"
        "3. Retrain the model if this window contains many false positives."
    )
    return Investigation(
        text=text,
        provider=DETERMINISTIC,
        model="window-report",
        grounded=True,
        confidence=0.6,
        evidence={"anomaly_count": len(anomalies), "counts": counts},
        note=f"Computed from stored records for the {window_label} window.",
    )


# --------------------------------------------------------------------------- #
# formatting helpers
# --------------------------------------------------------------------------- #
def _num(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if abs(number) >= 100:
        return f"{number:,.0f}"
    if abs(number) >= 1:
        return f"{number:.1f}"
    return f"{number:.2f}"


def _signed(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/a"
    return f"+{_num(number)}" if number > 0 else _num(number)


def _suffix(unit: str) -> str:
    return f" {unit}" if unit else ""


def _threshold_line(evidence: Mapping[str, Any]) -> str | None:
    threshold = evidence.get("threshold")
    if threshold is None:
        return None
    return f"Threshold {threshold} was crossed."


_BANDS: dict[str, tuple[float, str]] = {
    "cpu_percent": (85.0, "high"),
    "memory_percent": (88.0, "high"),
    "disk_percent": (90.0, "high"),
    "swap_percent": (30.0, "elevated"),
    "load_average": (8.0, "high"),
    "disk_free_gb": (10.0, "low"),
    "process_count": (600.0, "high"),
    "thread_count": (2500.0, "high"),
}


def _metric_band(metric: str, value: float) -> str | None:
    limits = _BANDS.get(metric)
    if not limits:
        return None
    threshold, label = limits
    if metric == "disk_free_gb":
        return label if value < threshold else None
    return label if value > threshold else None
