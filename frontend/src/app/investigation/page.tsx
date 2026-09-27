'use client';

import { useEffect, useState } from 'react';
import { Brain, Loader2, Send, Sparkles } from 'lucide-react';
import { PageHeader, ErrorBanner } from '@/components/PageHeader';
import { Panel } from '@/components/Panel';
import { investigate, investigateAnomaly } from '@/lib/api';
import type { AnomalyRow } from '@/lib/types';
import { riskBand } from '@/lib/format';

interface Turn {
  role: 'operator' | 'sentra';
  text: string;
}

const SUGGESTIONS = [
  'Summarise the current risk on this device.',
  'Which metric is driving the highest risk right now?',
  'What changed most in the last hour?',
];

export default function InvestigationPage() {
  const [question, setQuestion] = useState(SUGGESTIONS[0]);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [anomalyId, setAnomalyId] = useState('');

  const ask = async () => {
    const text = question.trim();
    if (!text) return;
    setBusy(true);
    setError(null);
    setTurns((prev) => [...prev, { role: 'operator', text }]);
    try {
      const response = anomalyId
        ? await investigateAnomaly(anomalyId, text)
        : await investigate(text);
      const answer =
        (response.answer as string) ||
        (response.summary as string) ||
        (response.text as string) ||
        JSON.stringify(response, null, 2);
      setTurns((prev) => [...prev, { role: 'sentra', text: String(answer) }]);
      setQuestion('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Investigation failed');
    } finally {
      setBusy(false);
    }
  };

  const runOnAnomaly = async (id: string) => {
    setBusy(true);
    setError(null);
    setAnomalyId(id);
    try {
      const response = await investigateAnomaly(id);
      const answer =
        (response.answer as string) || (response.summary as string) || JSON.stringify(response, null, 2);
      setTurns((prev) => [
        ...prev,
        { role: 'operator', text: `Investigate anomaly ${id.slice(0, 8)}` },
        { role: 'sentra', text: String(answer) },
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Investigation failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="animate-rise-in">
      <PageHeader
        title="AI INVESTIGATION"
        subtitle="Grounded answers from Sentra's RAG pipeline and investigator over real telemetry."
        action={
          <div className="flex items-center gap-2">
            <Sparkles size={14} className="text-cyan" />
            <span className="text-[10px] tracking-[0.16em] text-muted">RAG + LLM</span>
          </div>
        }
      />

      {error && <ErrorBanner message={error} />}

      <div className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)]">
        <Panel title="Investigator">
          <div className="min-h-[320px] space-y-3">
            {turns.length === 0 && (
              <div className="flex h-[280px] flex-col items-center justify-center text-center">
                <Brain size={30} strokeWidth={1.2} className="mb-3 text-cyan/70" />
                <p className="max-w-sm text-[11.5px] text-muted">
                  Ask Sentra about the monitored system. Answers are grounded in the ingested
                  runbooks and the recorded telemetry.
                </p>
              </div>
            )}
            {turns.map((turn, i) => (
              <div
                key={i}
                className="rounded-lg border px-3 py-2.5"
                style={{
                  borderColor:
                    turn.role === 'sentra' ? 'rgba(0,217,255,0.25)' : 'rgba(143,167,194,0.18)',
                  background:
                    turn.role === 'sentra' ? 'rgba(0,217,255,0.05)' : 'rgba(143,167,194,0.05)',
                }}
              >
                <div className="label-micro mb-1">
                  {turn.role === 'sentra' ? 'SENTRA AI' : 'OPERATOR'}
                </div>
                <p className="whitespace-pre-wrap text-[11.5px] leading-relaxed text-ink/90">
                  {turn.text}
                </p>
              </div>
            ))}
            {busy && (
              <div className="flex items-center gap-2 text-[11px] text-cyan">
                <Loader2 size={13} className="animate-spin" /> Analysing telemetry...
              </div>
            )}
          </div>

          <div className="mt-3 flex flex-wrap gap-1.5">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                type="button"
                className="btn-ghost"
                onClick={() => setQuestion(s)}
              >
                {s.length > 34 ? `${s.slice(0, 34)}...` : s}
              </button>
            ))}
            {anomalyId && (
              <button type="button" className="btn-ghost" onClick={() => setAnomalyId('')}>
                Clear anomaly scope
              </button>
            )}
          </div>

          <form
            className="mt-3 flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              void ask();
            }}
          >
            <input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Ask about risk, anomalies or system behaviour..."
              className="h-9 flex-1 rounded-lg border bg-[#040a14] px-3 text-[11.5px] text-ink outline-none placeholder:text-muted/70 focus:shadow-neon-cyan"
              style={{ borderColor: 'rgba(0,217,255,0.22)' }}
            />
            <button type="submit" className="btn-neon" disabled={busy}>
              <Send size={12} /> Ask
            </button>
          </form>
        </Panel>

        <RecentAnomaliesList onInvestigate={runOnAnomaly} busy={busy} />
      </div>
    </div>
  );
}

function RecentAnomaliesList({
  onInvestigate,
  busy,
}: {
  onInvestigate: (id: string) => Promise<void>;
  busy: boolean;
}) {
  const [rows, setRows] = useState<AnomalyRow[]>([]);

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const { fetchAnomalies } = await import('@/lib/api');
        const payload = await fetchAnomalies('24h', 8);
        if (active) setRows(payload.anomalies);
      } catch {
        /* surfaced by the main panel's error state */
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  return (
    <Panel title="Investigate Latest">
      {rows.length === 0 ? (
        <p className="text-[11px] text-muted/80">No recent anomalies to investigate.</p>
      ) : (
        <div className="space-y-2">
          {rows.map((row) => {
            const band = riskBand(row.risk_score);
            return (
              <div
                key={row.id}
                className="rounded-lg border px-3 py-2.5"
                style={{ borderColor: 'rgba(0,217,255,0.14)', background: 'rgba(2,6,13,0.6)' }}
              >
                <div className="flex items-center gap-2">
                  <span className={`badge ${band.badge}`}>{band.label}</span>
                  <span className="tabular ml-auto text-[11px] font-semibold text-ink">
                    {row.risk_score}/100
                  </span>
                </div>
                <p className="mt-1.5 line-clamp-3 text-[10.5px] leading-relaxed text-muted">
                  {row.explanation ?? 'No explanation recorded.'}
                </p>
                <button
                  type="button"
                  className="btn-neon mt-2 w-full"
                  disabled={busy}
                  onClick={() => void onInvestigate(row.id)}
                >
                  <Sparkles size={11} /> Investigate
                </button>
              </div>
            );
          })}
        </div>
      )}
    </Panel>
  );
}
