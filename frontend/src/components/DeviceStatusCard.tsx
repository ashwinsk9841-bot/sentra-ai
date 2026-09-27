'use client';

import { Cpu, Radio, Timer } from 'lucide-react';
import type { SentraDevice } from '@/lib/types';
import { fmtDuration, timeAgo } from '@/lib/format';

interface Props {
  device: SentraDevice | null;
  windowLabel?: string;
  uptimeSeconds?: number | null;
}

/**
 * Device status card in the hero. `CONNECTED` is shown only when the backend
 * reports the device as authorised/reachable; otherwise the real state is shown.
 */
export function DeviceStatusCard({ device, uptimeSeconds }: Props) {
  const connected = Boolean(device && String(device.status).toUpperCase() === 'AUTHORIZED');

  return (
    <div
      className="rounded-[12px] border p-3.5"
      style={{
        borderColor: connected ? 'rgba(0,229,160,0.28)' : 'rgba(255,176,32,0.3)',
        background: 'linear-gradient(155deg, rgba(0,229,160,0.07), rgba(4,10,20,0.72))',
        boxShadow: 'inset 0 0 26px rgba(0,229,160,0.05)',
      }}
    >
      <div className="flex items-center gap-2">
        <Radio
          size={14}
          strokeWidth={1.7}
          className={connected ? 'text-matrix' : 'text-amber'}
          style={{ filter: `drop-shadow(0 0 6px ${connected ? 'rgba(0,229,160,0.8)' : 'rgba(255,176,32,0.8)'})` }}
        />
        <span className="truncate font-display text-[12.5px] font-bold tracking-[0.1em] text-ink">
          {device?.name ?? 'NO DEVICE'}
        </span>
        <span className={`badge ml-auto ${connected ? 'badge-normal' : 'badge-elevated'}`}>
          {connected ? 'Connected' : device?.status ?? 'Offline'}
        </span>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2.5">
        <Field
          icon={<Cpu size={11} strokeWidth={1.8} />}
          label="Last Update"
          value={timeAgo(device?.last_seen)}
        />
        <Field
          icon={<Timer size={11} strokeWidth={1.8} />}
          label="Uptime"
          value={uptimeSeconds != null ? fmtDuration(uptimeSeconds) : '--'}
        />
        <Field
          icon={<Radio size={11} strokeWidth={1.8} />}
          label="Agent"
          value={device?.agent_version ?? '--'}
        />
        <Field
          icon={<Timer size={11} strokeWidth={1.8} />}
          label="Window"
          value={device ? 'Live' : '--'}
        />
      </div>
    </div>
  );
}

function Field({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div
      className="rounded-lg border px-2 py-1.5"
      style={{ borderColor: 'rgba(0,217,255,0.14)', background: 'rgba(2,5,10,0.45)' }}
    >
      <div className="flex items-center gap-1 text-muted">
        {icon}
        <span className="text-[8.5px] font-semibold uppercase tracking-[0.12em]">{label}</span>
      </div>
      <div className="tabular mt-0.5 truncate text-[11.5px] font-semibold text-ink">{value}</div>
    </div>
  );
}
