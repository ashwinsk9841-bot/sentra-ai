'use client';

import { Fragment, useCallback, useEffect, useState } from 'react';
import { CheckCircle2, Loader2 } from 'lucide-react';
import { PageHeader, ErrorBanner, LoadingBlock, EmptyState, WindowSelect } from '@/components/PageHeader';
import { Panel } from '@/components/Panel';
import { acknowledgeAnomaly, fetchAnomalies, WINDOWS } from '@/lib/api';
import type { AnomalyRow } from '@/lib/types';
import { clockTime, dateStamp, humanMetric, severityStyle } from '@/lib/format';

export default function AnomaliesPage() {
  const [rows, setRows] = useState<AnomalyRow[]>([]);
  const [timeWindow, setTimeWindow] = useState('24h');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = useCallback(async (w: string) => {
    setLoading(true);
    try {
      const payload = await fetchAnomalies(w, 200);
      setRows(payload.anomalies);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Request failed');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(timeWindow);
  }, [load, timeWindow]);

  const acknowledge = async (id: string) => {
    setBusy(id);
    try {
      await acknowledgeAnomaly(id);
      await load(timeWindow);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Acknowledge failed');
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="animate-rise-in">
      <PageHeader
        title="ANOMALIES"
        subtitle="Detections from the isolation forest, PCA reconstruction and z-score ensemble."
        action={<WindowSelect value={timeWindow} onChange={setTimeWindow} options={WINDOWS} />}
      />

      {error && <ErrorBanner message={error} onRetry={() => void load(timeWindow)} />}

      <Panel title={`Detections (${rows.length})`} bodyClassName="px-2 pb-2">
        {loading ? (
          <LoadingBlock rows={1} height={340} />
        ) : rows.length === 0 ? (
          <EmptyState message="No anomalies detected in this window" />
        ) : (
          <div className="max-h-[640px] overflow-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Event</th>
                  <th>Device</th>
                  <th>Severity</th>
                  <th className="text-right">Risk</th>
                  <th className="text-right">Score</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const sev = severityStyle(row.severity);
                  const open = expanded === row.id;
                  return (
                    <Fragment key={row.id}>
                      <tr>
                        <td className="tabular whitespace-nowrap text-[10px] text-muted">
                          {clockTime(row.ts)}
                          <span className="ml-1 text-muted/60">{dateStamp(row.ts).slice(0, 6)}</span>
                        </td>
                        <td className="max-w-[260px]">
                          <div className="truncate font-medium text-ink">
                            {humanMetric(row.metric)} deviation
                          </div>
                          <div className="truncate text-[9.5px] text-muted">
                            {Number(row.observed_value ?? 0).toFixed(1)} vs{' '}
                            {Number(row.expected_value ?? 0).toFixed(1)} expected
                          </div>
                        </td>
                        <td className="whitespace-nowrap text-[10.5px] text-muted">
                          {row.device_id}
                        </td>
                        <td>
                          <span className={`badge ${sev.badge}`}>
                            {String(row.severity ?? 'LOW').toUpperCase()}
                          </span>
                        </td>
                        <td className="tabular text-right font-semibold text-ink">
                          {row.risk_score ?? '--'}
                        </td>
                        <td className="tabular text-right text-muted">
                          {Number(row.anomaly_score ?? 0).toFixed(2)}
                        </td>
                        <td>
                          <span
                            className={`badge ${row.acknowledged ? 'badge-normal' : 'badge-high'}`}
                          >
                            {row.acknowledged ? 'ACK' : 'OPEN'}
                          </span>
                        </td>
                        <td className="whitespace-nowrap text-right">
                          <button
                            type="button"
                            className="btn-ghost"
                            onClick={() => setExpanded(open ? null : row.id)}
                          >
                            {open ? 'Hide' : 'Detail'}
                          </button>
                          {!row.acknowledged && (
                            <button
                              type="button"
                              className="btn-ghost"
                              disabled={busy === row.id}
                              onClick={() => void acknowledge(row.id)}
                            >
                              {busy === row.id ? (
                                <Loader2 size={10} className="animate-spin" />
                              ) : (
                                <CheckCircle2 size={10} />
                              )}
                              Ack
                            </button>
                          )}
                        </td>
                      </tr>
                      {open && (
                        <tr>
                          <td colSpan={8} className="bg-[#040c17] px-4 py-3">
                            <div className="label-micro mb-1">Explanation</div>
                            <p className="text-[10.5px] leading-relaxed text-ink/90">
                              {row.explanation ?? 'No explanation recorded.'}
                            </p>
                            <div className="mt-2 flex flex-wrap gap-4 text-[10px] text-muted">
                              <span>model: {row.model ?? '--'}</span>
                              <span>ratio: {Number(row.ratio ?? 0).toFixed(2)}x</span>
                              <span>delta: {Number(row.delta ?? 0).toFixed(2)}</span>
                              <span>baseline σ: {Number(row.baseline_std ?? 0).toFixed(2)}</span>
                            </div>
                            {row.evidence && (
                              <pre className="mt-2 overflow-x-auto rounded-md border border-cyan/15 bg-[#02050A] p-2 text-[9.5px] text-muted">
                                {JSON.stringify(row.evidence, null, 2)}
                              </pre>
                            )}
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
