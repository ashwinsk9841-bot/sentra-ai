'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { PageHeader, ErrorBanner, LoadingBlock, WindowSelect } from '@/components/PageHeader';
import { Panel } from '@/components/Panel';
import { fetchAnalytics, WINDOWS } from '@/lib/api';
import { ACCENT_HEX, fmt, fmtInt, titleCase } from '@/lib/format';

const BAR_COLORS = ['#00D9FF', '#1677FF', '#9B6CFF', '#00E5A0', '#FFB020', '#FF4D5E'];

/** Canonical severity order, least to most severe. */
const SEVERITY_ORDER = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'] as const;

/**
 * Upper bound on bar thickness. Recharts has no default cap, so a chart that
 * ever collapses to one category would otherwise stretch a bar across the full
 * plot width. Keeps bars looking like bars in every window.
 */
const SEVERITY_BAR_MAX = 44;

export default function AnalyticsPage() {
  const [data, setData] = useState<{
    summary: Record<string, unknown>;
    reliability: Record<string, number | string | null>;
    correlation: Record<string, unknown>[];
    hourly_profile: Record<string, unknown>[];
  } | null>(null);
  const [timeWindow, setTimeWindow] = useState('24h');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (w: string) => {
    setLoading(true);
    try {
      setData(await fetchAnalytics(w));
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

  const severity = (data?.summary?.anomalies as Record<string, unknown>) ?? {};
  const bySeverity = (severity.by_severity as Record<string, number>) ?? {};
  const byMetric = (severity.by_metric as Record<string, number>) ?? {};
  const alerts = (data?.summary?.alerts as Record<string, unknown>) ?? {};
  const reliability = data?.reliability ?? {};

  // Always emit the four canonical severities.
  //
  // The backend only returns the severities that actually occurred, so a
  // window containing a single severity produced a one-category chart. Recharts
  // gives a lone category the entire plot width, which rendered as one giant
  // solid bar (measured: width 517px of a 517px plot) instead of a chart.
  // Padding the missing severities with 0 keeps four real categories on the
  // X-axis and makes the shape robust for any window.
  const hasSeverityData = Object.keys(bySeverity).length > 0;
  const severityRows = SEVERITY_ORDER.map((name) => ({
    name,
    value: Math.max(0, Math.trunc(Number(bySeverity[name]) || 0)),
  }));

  const metricRows = Object.entries(byMetric)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8)
    .map(([key, value]) => ({ name: titleCase(key), value: Number(value) }));

  const hourly = (data?.hourly_profile ?? []).slice(0, 24);

  return (
    <div className="animate-rise-in">
      <PageHeader
        title="ANALYTICS"
        subtitle="Distribution of anomalies, correlation between metrics and reporting reliability."
        action={<WindowSelect value={timeWindow} onChange={setTimeWindow} options={WINDOWS} />}
      />

      {error && <ErrorBanner message={error} onRetry={() => void load(timeWindow)} />}

      <div className="mb-3 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="Samples" value={fmtInt(Number(data?.summary?.samples ?? 0))} />
        <Stat
          label="Anomalies"
          value={fmtInt(Number((severity.total as number) ?? 0))}
        />
        <Stat
          label="Alerts"
          value={fmtInt(Number((alerts.total as number) ?? 0))}
        />
        <Stat label="Mean risk" value={fmt(Number(reliability.mean_risk ?? 0), 1)} />
        <Stat label="Max risk" value={fmtInt(Number(reliability.max_risk ?? 0))} />
        <Stat
          label="Coverage"
          value={`${fmt(Number(reliability.coverage_pct ?? 0), 0)}%`}
        />
      </div>

      {loading ? (
        <LoadingBlock rows={2} height={240} />
      ) : (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          <Panel title="Anomalies by Severity">
            {!hasSeverityData ? (
              <p className="text-[11px] text-muted/80">No anomalies in this window.</p>
            ) : (
              <div className="h-[220px]">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={severityRows} margin={{ top: 6, right: 8, bottom: 0, left: -20 }}>
                    <CartesianGrid stroke="rgba(0,217,255,0.07)" strokeDasharray="2 4" vertical={false} />
                    <XAxis
                      dataKey="name"
                      tick={{ fill: '#8FA7C2', fontSize: 10 }}
                      axisLine={{ stroke: 'rgba(0,217,255,0.14)' }}
                      tickLine={false}
                    />
                    <YAxis tick={{ fill: '#8FA7C2', fontSize: 9 }} axisLine={false} tickLine={false} width={38} />
                    <Tooltip
                      cursor={{ fill: 'rgba(0,217,255,0.05)' }}
                      contentStyle={{
                        background: 'rgba(3,10,20,0.96)',
                        border: '1px solid rgba(0,217,255,0.3)',
                        borderRadius: 8,
                        fontSize: 11,
                      }}
                    />
                    <Bar
                      dataKey="value"
                      radius={[4, 4, 0, 0]}
                      isAnimationActive={false}
                      maxBarSize={SEVERITY_BAR_MAX}
                    >
                      {severityRows.map((row, i) => (
                        <Cell
                          key={row.name}
                          fill={
                            row.name === 'CRITICAL'
                              ? ACCENT_HEX.red
                              : row.name === 'HIGH'
                                ? ACCENT_HEX.amber
                                : row.name === 'MEDIUM'
                                  ? ACCENT_HEX.violet
                                  : ACCENT_HEX.green
                          }
                          opacity={0.9 - i * 0.05}
                        />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </Panel>

          <Panel title="Anomalies by Metric">
            {metricRows.length === 0 ? (
              <p className="text-[11px] text-muted/80">No metric distribution available.</p>
            ) : (
              <div className="h-[220px]">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart
                    data={metricRows}
                    layout="vertical"
                    margin={{ top: 4, right: 12, bottom: 0, left: 8 }}
                  >
                    <CartesianGrid stroke="rgba(0,217,255,0.07)" strokeDasharray="2 4" horizontal={false} />
                    <XAxis
                      type="number"
                      tick={{ fill: '#8FA7C2', fontSize: 9 }}
                      axisLine={false}
                      tickLine={false}
                    />
                    <YAxis
                      type="category"
                      dataKey="name"
                      tick={{ fill: '#8FA7C2', fontSize: 9.5 }}
                      axisLine={false}
                      tickLine={false}
                      width={104}
                    />
                    <Tooltip
                      cursor={{ fill: 'rgba(0,217,255,0.05)' }}
                      contentStyle={{
                        background: 'rgba(3,10,20,0.96)',
                        border: '1px solid rgba(0,217,255,0.3)',
                        borderRadius: 8,
                        fontSize: 11,
                      }}
                    />
                    <Bar dataKey="value" radius={[0, 4, 4, 0]} isAnimationActive={false}>
                      {metricRows.map((row, i) => (
                        <Cell key={row.name} fill={BAR_COLORS[i % BAR_COLORS.length]} opacity={0.85} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </Panel>

          <Panel title="Metric Correlation">
            {(data?.correlation ?? []).length === 0 ? (
              <p className="text-[11px] text-muted/80">
                Not enough overlapping samples to correlate metrics in this window.
              </p>
            ) : (
              <div className="max-h-[260px] overflow-auto">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Metric</th>
                      <th className="text-right">Pearson r</th>
                      <th className="text-right">Samples</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(data?.correlation ?? []).map((row, i) => {
                      const r = row as Record<string, unknown>;
                      return (
                        <tr key={String(r.metric ?? i)}>
                          <td className="text-ink">{titleCase(String(r.metric ?? ''))}</td>
                          <td className="tabular text-right">
                            <span
                              style={{
                                color:
                                  Math.abs(Number(r.correlation ?? 0)) > 0.6
                                    ? '#FFB020'
                                    : '#8FA7C2',
                              }}
                            >
                              {fmt(Number(r.correlation ?? 0), 3)}
                            </span>
                          </td>
                          <td className="tabular text-right text-muted">
                            {fmtInt(Number(r.samples ?? 0))}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>

          <Panel title="Reporting Reliability">
            <div className="space-y-2 text-[11px]">
              <ReliabilityRow
                label="Expected samples"
                value={fmtInt(Number(reliability.expected_samples ?? 0))}
              />
              <ReliabilityRow
                label="Received samples"
                value={fmtInt(Number(reliability.received_samples ?? 0))}
              />
              <ReliabilityRow
                label="Sample interval"
                value={`${String(reliability.sample_interval_s ?? '--')}s`}
              />
              <ReliabilityRow
                label="Measured over"
                value={`${fmt(Number(reliability.measured_over_minutes ?? 0), 1)} min`}
              />
              <ReliabilityRow
                label="Alerts resolved"
                value={`${fmtInt(Number(reliability.alerts_resolved ?? 0))} / ${fmtInt(
                  Number(reliability.alerts_total ?? 0),
                )}`}
              />
              <ReliabilityRow
                label="Device status"
                value={String(reliability.device_status ?? '--')}
              />
            </div>
            {hourly.length > 0 && (
              <p className="mt-3 text-[10px] text-muted/70">
                {hourly.length} hourly profile buckets recorded in this window.
              </p>
            )}
          </Panel>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="glass-panel glass-panel-hover px-3.5 py-3">
      <div className="label-micro truncate">{label}</div>
      <div className="metric-value mt-1 truncate text-[16px]">{value}</div>
    </div>
  );
}

function ReliabilityRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-cyan/8 pb-1.5">
      <span className="text-muted">{label}</span>
      <span className="tabular font-semibold text-ink">{value}</span>
    </div>
  );
}
