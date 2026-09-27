'use client';

import { useCallback, useEffect, useState } from 'react';
import { RefreshCw, WifiOff } from 'lucide-react';
import { HeroSection } from '@/components/HeroSection';
import { MetricRow } from '@/components/MetricRow';
import { LiveMonitoring } from '@/components/LiveMonitoring';
import { SystemRisk } from '@/components/SystemRisk';
import { RecentAnomalies, SecurityTimeline } from '@/components/RecentAnomalies';
import { AIInvestigation } from '@/components/AIInvestigation';
import { dashboard } from '@/lib/api';
import type { DashboardPayload } from '@/lib/types';

export default function OverviewPage() {
  const [data, setData] = useState<DashboardPayload | null>(null);
  const [timeWindow, setTimeWindow] = useState('1h');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(
    async (nextWindow: string, quiet = false) => {
      if (quiet) setRefreshing(true);
      try {
        const payload = await dashboard(nextWindow);
        setData(payload);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unable to reach the SENTRA backend');
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [],
  );

  useEffect(() => {
    void load(timeWindow);
  }, [load, timeWindow]);

  // Keep the overview live without hammering the backend.
  useEffect(() => {
    const id = window.setInterval(() => void load(timeWindow, true), 20000);
    return () => window.clearInterval(id);
  }, [load, timeWindow]);

  return (
    <div className="animate-rise-in">
      <HeroSection data={data} />

      {error && (
        <div
          className="mb-4 flex items-center gap-3 rounded-xl border px-4 py-3"
          style={{ borderColor: 'rgba(255,77,94,0.4)', background: 'rgba(255,77,94,0.08)' }}
        >
          <WifiOff size={16} className="shrink-0 text-danger" />
          <div className="min-w-0 flex-1">
            <div className="text-[12px] font-semibold text-danger">Backend unreachable</div>
            <p className="truncate text-[10.5px] text-muted">{error}</p>
          </div>
          <button type="button" className="btn-neon" onClick={() => void load(timeWindow)}>
            <RefreshCw size={12} /> Retry
          </button>
        </div>
      )}

      {loading ? (
        <LoadingGrid />
      ) : (
        <>
          <MetricRow data={data} />

          {/* Monitoring + risk */}
          <div className="mb-4 grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,1.9fr)_minmax(0,1fr)]">
            <LiveMonitoring
              data={data}
              window={timeWindow}
              onWindowChange={setTimeWindow}
            />
            <SystemRisk risk={data?.risk ?? null} />
          </div>

          {/* Anomalies + AI + timeline */}
          <div className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)_minmax(0,1fr)]">
            <RecentAnomalies
              anomalies={data?.anomalies ?? []}
              deviceName={data?.device?.name ?? null}
            />
            <AIInvestigation anomalies={data?.anomalies ?? []} device={data?.device ?? null} />
            <SecurityTimeline events={data?.timeline ?? []} />
          </div>
        </>
      )}

      {refreshing && (
        <div className="pointer-events-none fixed bottom-4 right-5 flex items-center gap-2 text-[10px] tracking-widest text-cyan/70">
          <RefreshCw size={11} className="animate-spin" /> SYNCING
        </div>
      )}
    </div>
  );
}

function LoadingGrid() {
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 7 }, (_, i) => (
          <div
            key={i}
            className="glass-panel h-[116px] animate-pulse"
            style={{ animationDuration: '1.6s' }}
          />
        ))}
      </div>
      <div className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,1.9fr)_minmax(0,1fr)]">
        <div className="glass-panel h-[330px] animate-pulse" />
        <div className="glass-panel h-[330px] animate-pulse" />
      </div>
    </div>
  );
}
