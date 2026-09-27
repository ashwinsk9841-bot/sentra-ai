'use client';

import Link from 'next/link';
import { ArrowRight } from 'lucide-react';
import { Panel } from './Panel';
import type { AnomalyRow, SentraDevice } from '@/lib/types';
import { clockTime, humanMetric, severityStyle, statusStyle } from '@/lib/format';

interface Props {
  anomalies: AnomalyRow[];
  deviceName?: string | null;
  limit?: number;
}

function statusOf(row: AnomalyRow): string {
  if (row.acknowledged) return 'ACKNOWLEDGED';
  return 'OPEN';
}

/** RECENT ANOMALIES: the compact event table from the backend's anomaly log. */
export function RecentAnomalies({ anomalies, deviceName, limit = 5 }: Props) {
  const rows = anomalies.slice(0, limit);

  return (
    <Panel
      title="Recent Anomalies"
      className="h-full"
      action={
        <Link href="/anomalies" className="btn-ghost">
          View All <ArrowRight size={11} />
        </Link>
      }
      bodyClassName="px-2 pb-2"
    >
      {rows.length === 0 ? (
        <div className="flex h-24 items-center justify-center text-[11px] text-muted/80">
          No anomalies recorded in this window
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="data-table">
            <thead>
              <tr>
                <th>Event</th>
                <th>Device</th>
                <th>Severity</th>
                <th className="text-right">Risk</th>
                <th>Time</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const sev = severityStyle(row.severity);
                const status = statusStyle(statusOf(row));
                return (
                  <tr key={row.id}>
                    <td className="max-w-[240px]">
                      <div className="truncate font-medium text-ink">
                        {humanMetric(row.metric)} deviation
                      </div>
                      <div className="truncate text-[9.5px] text-muted">
                        observed {Number(row.observed_value ?? 0).toFixed(1)} vs{' '}
                        {Number(row.expected_value ?? 0).toFixed(1)} baseline
                      </div>
                    </td>
                    <td className="whitespace-nowrap text-[10.5px] text-muted">
                      {deviceName ?? row.device_id}
                    </td>
                    <td>
                      <span className={`badge ${sev.badge}`}>
                        {String(row.severity ?? 'LOW').toUpperCase()}
                      </span>
                    </td>
                    <td className="tabular text-right font-semibold text-ink">
                      {row.risk_score ?? '--'}
                    </td>
                    <td className="tabular whitespace-nowrap text-[10.5px] text-muted">
                      {clockTime(row.ts)}
                    </td>
                    <td>
                      <span className={`badge ${status.badge}`}>
                        {statusOf(row).toUpperCase()}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

interface TimelineProps {
  events: import('@/lib/types').TimelineEvent[];
  limit?: number;
  title?: string;
}

const TONE_COLOR: Record<string, string> = {
  info: '#00D9FF',
  success: '#00E5A0',
  warning: '#FFB020',
  danger: '#FF4D5E',
};

/** SECURITY EVENT TIMELINE: real system and risk events, newest first. */
export function SecurityTimeline({ events, limit = 6, title = 'Security Event Timeline' }: TimelineProps) {
  const rows = events.slice(0, limit);

  return (
    <Panel
      title={title}
      className="h-full"
      action={
        <Link href="/logs" className="btn-ghost">
          View All <ArrowRight size={11} />
        </Link>
      }
    >
      {rows.length === 0 ? (
        <div className="flex h-24 items-center justify-center text-[11px] text-muted/80">
          No events recorded
        </div>
      ) : (
        <ol className="relative space-y-3 pl-1">
          {/* Connecting rail */}
          <span
            className="absolute bottom-2 left-[7px] top-2 w-px"
            style={{
              background:
                'linear-gradient(180deg, rgba(0,217,255,0.45), rgba(0,217,255,0.06))',
            }}
          />
          {rows.map((event) => {
            const color = TONE_COLOR[event.tone] ?? TONE_COLOR.info;
            return (
              <li key={event.id} className="relative flex gap-3 pl-0">
                <span className="relative z-10 mt-[3px] shrink-0">
                  <span
                    className="block h-[9px] w-[9px] rounded-full"
                    style={{
                      background: color,
                      boxShadow: `0 0 9px ${color}, 0 0 18px ${color}66`,
                    }}
                  />
                  <span
                    className="absolute inset-0 -z-10 block h-[9px] w-[9px] animate-ping rounded-full opacity-40"
                    style={{ background: color }}
                  />
                </span>
                <div className="min-w-0 flex-1 pb-0.5">
                  <div className="flex items-baseline gap-2">
                    <span className="tabular text-[10px] font-semibold text-cyan/90">
                      {clockTime(event.ts)}
                    </span>
                    <span className="truncate text-[11px] font-medium text-ink">
                      {event.title}
                    </span>
                  </div>
                  <div className="mt-0.5 flex items-center gap-1.5">
                    <span
                      className="text-[9px] font-semibold uppercase tracking-wider"
                      style={{ color }}
                    >
                      {event.status}
                    </span>
                    <span className="truncate text-[9.5px] text-muted">{event.detail}</span>
                  </div>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </Panel>
  );
}
