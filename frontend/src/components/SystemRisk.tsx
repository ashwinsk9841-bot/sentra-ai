'use client';

import { Panel } from './Panel';
import type { RiskPayload } from '@/lib/types';
import { ACCENT_HEX, fmt, num, riskBand } from '@/lib/format';

interface GaugeProps {
  score: number | null;
  severity: string | null;
  size?: number;
}

/**
 * The multi-ring neon risk gauge: an outer cyan track, a blue progress arc and
 * a warning segment, all drawn with SVG so the glow can be tuned precisely.
 */
export function RiskGauge({ score, severity, size = 196 }: GaugeProps) {
  const value = Math.max(0, Math.min(100, num(score) ?? 0));
  const band = riskBand(value);
  const stroke = ACCENT_HEX[band.accent];

  const cx = size / 2;
  const cy = size / 2;
  const rOuter = size / 2 - 12;
  const rInner = rOuter - 15;
  const circumference = 2 * Math.PI * rInner;

  // The gauge fills from the top, clockwise.
  const dash = (value / 100) * circumference;

  return (
    <div data-audit="gauge" className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90" aria-hidden>
        <defs>
          <linearGradient id="gauge-arc" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#00D9FF" />
            <stop offset="55%" stopColor="#1677FF" />
            <stop offset="100%" stopColor={stroke} />
          </linearGradient>
          <filter id="gauge-glow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="4" result="b" />
            <feMerge>
              <feMergeNode in="b" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* Outer decorative ring */}
        <circle
          cx={cx}
          cy={cy}
          r={rOuter}
          fill="none"
          stroke="rgba(0,217,255,0.16)"
          strokeWidth="1"
          strokeDasharray="1 7"
        />
        {/* Blue inner ring */}
        <circle
          cx={cx}
          cy={cy}
          r={rOuter - 5}
          fill="none"
          stroke="rgba(22,119,255,0.2)"
          strokeWidth="1.5"
        />
        {/* Track */}
        <circle
          cx={cx}
          cy={cy}
          r={rInner}
          fill="none"
          stroke="rgba(0,217,255,0.1)"
          strokeWidth="11"
        />
        {/* Warning threshold arc (>= 70) shown on the track */}
        <circle
          cx={cx}
          cy={cy}
          r={rInner}
          fill="none"
          stroke="rgba(255,176,32,0.16)"
          strokeWidth="11"
          strokeDasharray={`${(30 / 100) * circumference} ${circumference}`}
          strokeDashoffset={-(70 / 100) * circumference}
        />
        {/* Value arc */}
        <circle
          cx={cx}
          cy={cy}
          r={rInner}
          fill="none"
          stroke="url(#gauge-arc)"
          strokeWidth="11"
          strokeLinecap="round"
          strokeDasharray={`${dash} ${circumference}`}
          filter="url(#gauge-glow)"
          style={{ transition: 'stroke-dasharray 0.9s cubic-bezier(0.22, 1, 0.36, 1)' }}
        />
        {/* Tick marks */}
        {Array.from({ length: 36 }, (_, i) => {
          const angle = (i / 36) * Math.PI * 2;
          const inner = rInner - 8;
          const outer = rInner - 8 + (i % 3 === 0 ? 5 : 2.5);
          return (
            <line
              key={i}
              x1={cx + Math.cos(angle) * inner}
              y1={cy + Math.sin(angle) * inner}
              x2={cx + Math.cos(angle) * outer}
              y2={cy + Math.sin(angle) * outer}
              stroke={i % 9 === 0 ? 'rgba(0,217,255,0.5)' : 'rgba(0,217,255,0.18)'}
              strokeWidth={i % 9 === 0 ? 1.4 : 0.8}
            />
          );
        })}
      </svg>

      {/* Centre readout */}
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <div
          className="tabular font-display text-[46px] font-bold leading-none"
          style={{ color: stroke, textShadow: `0 0 26px ${stroke}88` }}
        >
          {value}
        </div>
        <div className="text-[10px] font-semibold tracking-[0.2em] text-muted">/100</div>
        <div className="mt-2 flex items-center gap-1.5">
          <span className={`badge ${band.badge}`}>
            {severity ? severity : band.label}
          </span>
        </div>
      </div>
    </div>
  );
}

interface DriverProps {
  driver: { key: string; label: string | null; value: number | null };
}

/** One risk driver row: label, glowing bar and value. */
export function RiskDriverRow({ driver }: DriverProps) {
  const value = Math.max(0, Math.min(100, num(driver.value) ?? 0));
  const band = riskBand(value);
  const stroke = ACCENT_HEX[band.accent];

  return (
    <div className="py-1.5">
      <div className="mb-1 flex items-baseline justify-between gap-2">
        <span className="truncate text-[10.5px] text-muted">{driver.label ?? driver.key}</span>
        <span
          className="tabular text-[11.5px] font-bold"
          style={{ color: stroke, textShadow: `0 0 12px ${stroke}66` }}
        >
          {fmt(value, 1)}
        </span>
      </div>
      <div
        className="h-[5px] w-full overflow-hidden rounded-full"
        style={{ background: 'rgba(143,167,194,0.12)' }}
      >
        <div
          className="h-full rounded-full"
          style={{
            width: `${value}%`,
            background: `linear-gradient(90deg, ${ACCENT_HEX.cyan}, ${stroke})`,
            boxShadow: `0 0 10px ${stroke}99`,
            transition: 'width 0.9s cubic-bezier(0.22, 1, 0.36, 1)',
          }}
        />
      </div>
    </div>
  );
}

interface Props {
  risk: RiskPayload | null;
}

/** SYSTEM RISK panel: the circular gauge plus the four composite drivers. */
export function SystemRisk({ risk }: Props) {
  const score = risk?.score ?? null;
  const drivers = risk?.drivers ?? [];

  return (
    <Panel title="System Risk" className="h-full">
      <div className="flex flex-col items-center gap-3 lg:flex-row lg:items-start lg:gap-4">
        <RiskGauge score={score} severity={risk?.severity ?? null} />

        <div className="w-full min-w-0 flex-1">
          <div className="label-micro mb-1.5">Risk Drivers</div>
          {drivers.length === 0 ? (
            <p className="text-[10.5px] text-muted/80">
              No composite risk drivers recorded yet.
            </p>
          ) : (
            drivers.map((driver) => (
              <RiskDriverRow key={driver.key} driver={driver} />
            ))
          )}

          {risk?.summary && (
            <p className="mt-2.5 line-clamp-4 border-t border-cyan/10 pt-2.5 text-[10.5px] leading-relaxed text-muted">
              {risk.summary}
            </p>
          )}
        </div>
      </div>
    </Panel>
  );
}
