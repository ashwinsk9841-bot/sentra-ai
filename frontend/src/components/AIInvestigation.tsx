'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { ArrowRight, Brain, Loader2, Sparkles } from 'lucide-react';
import { Panel } from './Panel';
import { investigate, investigateAnomaly } from '@/lib/api';
import type { AnomalyRow, SentraDevice } from '@/lib/types';
import { fmt, humanMetric, num, riskBand, severityStyle, titleCase } from '@/lib/format';

interface Props {
  anomalies: AnomalyRow[];
  device: SentraDevice | null;
}

/** Pull the evidence bullets out of the backend's anomaly record. */
function evidenceList(anomaly: AnomalyRow | null): string[] {
  if (!anomaly) return [];
  const out: string[] = [];
  const evidence = anomaly.evidence;
  if (evidence && typeof evidence === 'object') {
    for (const [key, value] of Object.entries(evidence)) {
      if (value === null || value === undefined) continue;
      if (typeof value === 'object') continue;
      out.push(`${titleCase(key)}: ${String(value)}`);
    }
  }
  if (anomaly.ratio) out.push(`Ratio to baseline: ${fmt(anomaly.ratio, 2)}x`);
  if (anomaly.baseline_std) out.push(`Baseline deviation: +${fmt(anomaly.delta, 1)}`);
  if (anomaly.model) out.push(`Detectors: ${anomaly.model.replace(/\+/g, ', ')}`);
  return out.slice(0, 4);
}

function firstSentence(text: string, max = 320): string {
  const clean = text.replace(/\s+/g, ' ').trim();
  if (clean.length <= max) return clean;
  const cut = clean.slice(0, max);
  const lastStop = Math.max(cut.lastIndexOf('. '), cut.lastIndexOf('; '));
  return `${lastStop > 60 ? cut.slice(0, lastStop + 1) : cut}...`;
}

/**
 * AI INVESTIGATION panel.
 *
 * The summary, evidence and actions are the real backend explanation and
 * detection context for the newest anomaly. "Open Investigation" runs the real
 * Sentra investigator (RAG + LLM) and shows what it returns.
 */
export function AIInvestigation({ anomalies, device }: Props) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const latest = anomalies[0] ?? null;
  const riskScore = latest?.risk_score ?? null;
  const band = riskBand(riskScore);
  const sev = severityStyle(latest?.severity);
  const evidence = evidenceList(latest);
  const deviceName = device?.name ?? latest?.device_id ?? 'this device';

  // Recommended next steps follow from the real detection signals.
  const actions: string[] = [];
  if (latest) {
    actions.push(`Verify recent activity on ${deviceName}`);
    actions.push(`Compare ${humanMetric(latest.metric)} against the learned baseline`);
    if (num(latest.ratio) && (latest.ratio ?? 0) > 2) {
      actions.push('Monitor the device for further deviation');
    } else {
      actions.push('Continue monitoring for recurrence');
    }
  } else {
    actions.push('No anomaly requires investigation right now');
  }

  const runInvestigation = async () => {
    if (!latest) {
      router.push('/investigation');
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const response = await investigateAnomaly(latest.id);
      const text =
        (response.answer as string) ||
        (response.summary as string) ||
        (response.text as string) ||
        JSON.stringify(response);
      setResult(firstSentence(String(text), 900));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Investigation failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel
      title="AI Investigation"
      className="h-full"
      action={
        <button type="button" className="btn-ghost" onClick={() => router.push('/investigation')}>
          <Sparkles size={11} /> New Analysis
        </button>
      }
    >
      {/* Risk level */}
      <div className="mb-3 flex items-center gap-2">
        <span className="label-micro">Risk Level</span>
        <span className={`badge ${sev.badge}`}>
          {latest ? String(latest.severity ?? band.label).toUpperCase() : band.label}
        </span>
        {latest && (
          <span className="tabular ml-auto text-[11px] font-semibold text-ink">
            risk {latest.risk_score ?? '--'}/100
          </span>
        )}
      </div>

      {/* Summary */}
      <div className="mb-3">
        <div className="label-micro mb-1">Summary</div>
        <p className="text-[11px] leading-relaxed text-ink/90">
          {latest?.explanation
            ? firstSentence(latest.explanation, 260)
            : 'No anomaly in the selected window. Sentra is monitoring for deviations.'}
        </p>
      </div>

      {/* Evidence */}
      <div className="mb-3">
        <div className="label-micro mb-1">Evidence</div>
        {evidence.length === 0 ? (
          <p className="text-[10.5px] text-muted/80">No evidence recorded.</p>
        ) : (
          <ul className="space-y-1">
            {evidence.map((item) => (
              <li key={item} className="flex gap-1.5 text-[10.5px] text-muted">
                <span className="text-cyan">•</span>
                <span className="min-w-0 flex-1">{item}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Recommended actions */}
      <div className="mb-3">
        <div className="label-micro mb-1">Recommended Actions</div>
        <ul className="space-y-1">
          {actions.map((item) => (
            <li key={item} className="flex gap-1.5 text-[10.5px] text-muted">
              <span className="text-cyan">•</span>
              <span className="min-w-0 flex-1">{item}</span>
            </li>
          ))}
        </ul>
      </div>

      {error && (
        <p className="mb-2 rounded-md border border-danger/40 bg-danger/10 px-2 py-1.5 text-[10px] text-danger">
          {error}
        </p>
      )}

      {result && (
        <div
          className="mb-2 rounded-md border px-2.5 py-2 text-[10.5px] leading-relaxed text-ink/90"
          style={{ borderColor: 'rgba(0,217,255,0.3)', background: 'rgba(0,217,255,0.06)' }}
        >
          <div className="mb-1 flex items-center gap-1.5 text-cyan">
            <Brain size={11} /> Investigator
          </div>
          {result}
        </div>
      )}

      <button
        type="button"
        onClick={runInvestigation}
        disabled={busy}
        className="btn-neon mt-auto w-full disabled:opacity-60"
      >
        {busy ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
        {busy ? 'Investigating...' : 'Open Investigation'}
        {!busy && <ArrowRight size={13} />}
      </button>
    </Panel>
  );
}
