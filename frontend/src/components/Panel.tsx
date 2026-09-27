'use client';

import type { ReactNode } from 'react';

interface PanelProps {
  title?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  /** Rendered top-right of the header row, e.g. a LIVE pill. */
  status?: ReactNode;
}

/** The single glass panel primitive used by every SENTRA surface. */
export function Panel({
  title,
  action,
  status,
  children,
  className = '',
  bodyClassName = '',
}: PanelProps) {
  return (
    <section
      data-audit="panel"
      data-audit-panel={title ?? ''}
      className={`glass-panel glass-panel-hover flex min-w-0 flex-col ${className}`}
    >
      {(title || action || status) && (
        <header className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 px-4 pb-2.5 pt-3.5">
          {title && (
            <h2 className="panel-title flex min-w-0 items-center gap-2">
              <span
                className="inline-block h-3 w-[2px] shrink-0 rounded-full"
                style={{
                  background: 'linear-gradient(180deg, #00D9FF, rgba(0,217,255,0))',
                  boxShadow: '0 0 8px rgba(0,217,255,0.8)',
                }}
              />
              <span className="truncate">{title}</span>
            </h2>
          )}
          {status}
          {action && <div className="ml-auto flex shrink-0 flex-wrap items-center justify-end gap-1.5">{action}</div>}
        </header>
      )}
      <div className={`min-w-0 flex-1 px-4 pb-4 ${bodyClassName}`}>{children}</div>
    </section>
  );
}

/** Small glowing pill, e.g. LIVE. */
export function LivePill({ label = 'Live' }: { label?: string }) {
  return (
    <span
      className="badge badge-normal gap-1.5"
      style={{ boxShadow: '0 0 12px rgba(0,229,160,0.25)' }}
    >
      <span className="status-dot status-dot-live" />
      {label}
    </span>
  );
}

/** Panel section heading used inside panels. */
export function SubLabel({ children }: { children: ReactNode }) {
  return <div className="label-micro mb-1.5">{children}</div>;
}
