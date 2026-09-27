'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useState } from 'react';
import { ChevronLeft, ChevronRight, ShieldCheck } from 'lucide-react';
import { NAV, NAV_GROUPS } from '@/lib/nav';
import { isoDay } from '@/lib/format';

interface Props {
  collapsed: boolean;
  onToggle: () => void;
}

function BrandMark({ size = 34 }: { size?: number }) {
  return (
    <span className="relative inline-flex shrink-0 items-center justify-center">
      <span
        className="absolute inset-0 rounded-[10px] opacity-70"
        style={{ background: 'radial-gradient(circle, rgba(0,217,255,0.35), transparent 70%)' }}
      />
      <ShieldCheck
        size={size}
        strokeWidth={1.5}
        className="relative text-cyan"
        style={{ filter: 'drop-shadow(0 0 8px rgba(0,217,255,0.75))' }}
      />
    </span>
  );
}

export function SentraSidebar({ collapsed, onToggle }: Props) {
  const pathname = usePathname();
  const [now, setNow] = useState<Date | null>(null);

  useEffect(() => {
    setNow(new Date());
    const id = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(id);
  }, []);

  const isActive = (href: string) =>
    href === '/' ? pathname === '/' : pathname === href || pathname.startsWith(`${href}/`);

  return (
    <>
      {/* Fixed rail */}
      <aside
        className="fixed inset-y-0 left-0 z-40 hidden flex-col border-r lg:flex"
        style={{
          width: collapsed ? 0 : 'var(--sidebar-w)',
          background: 'linear-gradient(180deg, rgba(3,8,18,0.94), rgba(2,5,10,0.97))',
          borderColor: 'rgba(0,217,255,0.15)',
          backdropFilter: 'blur(10px)',
          transition: 'width 0.3s ease',
          overflow: 'hidden',
        }}
      >
        {/* Brand - the whole area links to the Overview dashboard */}
        <Link
          href="/"
          aria-label="SENTRA AI - go to Overview"
          className="flex items-start gap-3 px-4 pb-4 pt-5"
        >
          <BrandMark />
          {!collapsed && (
            <div className="min-w-0 flex-1">
              <div
                className="font-display text-[17px] font-bold leading-none tracking-[0.16em] text-ink"
                style={{ textShadow: '0 0 16px rgba(0,217,255,0.45)' }}
              >
                SENTRA AI
              </div>
              <div className="mt-1.5 text-[8.5px] font-semibold tracking-[0.24em] text-cyan/80">
                SYSTEM INTELLIGENCE
              </div>
            </div>
          )}
        </Link>

        {/* Navigation */}
        <nav className="flex-1 overflow-y-auto px-3 pb-4">
          {NAV_GROUPS.map((group) => (
            <div key={group.id} className="mb-1">
              {!collapsed && (
                <div className="label-micro px-2 pb-1.5 pt-3 text-[8.5px] opacity-70">
                  {group.label}
                </div>
              )}
              {NAV.filter((item) => item.group === group.id).map((item) => {
                const Icon = item.icon;
                const active = isActive(item.href);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={`nav-item mb-0.5 ${active ? 'nav-item-active' : ''}`}
                    title={item.label}
                  >
                    <Icon size={15} strokeWidth={1.6} className="shrink-0 text-muted" />
                    {!collapsed && <span className="truncate">{item.label}</span>}
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>

        {/* Demo mode + system time */}
        <div className="px-3 pb-4">
          <div
            className="rounded-[12px] border p-3"
            style={{
              borderColor: 'rgba(0,217,255,0.22)',
              background: 'linear-gradient(160deg, rgba(0,217,255,0.07), rgba(2,5,10,0.4))',
              boxShadow: 'inset 0 0 22px rgba(0,217,255,0.05)',
            }}
          >
            <div className="flex items-center gap-2">
              <ShieldCheck
                size={14}
                strokeWidth={1.6}
                className="text-cyan"
                style={{ filter: 'drop-shadow(0 0 6px rgba(0,217,255,0.8))' }}
              />
              <span className="text-[10px] font-bold tracking-[0.16em] text-cyan">DEMO MODE</span>
              <span className="status-dot status-dot-live ml-auto" />
            </div>
            {!collapsed && (
              <p className="mt-1.5 text-[9.5px] leading-snug text-muted">
                Viewing simulated data for demonstration
              </p>
            )}

            {!collapsed && (
              <div className="mt-3 border-t border-cyan/10 pt-2.5">
                <div className="label-micro text-[8.5px]">SYSTEM TIME</div>
                <div className="tabular mt-1 text-[13px] font-semibold text-ink">
                  {now
                    ? now.toLocaleTimeString('en-GB', { hour12: false })
                    : '--:--:--'}
                </div>
                <div className="text-[9.5px] text-muted">
                  {now ? isoDay(now.toISOString()) : '---------'}
                </div>
              </div>
            )}
          </div>
        </div>
      </aside>

      {/* Collapse toggle */}
      <button
        type="button"
        onClick={onToggle}
        aria-label={collapsed ? 'Expand navigation' : 'Collapse navigation'}
        className="fixed top-[18px] z-50 hidden h-8 w-8 items-center justify-center rounded-lg border text-cyan transition-all hover:shadow-neon-cyan lg:flex"
        style={{
          left: collapsed ? 14 : 'calc(var(--sidebar-w) - 14px)',
          transform: 'translateX(-50%)',
          borderColor: 'rgba(0,217,255,0.35)',
          background: 'rgba(3,8,18,0.94)',
        }}
      >
        {collapsed ? <ChevronRight size={15} /> : <ChevronLeft size={15} />}
      </button>

      {/* Mobile drawer */}
      <MobileNav pathname={pathname} isActive={isActive} />
    </>
  );
}

function MobileNav({
  pathname,
  isActive,
}: {
  pathname: string;
  isActive: (href: string) => boolean;
}) {
  return (
    <div className="lg:hidden">
      <details className="group">
        <summary className="fixed left-4 top-4 z-50 flex h-10 w-10 cursor-pointer list-none items-center justify-center rounded-lg border border-cyan/30 bg-[#030812]/95 text-cyan">
          <ShieldCheck size={18} strokeWidth={1.6} />
        </summary>
        <div
          className="fixed inset-x-3 top-16 z-50 max-h-[70vh] overflow-y-auto rounded-xl border p-3"
          style={{
            borderColor: 'rgba(0,217,255,0.25)',
            background: 'rgba(3,8,18,0.98)',
          }}
        >
          <Link
            href="/"
            aria-label="SENTRA AI - go to Overview"
            className="mb-2 block px-1"
          >
            <div className="font-display text-[15px] font-bold tracking-[0.16em] text-ink">
              SENTRA AI
            </div>
            <div className="text-[8.5px] font-semibold tracking-[0.24em] text-cyan/80">
              SYSTEM INTELLIGENCE
            </div>
          </Link>
          {NAV.map((item) => {
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`nav-item ${isActive(item.href) ? 'nav-item-active' : ''}`}
              >
                <Icon size={15} strokeWidth={1.6} className="text-muted" />
                <span>{item.label}</span>
              </Link>
            );
          })}
        </div>
      </details>
    </div>
  );
}
