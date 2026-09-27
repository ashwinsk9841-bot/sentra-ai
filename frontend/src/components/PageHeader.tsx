'use client';

import type { ReactNode } from 'react';
import { RefreshCw, WifiOff } from 'lucide-react';

/** Page heading used by every route other than Overview. */
export function PageHeader({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1
          className="font-display text-[26px] font-bold leading-none tracking-[0.08em]"
          style={{ color: '#7FE9FF', textShadow: '0 0 20px rgba(0,217,255,0.4)' }}
        >
          {title}
        </h1>
        <p className="mt-1.5 text-[11.5px] text-muted">{subtitle}</p>
      </div>
      {action}
    </div>
  );
}

/** Standard error banner for a failed backend call. */
export function ErrorBanner({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div
      className="mb-4 flex items-center gap-3 rounded-xl border px-4 py-3"
      style={{ borderColor: 'rgba(255,77,94,0.4)', background: 'rgba(255,77,94,0.08)' }}
    >
      <WifiOff size={16} className="shrink-0 text-danger" />
      <div className="min-w-0 flex-1">
        <div className="text-[12px] font-semibold text-danger">Backend unreachable</div>
        <p className="truncate text-[10.5px] text-muted">{message}</p>
      </div>
      {onRetry && (
        <button type="button" className="btn-neon" onClick={onRetry}>
          <RefreshCw size={12} /> Retry
        </button>
      )}
    </div>
  );
}

/** Placeholder block used while a route is loading. */
export function LoadingBlock({ rows = 3, height = 220 }: { rows?: number; height?: number }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="glass-panel animate-pulse" style={{ height }} />
      ))}
    </div>
  );
}

/** Neutral empty state. */
export function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex h-32 items-center justify-center text-[11px] text-muted/80">{message}</div>
  );
}

/** Window selector bound to a real backend window value. */
export function WindowSelect({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      aria-label="Time window"
      className="rounded-md border bg-[#040a14] px-2.5 py-1.5 text-[10.5px] font-semibold tracking-wide text-ink outline-none transition-shadow focus:shadow-neon-cyan"
      style={{ borderColor: 'rgba(0,217,255,0.22)' }}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}
