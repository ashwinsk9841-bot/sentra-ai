"""Demo Mode: a fully populated workspace with clearly-labelled synthetic data.

Guarantees:

* The device id, name and every generated row are marked ``SENTINEL-DEMO`` so a
  demo device can never be confused with a real one.
* Nothing is fabricated at read time. The generator writes rows to the same
  tables the agent uses, and the dashboard then reads them back like any other
  telemetry - so Demo Mode also exercises the real code paths.
* Seeding is idempotent: re-seeding replaces the demo device's history rather
  than duplicating it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from ..config import Settings, get_settings
from ..constants import LOG_LEVELS
from ..database.repository import SentinelRepository
from ..logger import get_logger
from ..synth.generator import (
    DEMO_AGENT_VERSION,
    DEMO_DEVICE_ID,
    DEMO_DEVICE_NAME,
    describe_scenario,
    generate_logs,
    generate_network,
    generate_processes,
    generate_telemetry,
    sample_document,
)

log = get_logger("services.demo")

__all__ = ["DemoResult", "DemoService", "SCENARIOS"]

SCENARIOS = ("mixed", "normal", "warning", "anomaly", "critical")


@dataclass(slots=True)
class DemoResult:
    """What a seed run produced."""

    device_id: str
    scenario: str
    samples: int = 0
    baseline_rows: int = 0
    system_rows: int = 0
    network_rows: int = 0
    process_rows: int = 0
    log_rows: int = 0
    document_id: str | None = None
    anomalies: int = 0
    alerts: int = 0
    risk_score: int = 0
    risk_severity: str = "LOW"
    duration_ms: float = 0.0
    steps: list[str] = field(default_factory=list)
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "scenario": self.scenario,
            "samples": self.samples,
            "baseline_rows": self.baseline_rows,
            "system_rows": self.system_rows,
            "network_rows": self.network_rows,
            "process_rows": self.process_rows,
            "log_rows": self.log_rows,
            "document_id": self.document_id,
            "anomalies": self.anomalies,
            "alerts": self.alerts,
            "risk_score": self.risk_score,
            "risk_severity": self.risk_severity,
            "duration_ms": round(self.duration_ms, 1),
            "steps": self.steps,
            "error": self.error,
        }


class DemoService:
    """Seeds and clears the synthetic demo workspace."""

    def __init__(self, repository: SentinelRepository, settings: Settings | None = None) -> None:
        self.repo = repository
        self.settings = settings or get_settings()

    # ------------------------------------------------------------------ #
    def is_seeded(self) -> bool:
        devices = self.repo.list_devices()
        if devices.empty or "device_id" not in devices.columns:
            return False
        return bool((devices["device_id"] == DEMO_DEVICE_ID).any())

    def seed(
        self,
        *,
        samples: int = 480,
        scenario: str = "mixed",
        interval_s: int = 5,
        seed: int | None = 7,
        include_document: bool = True,
        train_model: bool = True,
    ) -> DemoResult:
        """Populate the demo workspace. Returns a summary of what was written."""
        import time

        started = time.perf_counter()
        scenario = scenario if scenario in SCENARIOS else "mixed"
        steps: list[str] = []
        result = DemoResult(device_id=DEMO_DEVICE_ID, scenario=scenario, samples=int(samples))

        try:
            self._clear(quiet=True)
            steps.append("cleared previous demo data")

            self._register(scenario, interval_s)
            steps.append(f"registered {DEMO_DEVICE_NAME} ({DEMO_DEVICE_ID})")

            device_pk = self.repo.resolve_device_pk(DEMO_DEVICE_ID)
            if not device_pk:
                raise RuntimeError("Could not resolve the demo device id after registration.")

            telemetry, baseline_rows = self._telemetry_series(samples, interval_s, scenario, seed)
            result.baseline_rows = baseline_rows
            head = telemetry.iloc[:baseline_rows]
            tail = telemetry.iloc[baseline_rows:]
            incident_rows = [{**record, "device_pk": device_pk} for record in tail.to_dict("records")]

            if not train_model:
                result.system_rows = self.repo.insert_system_metrics(
                    [{**record, "device_pk": device_pk} for record in telemetry.to_dict("records")]
                )
                steps.append(f"wrote {result.system_rows} system metric row(s)")
            else:
                result.system_rows = self.repo.insert_system_metrics(
                    [{**record, "device_pk": device_pk} for record in head.to_dict("records")]
                )
                steps.append(
                    f"wrote {result.system_rows} healthy baseline row(s) to train on "
                    f"({baseline_rows} samples)"
                )

            network = generate_network(samples, interval_s=interval_s, scenario=scenario, seed=seed)
            network_rows = [
                {**record, "device_pk": device_pk} for record in network.to_dict("records")
            ]
            result.network_rows = self.repo.insert_network_metrics(network_rows)
            steps.append(f"wrote {result.network_rows} network row(s)")

            processes = generate_processes(
                count=18, scenario=scenario, seed=seed, ts=datetime.now(timezone.utc)
            )
            process_rows = [
                {**record, "device_pk": device_pk} for record in processes.to_dict("records")
            ]
            result.process_rows = self.repo.insert_process_snapshots(process_rows)
            steps.append(f"wrote {result.process_rows} process row(s)")

            logs = generate_logs(samples, interval_s=interval_s, scenario=scenario, seed=seed)
            log_rows = [
                {**record, "device_pk": device_pk} for record in logs.to_dict("records")
            ]
            result.log_rows = self.repo.insert_logs(log_rows)
            steps.append(f"wrote {result.log_rows} log row(s)")

            self.repo.touch_device(
                DEMO_DEVICE_ID,
                cpu_percent=_last(telemetry, "cpu_percent"),
                disk_percent=_last(telemetry, "disk_percent"),
                agent_version=DEMO_AGENT_VERSION,
            )
            steps.append("updated device liveness")

            if include_document:
                result.document_id = self._seed_document()
                steps.append(f"ingested the sample runbook ({result.document_id})")

            if train_model:
                from ..ml.pipeline import AnomalyPipeline

                pipeline = AnomalyPipeline(self.repo, self.settings)
                report = pipeline.train(DEMO_DEVICE_ID, force=True)
                if not report.ok:
                    raise RuntimeError(report.message or "Training failed during demo seed.")
                steps.append(
                    f"trained {len(report.models)} detector(s) on {report.sample_count} sample(s)"
                )

                result.system_rows += self.repo.insert_system_metrics(incident_rows)
                steps.append(
                    f"wrote {len(incident_rows)} incident row(s) after training "
                    "(unseen by the model)"
                )

                cycle = pipeline.run_cycle(DEMO_DEVICE_ID, train=False)
                result.anomalies = len(cycle.verdicts)
                result.alerts = cycle.alerts_persisted
                result.risk_score = cycle.risk.risk_score
                result.risk_severity = cycle.risk.severity
                steps.append(
                    f"ran detection: {len(cycle.verdicts)} verdict(s), "
                    f"{cycle.alerts_persisted} alert(s), risk {result.risk_score} "
                    f"({result.risk_severity})"
                )
                if cycle.errors:
                    steps.append(f"detector notes: {'; '.join(cycle.errors)[:200]}")
        except Exception as exc:
            log.exception("Demo seed failed")
            result.error = str(exc)[:400]

        result.duration_ms = (time.perf_counter() - started) * 1000
        result.steps = steps
        self._note(result)
        return result

    # ------------------------------------------------------------------ #
    def _telemetry_series(
        self, samples: int, interval_s: int, scenario: str, seed: int | None
    ) -> tuple[pd.DataFrame, int]:
        """Build ``normal baseline`` + ``incident`` as one continuous series.

        The model is trained on the first (healthy) part only, so the incident
        is genuinely unseen at detection time. Training on the incident as well
        would teach the detectors that it is normal, and Demo Mode would report
        zero anomalies on a run that clearly contains one.
        """
        total = max(20, int(samples))
        minimum = max(10, int(self.settings.min_train_samples))
        baseline = max(minimum, int(total * 0.6))
        baseline = min(baseline, total - 5)
        incident = total - baseline

        head = generate_telemetry(baseline, interval_s=interval_s, scenario="normal", seed=seed)
        # ``generate_telemetry`` treats ``start`` as the series *end*, so the
        # tail has to be pushed forward by its own length to begin one interval
        # after the baseline's last sample. Passing the baseline's last
        # timestamp directly would replay the incident backwards over the
        # healthy window instead of following it.
        tail_end = head["ts"].iloc[-1] + timedelta(seconds=interval_s * incident)
        tail = generate_telemetry(
            incident,
            interval_s=interval_s,
            scenario=scenario,
            seed=None if seed is None else seed + 1,
            start=tail_end,
        )
        return pd.concat([head, tail], ignore_index=True), len(head)

    # ------------------------------------------------------------------ #
    def _register(self, scenario: str, interval_s: int) -> None:
        import platform
        import sys

        self.repo.register_device(
            device_id=DEMO_DEVICE_ID,
            name=DEMO_DEVICE_NAME,
            os_name=f"{platform.system()} (synthetic)",
            os_version="demo",
            hostname="sentinel-demo",
            arch=platform.machine() or "x86_64",
            agent_version=DEMO_AGENT_VERSION,
            pairing_code=None,
            python_version=sys.version.split()[0],
            interval_s=int(interval_s),
            metadata={
                "synthetic": True,
                "demo": True,
                "scenario": scenario,
                "notice": "Synthetic demo data. Not measured from a real system.",
            },
        )
        self.repo.set_device_status(DEMO_DEVICE_ID, "AUTHORIZED")

    def _seed_document(self) -> str | None:
        from ..rag.pipeline import RagPipeline

        filename, text = sample_document()
        pipeline = RagPipeline(self.repo, self.settings)
        report = pipeline.ingest_bytes(
            text.encode("utf-8"),
            filename,
            title="Sentinel AI - Anomaly Response Runbook (sample)",
            source="DEMO",
        )
        return report.document_id if report.status == "INDEXED" else None

    def _clear(self, *, quiet: bool = False) -> int:
        """Remove all demo artefacts for the demo device."""
        from ..rag.pipeline import RagPipeline

        removed = 0
        try:
            documents = self.repo.list_documents()
            if not documents.empty and "source" in documents.columns:
                pipeline = RagPipeline(self.repo, self.settings)
                for document_id in documents[documents["source"] == "DEMO"]["id"].tolist():
                    pipeline.delete_document(str(document_id))
                    removed += 1
        except Exception as exc:
            log.debug("Could not clear demo documents: %s", exc)

        try:
            if self.repo.get_device(DEMO_DEVICE_ID):
                self.repo.delete_device(DEMO_DEVICE_ID)
        except Exception as exc:
            log.debug("Could not clear demo device: %s", exc)

        try:
            from ..ml.pipeline import AnomalyPipeline

            AnomalyPipeline(self.repo, self.settings).clear_model(DEMO_DEVICE_ID)
        except Exception as exc:  # pragma: no cover
            log.debug("Could not clear demo model: %s", exc)

        if not quiet:
            log.info("Demo data cleared (%d document(s))", removed)
        return removed

    def clear(self) -> dict[str, Any]:
        return {"removed_documents": self._clear(), "device_id": DEMO_DEVICE_ID}

    def _note(self, result: DemoResult) -> None:
        level = "ERROR" if result.error else "INFO"
        try:
            self.repo.insert_system_events(
                [
                    {
                        "ts": datetime.now(timezone.utc),
                        "level": level,
                        "source": "demo",
                        "message": (
                            f"Demo seed {result.scenario}: {result.system_rows} metric rows, "
                            f"{result.log_rows} log rows, {result.alerts} alert(s)"
                            if not result.error
                            else f"Demo seed failed: {result.error}"
                        ),
                        "context": result.as_dict(),
                    }
                ]
            )
        except Exception as exc:  # pragma: no cover
            log.debug("Could not record demo event: %s", exc)

    # ------------------------------------------------------------------ #
    def describe(self) -> dict[str, Any]:
        """Scenario descriptions for the Demo Mode controls."""
        return {
            "device_id": DEMO_DEVICE_ID,
            "device_name": DEMO_DEVICE_NAME,
            "scenarios": [
                {"id": name, "description": describe_scenario(name)} for name in SCENARIOS
            ],
            "log_levels": list(LOG_LEVELS),
            "seeded": self.is_seeded(),
        }


def _last(frame: Any, column: str) -> float | None:
    if frame is None or frame.empty or column not in frame.columns:
        return None
    value = frame[column].iloc[-1]
    return float(value) if value == value else None
