'use client';

import { useCallback, useEffect, useState } from 'react';
import { KeyRound, Loader2, Server, ShieldCheck } from 'lucide-react';
import { PageHeader, ErrorBanner, LoadingBlock, EmptyState } from '@/components/PageHeader';
import { Panel } from '@/components/Panel';
import { createPairingCode, fetchAgent, fetchFleet, setDeviceStatus } from '@/lib/api';
import type { AgentStatus, FleetRow } from '@/lib/types';
import { fmt, fmtDuration, timeAgo, usageBand } from '@/lib/format';

export default function DevicesPage() {
  const [fleet, setFleet] = useState<FleetRow[]>([]);
  const [agent, setAgent] = useState<AgentStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [code, setCode] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [fleetPayload, agentPayload] = await Promise.all([fetchFleet(), fetchAgent()]);
      setFleet(fleetPayload.fleet);
      setAgent(agentPayload);
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

  const pair = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await createPairingCode();
      setCode(String(result.code ?? result.pairing_code ?? JSON.stringify(result)));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create a pairing code');
    } finally {
      setBusy(false);
    }
  };

  const setStatus = async (deviceId: string, status: string) => {
    setBusy(true);
    try {
      await setDeviceStatus(deviceId, status);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not update the device');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="animate-rise-in">
      <PageHeader
        title="DEVICES"
        subtitle="Authorised Sentra agents reporting system telemetry."
        action={
          <button type="button" className="btn-neon" onClick={() => void pair()} disabled={busy}>
            {busy ? <Loader2 size={12} className="animate-spin" /> : <KeyRound size={12} />}
            Pairing Code
          </button>
        }
      />

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      {code && (
        <div
          className="mb-3 rounded-xl border px-4 py-3"
          style={{ borderColor: 'rgba(0,229,160,0.35)', background: 'rgba(0,229,160,0.07)' }}
        >
          <div className="label-micro">Pairing code</div>
          <div className="tabular mt-1 font-mono text-[20px] font-bold tracking-[0.2em] text-matrix">
            {code}
          </div>
        </div>
      )}

      <div className="mb-3 grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <Panel title={`Fleet (${fleet.length})`} bodyClassName="px-2 pb-2">
          {loading ? (
            <LoadingBlock rows={1} height={240} />
          ) : fleet.length === 0 ? (
            <EmptyState message="No devices have paired with this Sentra instance" />
          ) : (
            <div className="space-y-2">
              {fleet.map((row) => {
                const online = row.online;
                const cpu = usageBand(row.cpu_percent);
                return (
                  <div
                    key={row.device_id}
                    className="rounded-lg border px-3.5 py-3"
                    style={{
                      borderColor: online ? 'rgba(0,229,160,0.25)' : 'rgba(255,176,32,0.25)',
                      background: 'rgba(2,6,13,0.6)',
                    }}
                  >
                    <div className="flex flex-wrap items-center gap-2.5">
                      <Server
                        size={15}
                        strokeWidth={1.7}
                        className={online ? 'text-matrix' : 'text-amber'}
                      />
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-[12.5px] font-semibold text-ink">
                          {row.name}
                        </div>
                        <div className="truncate text-[9.5px] text-muted">
                          {row.device_id} &middot; {row.os_name ?? 'unknown OS'} &middot;{' '}
                          {row.agent_version ?? 'no agent'}
                        </div>
                      </div>
                      <span className={`badge ${online ? 'badge-normal' : 'badge-elevated'}`}>
                        {String(row.status ?? 'UNKNOWN').toUpperCase()}
                      </span>
                      <button
                        type="button"
                        className="btn-ghost"
                        disabled={busy}
                        onClick={() =>
                          void setStatus(
                            row.device_id,
                            online ? 'REVOKED' : 'AUTHORIZED',
                          )
                        }
                      >
                        {online ? 'Revoke' : 'Authorize'}
                      </button>
                    </div>

                    <div className="mt-2.5 grid grid-cols-2 gap-2 sm:grid-cols-4">
                      <Metric label="CPU" value={fmt(row.cpu_percent, 1, '%')} accent={cpu.accent} />
                      <Metric
                        label="Memory"
                        value={fmt(row.memory_percent, 1, '%')}
                        accent={usageBand(row.memory_percent).accent}
                      />
                      <Metric
                        label="Disk"
                        value={fmt(row.disk_percent, 1, '%')}
                        accent={usageBand(row.disk_percent).accent}
                      />
                      <Metric
                        label="Risk"
                        value={row.risk_score === null ? '--' : `${row.risk_score}/100`}
                        accent="amber"
                      />
                    </div>

                    <div className="mt-2 text-[9.5px] text-muted">
                      Last seen {timeAgo(row.last_seen)}
                      {row.last_seen_age_s !== null
                        ? ` (${fmtDuration(row.last_seen_age_s)} ago)`
                        : ''}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </Panel>

        <div className="space-y-3">
          <Panel title="Agent Status">
            {loading || !agent ? (
              <LoadingBlock rows={1} height={140} />
            ) : (
              <div className="space-y-2.5 text-[10.5px]">
                <Row label="Transport mode" value={String(agent.transport?.mode ?? '--')} />
                <Row label="Update interval" value={`${agent.collection?.interval_s ?? '--'}s`} />
                <Row
                  label="psutil available"
                  value={agent.collection?.psutil_available ? 'yes' : 'no'}
                />
                <Row
                  label="Backend"
                  value={String(agent.backend?.name ?? '--')}
                />
                <Row
                  label="Backend connected"
                  value={agent.backend?.connected ? 'yes' : 'no'}
                />
                <div>
                  <div className="label-micro mb-1">Collected metrics</div>
                  <div className="flex flex-wrap gap-1">
                    {(agent.collection?.metrics as string[] | undefined)?.map((m) => (
                      <span key={m} className="badge badge-cyan">
                        {m}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </Panel>

          <Panel title="Data Boundary">
            <ul className="space-y-1.5">
              {(agent?.data_boundary ?? []).map((line) => (
                <li key={line} className="flex gap-1.5 text-[10.5px] text-muted">
                  <ShieldCheck size={11} className="mt-0.5 shrink-0 text-cyan/70" />
                  <span>{line}</span>
                </li>
              ))}
            </ul>
          </Panel>
        </div>
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-cyan/8 pb-1.5">
      <span className="text-muted">{label}</span>
      <span className="font-semibold text-ink">{value}</span>
    </div>
  );
}

function Metric({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent: string;
}) {
  const color =
    accent === 'green'
      ? '#00E5A0'
      : accent === 'red'
        ? '#FF4D5E'
        : accent === 'amber'
          ? '#FFB020'
          : '#00D9FF';
  return (
    <div
      className="rounded-md border px-2 py-1.5"
      style={{ borderColor: 'rgba(0,217,255,0.12)', background: 'rgba(2,5,10,0.5)' }}
    >
      <div className="label-micro">{label}</div>
      <div className="tabular mt-0.5 text-[12px] font-bold" style={{ color }}>
        {value}
      </div>
    </div>
  );
}
