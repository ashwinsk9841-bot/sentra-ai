'use client';

import { useEffect, useMemo, useState } from 'react';

interface GlobeProps {
  size?: number;
  className?: string;
}

/**
 * A generated digital network globe: latitude/longitude arcs, orbiting nodes,
 * and data links. Pure SVG + CSS so there is no image dependency and no canvas
 * cost, and it stays crisp on any display.
 */
export function DigitalGlobe({ size = 300, className = '' }: GlobeProps) {
  const [t, setT] = useState(0);

  useEffect(() => {
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduce) return;
    let raf = 0;
    const start = performance.now();
    const tick = (now: number) => {
      setT((now - start) / 1000);
      raf = window.requestAnimationFrame(tick);
    };
    raf = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(raf);
  }, []);

  const cx = 150;
  const cy = 150;
  const r = 118;

  // Deterministic node placement (no hydration mismatch).
  const nodes = useMemo(
    () =>
      Array.from({ length: 26 }, (_, i) => {
        const golden = Math.PI * (3 - Math.sqrt(5));
        const y = 1 - (i / 25) * 2;
        const rad = Math.sqrt(1 - y * y);
        const theta = golden * i;
        return {
          x: cx + Math.cos(theta) * rad * r * 0.94,
          y: cy + y * r * 0.94,
          size: 0.9 + ((i * 37) % 11) / 9,
          phase: (i * 0.7) % 6.28,
        };
      }),
    [],
  );

  const links = useMemo(
    () =>
      Array.from({ length: 16 }, (_, i) => {
        const a = nodes[i % nodes.length];
        const b = nodes[(i * 5 + 3) % nodes.length];
        return { a, b, key: `l${i}` };
      }),
    [nodes],
  );

  const latitudes = [-60, -30, 0, 30, 60];
  const longitudes = [-60, -30, 0, 30, 60];

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 300 300"
      className={className}
      aria-hidden
      style={{ overflow: 'visible' }}
    >
      <defs>
        <radialGradient id="globe-core" cx="50%" cy="45%" r="60%">
          <stop offset="0%" stopColor="#0b2740" stopOpacity="0.95" />
          <stop offset="60%" stopColor="#061826" stopOpacity="0.7" />
          <stop offset="100%" stopColor="#02050A" stopOpacity="0.2" />
        </radialGradient>
        <linearGradient id="globe-sweep" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="#00D9FF" stopOpacity="0" />
          <stop offset="50%" stopColor="#00D9FF" stopOpacity="0.85" />
          <stop offset="100%" stopColor="#00D9FF" stopOpacity="0" />
        </linearGradient>
        <filter id="globe-glow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="3.2" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      {/* Sphere body */}
      <circle cx={cx} cy={cy} r={r} fill="url(#globe-core)" />
      <circle
        cx={cx}
        cy={cy}
        r={r}
        fill="none"
        stroke="rgba(0,217,255,0.42)"
        strokeWidth="1"
        filter="url(#globe-glow)"
      />
      <circle cx={cx} cy={cy} r={r * 0.995} fill="none" stroke="rgba(22,119,255,0.2)" strokeWidth="4" />

      {/* Latitude rings */}
      {latitudes.map((lat) => {
        const y = cy + (lat / 90) * r;
        const rx = Math.sqrt(Math.max(0, r * r - (lat / 90) * (r * r))) * 0.97;
        return (
          <ellipse
            key={`lat${lat}`}
            cx={cx}
            cy={y}
            rx={rx}
            ry={rx * 0.22}
            fill="none"
            stroke="rgba(0,217,255,0.18)"
            strokeWidth="0.7"
          />
        );
      })}

      {/* Longitude rings */}
      {longitudes.map((lon) => {
        const rx = Math.abs((lon / 90)) * r;
        return (
          <ellipse
            key={`lon${lon}`}
            cx={cx}
            cy={cy}
            rx={Math.max(2, rx)}
            ry={r * 0.97}
            fill="none"
            stroke="rgba(0,217,255,0.16)"
            strokeWidth="0.7"
          />
        );
      })}
      <ellipse
        cx={cx}
        cy={cy}
        rx={r}
        ry={r * 0.28}
        fill="none"
        stroke="rgba(155,108,255,0.22)"
        strokeWidth="0.8"
      />

      {/* Data links */}
      {links.map((link) => (
        <line
          key={link.key}
          x1={link.a.x}
          y1={link.a.y}
          x2={link.b.x}
          y2={link.b.y}
          stroke="rgba(0,217,255,0.32)"
          strokeWidth="0.6"
        />
      ))}

      {/* Orbiting ring 1 */}
      <g style={{ transformOrigin: `${cx}px ${cy}px`, animation: 'spinSlow 26s linear infinite' }}>
        <circle
          cx={cx}
          cy={cy}
          r={r + 12}
          fill="none"
          stroke="rgba(0,217,255,0.18)"
          strokeWidth="0.8"
          strokeDasharray="3 9"
        />
        <circle cx={cx} cy={cy - r - 12} r="2.6" fill="#00D9FF" filter="url(#globe-glow)" />
      </g>

      {/* Orbiting ring 2 (counter-rotating) */}
      <g
        style={{ transformOrigin: `${cx}px ${cy}px`, animation: 'spinReverse 34s linear infinite' }}
      >
        <circle
          cx={cx}
          cy={cy}
          r={r + 24}
          fill="none"
          stroke="rgba(22,119,255,0.16)"
          strokeWidth="0.7"
          strokeDasharray="2 12"
        />
        <circle cx={cx + r + 24} cy={cy} r="2" fill="#1677FF" filter="url(#globe-glow)" />
      </g>

      {/* Surface nodes with a travelling pulse */}
      {nodes.map((node, i) => {
        const pulse = 0.45 + 0.55 * Math.abs(Math.sin(t * 0.9 + node.phase));
        return (
          <circle
            key={`n${i}`}
            cx={node.x}
            cy={node.y}
            r={node.size}
            fill="#00D9FF"
            opacity={pulse}
            filter="url(#globe-glow)"
          />
        );
      })}

      {/* Rotating scan sweep */}
      <g style={{ transformOrigin: `${cx}px ${cy}px`, animation: 'spinSlow 12s linear infinite' }}>
        <path d={`M ${cx} ${cy} L ${cx - r * 0.5} ${cy - r * 0.86} A ${r} ${r} 0 0 1 ${cx + r * 0.5} ${cy - r * 0.86} Z`} fill="url(#globe-sweep)" opacity="0.16" />
      </g>
    </svg>
  );
}
