'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { PageHeader, ErrorBanner, LoadingBlock, WindowSelect } from '@/components/PageHeader';
import { Panel, LivePill } from '@/components/Panel';
import { MetricRow } from '@/components/MetricRow';
import { SystemRisk } from '@/components/SystemRisk';
import { dashboard, WINDOWS } from '@/lib/api';
import type { DashboardPayload } from '@/lib/types';
import { ACCENT_HEX, axisTime, num } from '@/lib/format';

const TRACKS: { key: string; label: string; accent: keyof typeof ACCENT_HEX; unit: string }[] = [
  { key: 'cpu_percent', label: 'CPU Usage', accent: 'cyan', unit: '%' },
  { key: 'memory_percent', label: 'Memory Usage', accent: 'violet', unit: '%' },
  { key: 'disk_percent', label: 'Disk Usage', accent: 'green', unit: '%' },
  { key: 'load_average', label: 'Load Average', accent: 'blue', unit: '' },
  { key: 'process_count', label: 'Active Processes', accent: 'cyan', unit: '' },
  { key: 'disk_read_mbps', label: 'Disk Read', accent: 'amber', unit: 'MB/s' },
  { key: 'disk_write_mbps', label: 'Disk Write', accent: 'amber', unit: 'MB/s' },
  { key: 'net_sent_mbps', label: 'Network Sent', accent: 'blue', unit: 'MB/s' },
  { key: 'net_recv_mbps', label: 'Network Received', accent: 'blue', unit: 'MB/s' },
];

export default function MonitoringPage() {
  const [data, setData] = useState<DashboardPayload | null>(null);
  const [timeWindow, setTimeWindow] = useState('6h');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (w: string) => {
    try {
      setData(await dashboard(w));
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

  const ts = data?.series?.ts ?? [];
  const metrics = data?.series?.metrics ?? {};

  return (
    <div className="animate-rise-in">
      <PageHeader
        title="LIVE MONITORING"
        subtitle="Real-time system telemetry, resource pressure and composite risk."
        action={<WindowSelect value={timeWindow} onChange={setTimeWindow} options={WINDOWS} />}
      />

      {error && <ErrorBanner message={error} onRetry={() => void load(timeWindow)} />}

      {loading ? (
        <LoadingBlock rows={2} height={260} />
      ) : (
        <>
          <MetricRow data={data} />

          <div className="mb-4 grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,2.2fr)_minmax(0,1fr)]">
            <Panel title="Telemetry Streams" status={<LivePill />}>
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                {TRACKS.map((track) => {
                  const values = metrics[track.key];
                  const points = ts.map((t, i) => ({ t, v: num(values?.[i]) }));
                  const stroke = ACCENT_HEX[track.accent];
                  const last = [...points].reverse().find((p) => p.v !== null)?.v ?? null;
                  return (
                    <div key={track.key} className="min-w-0">
                      <div className="mb-1 flex items-baseline justify-between">
                        <span className="text-[10.5px] text-muted">{track.label}</span>
                        <span
                          className="tabular text-[13px] font-bold"
                          style={{ color: stroke, textShadow: `0 0 12px ${stroke}66` }}
                        >
                          {last === null
                            ? '--'
                            : track.unit === '%'
                              ? `${last.toFixed(1)}%`
                              : track.unit
                                ? `${last.toFixed(2)} ${track.unit}`
                                : last.toFixed(0)}
                        </span>
                      </div>
                      <div className="h-[112px]">
                        {points.length === 0 ? (
                          <div className="flex h-full items-center justify-center text-[10px] text-muted/70">
                            No samples
                          </div>
                        ) : (
                          <ResponsiveContainer width="100%" height="100%">
                            <LineChart data={points} margin={{ top: 4, right: 6, bottom: 0, left: -24 }}>
                              <CartesianGrid
                                stroke="rgba(0,217,255,0.07)"
                                strokeDasharray="2 4"
                                vertical={false}
                              />
                              <XAxis
                                dataKey="t"
                                tickFormatter={axisTime}
                                tick={{ fill: '#8FA7C2', fontSize: 9 }}
                                axisLine={{ stroke: 'rgba(0,217,255,0.14)' }}
                                tickLine={false}
                                minTickGap={26}
                              />
                              <YAxis
                                tick={{ fill: '#8FA7C2', fontSize: 9 }}
                                axisLine={false}
                                tickLine={false}
                                width={42}
                                domain={[0, 'auto']}
                              />
                              <Tooltip
                                contentStyle={{
                                  background: 'rgba(3,10,20,0.96)',
                                  border: '1px solid rgba(0,217,255,0.3)',
                                  borderRadius: 8,
                                  fontSize: 11,
                                }}
                                labelFormatter={(v) => axisTime(v as string)}
                              />
                              {track.unit === '%' && (
                                <ReferenceLine
                                  y={70}
                                  stroke="rgba(255,176,32,0.45)"
                                  strokeDasharray="3 4"
                                />
                              )}
                              <Line
                                type="monotone"
                                dataKey="v"
                                stroke={stroke}
                                strokeWidth={1.6}
                                dot={false}
                                isAnimationActive={false}
                                connectNulls
                                style={{ filter: `drop-shadow(0 0 5px ${stroke}77)` }}
                              />
                            </LineChart>
                          </ResponsiveContainer>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </Panel>

            <SystemRisk risk={data?.risk ?? null} />
          </div>
        </>
      )}
    </div>
  );
}
