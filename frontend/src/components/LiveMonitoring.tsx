'use client';

import { useMemo } from 'react';
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { Panel, LivePill } from './Panel';
import { WINDOWS } from '@/lib/api';
import type { DashboardPayload } from '@/lib/types';
import { ACCENT_HEX, axisTime, fmt, fmtMbps, num } from '@/lib/format';

interface Props {
  data: DashboardPayload | null;
  window: string;
  onWindowChange: (value: string) => void;
}

interface ChartCardProps {
  title: string;
  value: string;
  accent: keyof typeof ACCENT_HEX;
  data: { t: string; v: number | null }[];
  unit: string;
  domain?: [number | 'auto', number | 'auto'];
  decimals?: number;
  spikes?: boolean;
}

/** One neon chart tile inside Live System Monitoring. */
function ChartCard({
  title,
  value,
  accent,
  data,
  unit,
  domain = [0, 'auto'],
  decimals = 0,
  spikes = false,
}: ChartCardProps) {
  const stroke = ACCENT_HEX[accent];
  const gradientId = `grad-${accent}-${title.replace(/\s+/g, '').toLowerCase()}`;

  const ticks = useMemo(() => {
    if (data.length === 0) return [];
    const step = Math.max(1, Math.floor(data.length / 4));
    return data
      .filter((_, i) => i % step === 0 || i === data.length - 1)
      .slice(0, 5)
      .map((d) => d.t);
  }, [data]);

  return (
    <div
      className="rounded-[11px] border p-3 transition-colors"
      style={{ borderColor: 'rgba(0,217,255,0.13)', background: 'rgba(2,6,13,0.66)' }}
    >
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <span className="text-[10.5px] font-medium text-muted">{title}</span>
        <span
          className="tabular text-[14px] font-bold"
          style={{ color: stroke, textShadow: `0 0 14px ${stroke}55` }}
        >
          {value}
        </span>
      </div>

      <div className="h-[124px] w-full">
        {data.length === 0 ? (
          <div className="flex h-full items-center justify-center text-[10.5px] text-muted/70">
            No telemetry in this window
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: -22 }}>
              <defs>
                <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={stroke} stopOpacity={spikes ? 0.34 : 0.26} />
                  <stop offset="100%" stopColor={stroke} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="rgba(0,217,255,0.07)" strokeDasharray="2 4" vertical={false} />
              <XAxis
                dataKey="t"
                ticks={ticks}
                tickFormatter={axisTime}
                tick={{ fill: '#8FA7C2', fontSize: 9 }}
                axisLine={{ stroke: 'rgba(0,217,255,0.14)' }}
                tickLine={false}
                minTickGap={18}
              />
              <YAxis
                domain={domain}
                tick={{ fill: '#8FA7C2', fontSize: 9 }}
                axisLine={false}
                tickLine={false}
                width={44}
                tickFormatter={(v: number) =>
                  unit === '%' ? `${Math.round(v)}%` : unit === 'MB/s' ? v.toFixed(1) : `${Math.round(v)}`
                }
              />
              <Tooltip
                contentStyle={{
                  background: 'rgba(3,10,20,0.96)',
                  border: '1px solid rgba(0,217,255,0.3)',
                  borderRadius: 8,
                  fontSize: 11,
                  color: '#F2F7FF',
                  boxShadow: '0 0 18px rgba(0,150,255,0.2)',
                }}
                labelFormatter={(v) => axisTime(v as string)}
                formatter={(value) => {
                  const n = num(value as unknown) ?? 0;
                  const text =
                    unit === '%'
                      ? `${n.toFixed(decimals)}%`
                      : unit === 'MB/s'
                        ? `${n.toFixed(2)} MB/s`
                        : n.toFixed(decimals);
                  return [text, title];
                }}
              />
              <Area
                type="monotone"
                dataKey="v"
                stroke={stroke}
                strokeWidth={1.7}
                fill={`url(#${gradientId})`}
                dot={false}
                isAnimationActive={false}
                connectNulls
                style={{ filter: `drop-shadow(0 0 5px ${stroke}88)` }}
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}

/** LIVE SYSTEM MONITORING: CPU, memory, network and disk, 2x2. */
export function LiveMonitoring({ data, window, onWindowChange }: Props) {
  const ts = data?.series?.ts ?? [];
  const metrics = data?.series?.metrics ?? {};
  const network = data?.network;

  const toPoints = (values?: (number | null)[]) =>
    ts.map((t, i) => ({ t, v: values?.[i] === undefined ? null : num(values[i]) }));

  const cpuPoints = toPoints(metrics.cpu_percent);
  const memPoints = toPoints(metrics.memory_percent);

  // Network throughput: sent + received, per timestamp. When the window holds no
  // network rows the tile still renders on the system-metric axis with null values
  // so the 2x2 grid stays consistent and nothing is fabricated.
  const netPoints = useMemo(() => {
    const nts = network?.ts?.length ? network.ts : ts;
    const hasNetwork = Boolean(network?.ts?.length);
    const sent = network?.sent_mbps ?? [];
    const recv = network?.recv_mbps ?? [];
    return nts.map((t, i) => {
      if (!hasNetwork) return { t, v: null };
      const s = num(sent[i]) ?? 0;
      const r = num(recv[i]) ?? 0;
      return { t, v: s + r };
    });
  }, [network, ts]);

  // Disk I/O: read + write throughput.
  const diskPoints = useMemo(
    () =>
      ts.map((t, i) => {
        const r = num(metrics.disk_read_mbps?.[i]) ?? 0;
        const w = num(metrics.disk_write_mbps?.[i]) ?? 0;
        return { t, v: r + w };
      }),
    [ts, metrics],
  );

  const last = (points: { v: number | null }[]) => {
    for (let i = points.length - 1; i >= 0; i -= 1) {
      if (points[i].v !== null) return points[i].v as number;
    }
    return null;
  };

  return (
    <Panel
      title="Live System Monitoring"
      status={<LivePill />}
      action={
        <select
          value={window}
          onChange={(e) => onWindowChange(e.target.value)}
          aria-label="Monitoring time window"
          className="rounded-md border bg-[#040a14] px-2 py-1 text-[10px] font-semibold tracking-wide text-ink outline-none"
          style={{ borderColor: 'rgba(0,217,255,0.22)' }}
        >
          {WINDOWS.map((w) => (
            <option key={w.value} value={w.value}>
              {w.label}
            </option>
          ))}
        </select>
      }
    >
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <ChartCard
          title="CPU Usage"
          value={fmt(last(cpuPoints), 1, '%')}
          accent="cyan"
          data={cpuPoints}
          unit="%"
          domain={[0, 100]}
          decimals={1}
        />
        <ChartCard
          title="Memory Usage"
          value={fmt(last(memPoints), 1, '%')}
          accent="violet"
          data={memPoints}
          unit="%"
          domain={[0, 100]}
          decimals={1}
        />
        <ChartCard
          title="Network Activity"
          value={fmtMbps(last(netPoints))}
          accent="blue"
          data={netPoints}
          unit="MB/s"
          decimals={2}
          spikes
        />
        <ChartCard
          title="Disk I/O"
          value={fmtMbps(last(diskPoints))}
          accent="green"
          data={diskPoints}
          unit="MB/s"
          decimals={2}
        />
      </div>
    </Panel>
  );
}

export { ChartCard };
