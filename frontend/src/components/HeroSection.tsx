'use client';

import { DeviceStatusCard } from './DeviceStatusCard';
import { DigitalGlobe } from './DigitalGlobe';
import type { DashboardPayload } from '@/lib/types';

interface Props {
  data: DashboardPayload | null;
}

/** The SENTRA AI hero: brand headline plus the live device panel and globe. */
export function HeroSection({ data }: Props) {
  return (
    <section
      className="glass-panel relative mb-4 overflow-hidden"
      style={{ minHeight: 168 }}
    >
      {/* Globe sits behind the right side of the hero */}
      <div className="pointer-events-none absolute -right-10 top-1/2 hidden -translate-y-1/2 opacity-90 lg:block">
        <DigitalGlobe size={300} />
      </div>
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            'linear-gradient(100deg, rgba(6,17,29,0.96) 0%, rgba(6,17,29,0.86) 42%, rgba(6,17,29,0.28) 68%, transparent 100%)',
        }}
      />

      <div className="relative flex flex-wrap items-center gap-6 overflow-hidden px-5 py-5">
        <div className="min-w-0 flex-1 basis-[280px]">
          <h1
            className="font-display text-[40px] font-bold leading-none tracking-[0.06em] sm:text-[52px]"
            style={{
              color: '#7FE9FF',
              textShadow:
                '0 0 24px rgba(0,217,255,0.55), 0 0 60px rgba(22,119,255,0.35), 0 2px 0 rgba(0,0,0,0.4)',
            }}
          >
            SENTRA AI
          </h1>
          <div
            className="mt-2 font-display text-[15px] font-medium tracking-[0.14em] sm:text-[17px]"
            style={{ color: '#3FC8F5', textShadow: '0 0 16px rgba(0,217,255,0.4)' }}
          >
            Real-Time AI System Intelligence
          </div>
          <p className="mt-2.5 max-w-[520px] text-[12.5px] leading-relaxed text-muted">
            Monitor system behavior, detect anomalies and investigate risks with AI.
          </p>
        </div>

        <div className="relative z-10 w-full max-w-[320px]">
          <DeviceStatusCard
            device={data?.device ?? null}
            windowLabel={data?.window_label}
            uptimeSeconds={data?.uptime_seconds ?? data?.monitored_seconds ?? null}
          />
        </div>
      </div>
    </section>
  );
}
