'use client';

import { useCallback, useEffect, useState } from 'react';
import { PageHeader, ErrorBanner, LoadingBlock, EmptyState, WindowSelect } from '@/components/PageHeader';
import { Panel } from '@/components/Panel';
import { fetchAlerts, setAlertStatus, WINDOWS } from '@/lib/api';
import type { AlertRow } from '@/lib/types';
import { clockTime, dateStamp, severityStyle, statusStyle } from '@/lib/format';

export default function AlertsPage() {
  const [rows, setRows] = useState<AlertRow[]>([]);
  const [timeWindow, setTimeWindow] = useState('24h');
  const [filter, setFilter] = useState('ALL');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async (w: string) => {
    setLoading(true);
    try {
      const payload = await fetchAlerts(w, 200);
      setRows(payload.alerts);
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

  const update = async (id: string, status: string) => {
    setBusy(id);
    try {
      await setAlertStatus(id, status);
      await load(timeWindow);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Update failed');
    } finally {
      setBusy(null);
    }
  };

  const filtered = filter === 'ALL' ? rows : rows.filter((r) => String(r.status).toUpperCase() === filter);
  const counts = {
    NEW: rows.filter((r) => String(r.status).toUpperCase() === 'NEW').length,
    ACKNOWLEDGED: rows.filter((r) => String(r.status).toUpperCase() === 'ACKNOWLEDGED').length,
    RESOLVED: rows.filter((r) => String(r.status).toUpperCase() === 'RESOLVED').length,
  };

  return (
    <div className="animate-rise-in">
      <PageHeader
        title="ALERTS"
        subtitle="Operator notifications raised by the anomaly detection pipeline."
        action={
          <div className="flex items-center gap-2">
            <select
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              className="h-8 rounded-md border bg-[#040a14] px-2 text-[10.5px] text-ink"
              style={{ borderColor: 'rgba(0,217,255,0.2)' }}
            >
              <option value="ALL">ALL</option>
              <option value="NEW">NEW ({counts.NEW})</option>
              <option value="ACKNOWLEDGED">ACKNOWLEDGED ({counts.ACKNOWLEDGED})</option>
              <option value="RESOLVED">RESOLVED ({counts.RESOLVED})</option>
            </select>
            <WindowSelect value={timeWindow} onChange={setTimeWindow} options={WINDOWS} />
          </div>
        }
      />

      {error && <ErrorBanner message={error} onRetry={() => void load(timeWindow)} />}

      <Panel title={`Notifications (${filtered.length})`} bodyClassName="px-2 pb-2">
        {loading ? (
          <LoadingBlock rows={1} height={340} />
        ) : filtered.length === 0 ? (
          <EmptyState message="No alerts in this window" />
        ) : (
          <div className="max-h-[640px] overflow-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Alert</th>
                  <th>Severity</th>
                  <th className="text-right">Risk</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {filtered.map((row) => {
                  const sev = severityStyle(row.severity);
                  const st = statusStyle(row.status);
                  return (
                    <tr key={row.id}>
                      <td className="tabular whitespace-nowrap text-[10px] text-muted">
                        {clockTime(row.ts)}
                        <span className="ml-1 text-muted/60">{dateStamp(row.ts).slice(0, 6)}</span>
                      </td>
                      <td className="max-w-[420px]">
                        <div className="truncate font-medium text-ink">{row.title ?? 'Alert'}</div>
                        <div className="line-clamp-1 text-[9.5px] text-muted">{row.message ?? ''}</div>
                      </td>
                      <td>
                        <span className={`badge ${sev.badge}`}>
                          {String(row.severity ?? 'LOW').toUpperCase()}
                        </span>
                      </td>
                      <td className="tabular text-right font-semibold text-ink">
                        {row.risk_score ?? '--'}
                      </td>
                      <td>
                        <span className={`badge ${st.badge}`}>
                          {String(row.status ?? 'NEW').toUpperCase()}
                        </span>
                      </td>
                      <td className="whitespace-nowrap text-right">
                        {String(row.status).toUpperCase() !== 'RESOLVED' && (
                          <button
                            type="button"
                            className="btn-ghost"
                            disabled={busy === row.id}
                            onClick={() =>
                              void update(
                                row.id,
                                String(row.status).toUpperCase() === 'NEW'
                                  ? 'ACKNOWLEDGED'
                                  : 'RESOLVED',
                              )
                            }
                          >
                            {String(row.status).toUpperCase() === 'NEW' ? 'Acknowledge' : 'Resolve'}
                          </button>
                        )}
                      </td>
                    </tr>
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
