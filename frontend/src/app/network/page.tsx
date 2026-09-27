'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { PageHeader, ErrorBanner, LoadingBlock, WindowSelect } from '@/components/PageHeader';
import { Panel, LivePill } from '@/components/Panel';
import { fetchNetwork, WINDOWS } from '@/lib/api';
import type { NetworkSeries } from '@/lib/types';
import { ACCENT_HEX, axisTime, fmt, fmtInt, num } from '@/lib/format';

export default function NetworkPage() {
  const [data, setData] = useState<NetworkSeries | null>(null);
  const [timeWindow, setTimeWindow] = useState('6h');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (w: string) => {
    try {
      setData(await fetchNetwork(w));
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

  const ts = data?.ts ?? [];
  const points = ts.map((t, i) => ({
    t,
    sent: num(data?.sent_mbps?.[i]),
    recv: num(data?.recv_mbps?.[i]),
  }));
  const latest = data?.latest ?? null;

  const total = (key: string) => {
    const value = num(latest?.[key]);
    return value === null ? '--' : fmtInt(value);
  };

  return (
    <div className="animate-rise-in">
      <PageHeader
        title="NETWORK"
        subtitle="Interface counters and throughput. No packet capture or payload inspection."
        action={<WindowSelect value={timeWindow} onChange={setTimeWindow} options={WINDOWS} />}
      />

      {error && <ErrorBanner message={error} onRetry={() => void load(timeWindow)} />}

      <div className="mb-3 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="Interface" value={String(latest?.iface ?? '--')} />
        <Stat label="Sent Mbps" value={fmt(latest?.sent_mbps, 3)} />
        <Stat label="Recv Mbps" value={fmt(latest?.recv_mbps, 3)} />
        <Stat label="Bytes Sent" value={total('bytes_sent')} />
        <Stat label="Bytes Recv" value={total('bytes_recv')} />
        <Stat label="Connections" value={total('connections')} />
      </div>

      <Panel title="Throughput" status={<LivePill />}>
        {loading ? (
          <LoadingBlock rows={1} height={260} />
        ) : points.length === 0 ? (
          <div className="flex h-40 items-center justify-center text-[11px] text-muted/80">
            No network samples in this window
          </div>
        ) : (
          <div className="h-[300px]">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={points} margin={{ top: 6, right: 8, bottom: 0, left: -18 }}>
                <defs>
                  <linearGradient id="net-sent" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={ACCENT_HEX.cyan} stopOpacity={0.3} />
                    <stop offset="100%" stopColor={ACCENT_HEX.cyan} stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="net-recv" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={ACCENT_HEX.blue} stopOpacity={0.3} />
                    <stop offset="100%" stopColor={ACCENT_HEX.blue} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="rgba(0,217,255,0.07)" strokeDasharray="2 4" vertical={false} />
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
                  width={46}
                  tickFormatter={(v: number) => `${v.toFixed(1)}`}
                />
                <Tooltip
                  contentStyle={{
                    background: 'rgba(3,10,20,0.96)',
                    border: '1px solid rgba(0,217,255,0.3)',
                    borderRadius: 8,
                    fontSize: 11,
                  }}
                  labelFormatter={(v) => axisTime(v as string)}
                  formatter={(value, name) => [
                    `${num(value)?.toFixed(3) ?? '--'} MB/s`,
                    String(name).toUpperCase(),
                  ]}
                />
                <Area
                  type="monotone"
                  dataKey="recv"
                  name="recv"
                  stroke={ACCENT_HEX.blue}
                  strokeWidth={1.7}
                  fill="url(#net-recv)"
                  dot={false}
                  isAnimationActive={false}
                  connectNulls
                />
                <Area
                  type="monotone"
                  dataKey="sent"
                  name="sent"
                  stroke={ACCENT_HEX.cyan}
                  strokeWidth={1.7}
                  fill="url(#net-sent)"
                  dot={false}
                  isAnimationActive={false}
                  connectNulls
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}
      </Panel>
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
