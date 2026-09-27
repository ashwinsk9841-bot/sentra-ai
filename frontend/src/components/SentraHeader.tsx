'use client';

import { useEffect, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { Bell, ChevronDown, Search, Settings2, ShieldCheck } from 'lucide-react';
import { NAV } from '@/lib/nav';
import { dashboard } from '@/lib/api';
import type { DashboardPayload } from '@/lib/types';

interface Props {
  collapsed: boolean;
}

export function SentraHeader({ collapsed }: Props) {
  const pathname = usePathname();
  const router = useRouter();
  const [query, setQuery] = useState('');
  const [data, setData] = useState<DashboardPayload | null>(null);

  useEffect(() => {
    let active = true;
    dashboard('1h')
      .then((payload) => {
        if (active) setData(payload);
      })
      .catch(() => {
        if (active) setData(null);
      });
    return () => {
      active = false;
    };
  }, [pathname]);

  const online = Boolean(data?.device);
  // Operational reflects the monitoring stack itself: a reachable storage backend
  // plus a reporting device. The optional LLM provider is surfaced on the Security
  // Health page rather than degrading the whole system indicator.
  const storageUp = Boolean(data?.health?.backends?.some((backend) => backend.connected));
  const operational = storageUp && online;
  const unread = data?.unread ?? 0;
  const page = NAV.find((item) =>
    item.href === '/' ? pathname === '/' : pathname.startsWith(item.href),
  );

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const term = query.trim().toLowerCase();
    if (!term) return;
    // Route the operator's search to the page that can answer it.
    if (term.includes('log')) router.push('/logs');
    else if (term.includes('anomal')) router.push('/anomalies');
    else if (term.includes('alert')) router.push('/alerts');
    else if (term.includes('device')) router.push('/devices');
    else if (term.includes('process')) router.push('/processes');
    else router.push('/anomalies');
  };

  return (
    <header
      className="sticky top-0 z-30 flex items-center gap-4 border-b px-5 sm:px-6 lg:px-7"
      style={{
        height: 'var(--header-h)',
        borderColor: 'rgba(0,217,255,0.12)',
        background: 'rgba(2,5,10,0.72)',
        backdropFilter: 'blur(12px)',
        WebkitBackdropFilter: 'blur(12px)',
        marginLeft: collapsed ? 0 : undefined,
      }}
    >
      {/* Search */}
      <form onSubmit={submit} className="relative flex min-w-0 flex-1 max-w-[520px] items-center">
        <Search
          size={15}
          strokeWidth={1.7}
          className="pointer-events-none absolute left-3 text-cyan/70"
        />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search devices, logs, anomalies..."
          aria-label="Search devices, logs and anomalies"
          className="h-9 w-full rounded-lg border bg-[#040a14]/80 pl-9 pr-16 text-[12.5px] text-ink outline-none transition-all placeholder:text-muted/70 focus:shadow-neon-cyan"
          style={{ borderColor: 'rgba(0,217,255,0.22)' }}
        />
        <kbd
          className="pointer-events-none absolute right-2.5 rounded border px-1.5 py-0.5 text-[9.5px] font-semibold tracking-wide text-muted"
          style={{ borderColor: 'rgba(0,217,255,0.22)', background: 'rgba(0,217,255,0.05)' }}
        >
          Ctrl K
        </kbd>
      </form>

      {/* Current section */}
      <div className="hidden items-center gap-2 xl:flex">
        <ShieldCheck size={13} strokeWidth={1.7} className="text-cyan/80" />
        <span className="text-[10px] font-semibold tracking-[0.16em] text-muted">
          {page?.label ?? 'Overview'}
        </span>
      </div>

      <div className="ml-auto flex items-center gap-2 sm:gap-3">
        {/* Operational status */}
        <div
          className="flex items-center gap-2 rounded-lg border px-2.5 py-1.5"
          style={{ borderColor: 'rgba(0,229,160,0.22)', background: 'rgba(0,229,160,0.05)' }}
          title={operational ? 'System operational' : 'System degraded'}
        >
          <span className={`status-dot ${operational ? 'status-dot-live' : 'status-dot-idle'}`} />
          <span className="hidden text-[9.5px] font-bold tracking-[0.16em] text-matrix sm:inline">
            {operational ? 'SYSTEM OPERATIONAL' : 'DEGRADED'}
          </span>
        </div>

        {/* Notifications */}
        <button
          type="button"
          aria-label={`Notifications${unread ? `, ${unread} unread` : ''}`}
          onClick={() => router.push('/alerts')}
          className="relative flex h-9 w-9 items-center justify-center rounded-lg border text-muted transition-all hover:text-cyan hover:shadow-neon-cyan"
          style={{ borderColor: 'rgba(0,217,255,0.18)', background: 'rgba(4,10,20,0.7)' }}
        >
          <Bell size={15} strokeWidth={1.7} />
          {unread > 0 && (
            <span
              className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-[9px] font-bold text-[#04070d]"
              style={{ background: '#FF4D5E', boxShadow: '0 0 10px rgba(255,77,94,0.85)' }}
            >
              {unread > 99 ? '99+' : unread}
            </span>
          )}
        </button>

        {/* Settings */}
        <button
          type="button"
          aria-label="Settings"
          onClick={() => router.push('/settings')}
          className="flex h-9 w-9 items-center justify-center rounded-lg border text-muted transition-all hover:text-cyan hover:shadow-neon-cyan"
          style={{ borderColor: 'rgba(0,217,255,0.18)', background: 'rgba(4,10,20,0.7)' }}
        >
          <Settings2 size={15} strokeWidth={1.7} />
        </button>

        {/* Profile */}
        <button
          type="button"
          className="flex items-center gap-2.5 rounded-lg border py-1 pl-1 pr-2 transition-all hover:shadow-neon-cyan"
          style={{ borderColor: 'rgba(0,217,255,0.18)', background: 'rgba(4,10,20,0.7)' }}
        >
          <span
            className="flex h-7 w-7 items-center justify-center rounded-full text-[10.5px] font-bold text-[#04070d]"
            style={{
              background: 'linear-gradient(135deg, #00D9FF, #1677FF)',
              boxShadow: '0 0 12px rgba(0,217,255,0.5)',
            }}
          >
            AD
          </span>
          <span className="hidden text-left leading-tight sm:block">
            <span className="block text-[11.5px] font-semibold text-ink">Admin</span>
            <span className="block text-[9.5px] text-muted">Operator</span>
          </span>
          <ChevronDown size={13} className="text-muted" />
        </button>
      </div>
    </header>
  );
}
