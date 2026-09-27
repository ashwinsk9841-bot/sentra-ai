'use client';

import {
  Activity,
  Cpu,
  HardDrive,
  HeartPulse,
  MemoryStick,
  Network as NetworkIcon,
  TriangleAlert,
} from 'lucide-react';
import { MetricCard, tail } from './MetricCard';
import type { DashboardPayload } from '@/lib/types';
import {
  fmt,
  fmtInt,
  fmtMbps,
  fmtPadded,
  num,
  riskBand,
  usageBand,
  usageScore,
} from '@/lib/format';

interface Props {
  data: DashboardPayload | null;
}

/**
 * The seven headline metrics, in the order fixed by the design spec.
 * Every value is the real backend reading; the reference numbers in the spec are
 * only used when the backend has no reading for that metric yet.
 */
export function MetricRow({ data }: Props) {
  const latest = data?.latest ?? {};
  const metrics = data?.series?.metrics ?? {};

  const cpu = num(latest.cpu_percent);
  const memory = num(latest.memory_percent);
  const disk = num(latest.disk_percent);

  // System Health is the inverse of the worst resource pressure, on Sentra's
  // 0-100 scale, so it is directly comparable to the risk score.
  const pressures = [usageScore(cpu), usageScore(memory), usageScore(disk)].filter(
    (v): v is number => v !== null,
  );
  const health = pressures.length ? Math.round(Math.min(...pressures)) : null;

  const netActivity = num(data?.net_activity_mbps);
  const anomalies = data?.anomalies ?? [];
  const activeAnomalies = anomalies.length;
  const highAnomalies = anomalies.filter(
    (a) => String(a.severity).toUpperCase() === 'HIGH' || String(a.severity).toUpperCase() === 'CRITICAL',
  ).length;
  const risk = data?.risk?.score ?? null;
  const riskStyle = riskBand(risk);
  const healthStyle = riskBand(health);
  const cpuStyle = usageBand(cpu);
  const memStyle = usageBand(memory);
  const diskStyle = usageBand(disk);
  const netStyle = usageBand(netActivity === null ? null : Math.min(100, netActivity));

  return (
    <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <MetricCard
        title="System Health"
        value={health === null ? '--' : `${health}%`}
        badge={healthStyle.label}
        badgeClass={healthStyle.badge}
        accent={healthStyle.accent}
        icon={<HeartPulse size={14} strokeWidth={1.8} />}
        series={tail(metrics.load_average)}
        hint="inverse of peak pressure"
      />
      <MetricCard
        title="CPU Usage"
        value={fmt(cpu, 1, '%')}
        badge={cpuStyle.label}
        badgeClass={cpuStyle.badge}
        accent={cpuStyle.accent}
        icon={<Cpu size={14} strokeWidth={1.8} />}
        series={tail(metrics.cpu_percent)}
      />
      <MetricCard
        title="Memory Usage"
        value={fmt(memory, 1, '%')}
        badge={memStyle.label}
        badgeClass={memStyle.badge}
        accent={memStyle.accent}
        icon={<MemoryStick size={14} strokeWidth={1.8} />}
        series={tail(metrics.memory_percent)}
      />
      <MetricCard
        title="Disk Usage"
        value={fmt(disk, 1, '%')}
        badge={diskStyle.label}
        badgeClass={diskStyle.badge}
        accent={diskStyle.accent}
        icon={<HardDrive size={14} strokeWidth={1.8} />}
        series={tail(metrics.disk_percent)}
      />
      <MetricCard
        title="Network Activity"
        value={fmtMbps(netActivity)}
        badge={netStyle.label}
        badgeClass={netStyle.badge}
        accent={netStyle.accent}
        icon={<NetworkIcon size={14} strokeWidth={1.8} />}
        series={tail(metrics.net_sent_mbps)}
      />
      <MetricCard
        title="Active Anomalies"
        value={fmtPadded(activeAnomalies)}
        badge={highAnomalies > 0 ? `${highAnomalies} High` : 'None'}
        badgeClass={highAnomalies > 0 ? 'badge-high' : 'badge-normal'}
        accent={highAnomalies > 0 ? 'red' : 'green'}
        icon={<TriangleAlert size={14} strokeWidth={1.8} />}
        series={tail(metrics.load_average)}
        hint={`${fmtInt(data?.counts?.anomalies)} recorded`}
      />
      <MetricCard
        title="Risk Score"
        value={risk === null ? '--' : `${Math.round(risk)} / 100`}
        badge={riskStyle.label}
        badgeClass={riskStyle.badge}
        accent={riskStyle.accent}
        icon={<Activity size={14} strokeWidth={1.8} />}
        series={tail(metrics.process_count)}
      />
    </div>
  );
}
