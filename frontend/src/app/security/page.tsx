'use client';

import { useCallback, useEffect, useState } from 'react';
import { CheckCircle2, Database, HardDrive, KeyRound, Server, XCircle } from 'lucide-react';
import { PageHeader, ErrorBanner, LoadingBlock } from '@/components/PageHeader';
import { Panel } from '@/components/Panel';
import { fetchHealth } from '@/lib/api';
import type { HealthPayload } from '@/lib/types';
import { fmt, fmtInt } from '@/lib/format';

const ICONS: Record<string, React.ReactNode> = {
  Database: <Database size={14} strokeWidth={1.7} />,
  'Vector store': <HardDrive size={14} strokeWidth={1.7} />,
  'AI provider': <KeyRound size={14} strokeWidth={1.7} />,
  Server: <Server size={14} strokeWidth={1.7} />,
};

export default function SecurityPage() {
  const [health, setHealth] = useState<HealthPayload | null>(null);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await fetchHealth();
      setHealth(payload.health);
      setCounts(payload.counts);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Request failed');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const overall = health?.ok;

  return (
    <div className="animate-rise-in">
      <PageHeader
        title="SECURITY HEALTH"
        subtitle="Integrity of the storage, vector, embedding and AI subsystems."
        action={
          <div
            className="flex items-center gap-2 rounded-lg border px-3 py-1.5"
            style={{
              borderColor: overall ? 'rgba(0,229,160,0.3)' : 'rgba(255,176,32,0.35)',
              background: overall ? 'rgba(0,229,160,0.07)' : 'rgba(255,176,32,0.08)',
            }}
          >
            <span className={`status-dot ${overall ? 'status-dot-live' : 'status-dot-idle'}`} />
            <span
              className="text-[10px] font-bold tracking-[0.16em]"
              style={{ color: overall ? '#00E5A0' : '#FFB020' }}
            >
              {overall ? 'ALL SYSTEMS HEALTHY' : 'DEGRADED'}
            </span>
          </div>
        }
      />

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      <div className="mb-3 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <Stat label="Devices" value={fmtInt(counts.devices ?? 0)} />
        <Stat label="Anomalies" value={fmtInt(counts.anomalies ?? 0)} />
        <Stat label="Alerts" value={fmtInt(counts.alerts ?? 0)} />
        <Stat label="Documents" value={fmtInt(counts.documents ?? 0)} />
        <Stat label="System events" value={fmtInt(counts.system_events ?? 0)} />
      </div>

      {loading ? (
        <LoadingBlock rows={2} height={200} />
      ) : (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          <Panel title="Subsystem Checks">
            <div className="space-y-2">
              {(health?.checks ?? []).map((check) => (
                <div
                  key={check.name}
                  className="flex items-center gap-3 rounded-lg border px-3 py-2.5"
                  style={{
                    borderColor: check.ok ? 'rgba(0,229,160,0.2)' : 'rgba(255,176,32,0.28)',
                    background: 'rgba(2,6,13,0.6)',
                  }}
                >
                  <span className={check.ok ? 'text-matrix' : 'text-amber'}>
                    {ICONS[check.name] ?? <Server size={14} strokeWidth={1.7} />}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="text-[11.5px] font-semibold text-ink">{check.name}</div>
                    <div className="truncate text-[9.5px] text-muted">{check.detail}</div>
                  </div>
                  {check.latency_ms !== undefined && (
                    <span className="tabular text-[10px] text-muted">
                      {fmt(check.latency_ms, 2)} ms
                    </span>
                  )}
                  {check.ok ? (
                    <CheckCircle2 size={14} className="shrink-0 text-matrix" />
                  ) : (
                    <XCircle size={14} className="shrink-0 text-amber" />
                  )}
                </div>
              ))}
            </div>
          </Panel>

          <Panel title="Storage Backends">
            <div className="space-y-2">
              {(health?.backends ?? []).map((backend) => (
                <div
                  key={backend.name}
                  className="rounded-lg border px-3 py-2.5"
                  style={{
                    borderColor: backend.connected ? 'rgba(0,229,160,0.2)' : 'rgba(255,77,94,0.3)',
                    background: 'rgba(2,6,13,0.6)',
                  }}
                >
                  <div className="flex items-center gap-2">
                    <span className={`status-dot ${backend.connected ? 'status-dot-live' : 'status-dot-down'}`} />
                    <span className="text-[11.5px] font-semibold text-ink">{backend.name}</span>
                    <span className="badge badge-cyan ml-auto">{backend.mode}</span>
                  </div>
                  <div className="mt-1 text-[9.5px] text-muted">{backend.detail}</div>
                  <div className="tabular mt-0.5 text-[9.5px] text-muted">
                    latency {fmt(backend.latency_ms, 3)} ms
                  </div>
                </div>
              ))}
            </div>

            {Array.isArray(health?.problems) && health.problems.length > 0 && (
              <div
                className="mt-3 rounded-lg border px-3 py-2.5"
                style={{ borderColor: 'rgba(255,176,32,0.3)', background: 'rgba(255,176,32,0.07)' }}
              >
                <div className="label-micro mb-1">Problems</div>
                <ul className="space-y-1">
                  {health.problems.map((problem) => (
                    <li key={problem} className="text-[10.5px] text-amber">
                      {problem}
                    </li>
                  ))}
                </ul>
              </div>
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
