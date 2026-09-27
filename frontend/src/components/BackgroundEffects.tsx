'use client';

import { useEffect, useRef } from 'react';

interface Node {
  x: number;
  y: number;
  vx: number;
  vy: number;
  r: number;
  hue: 'cyan' | 'blue' | 'violet';
}

const NODE_COUNT = 58;
const LINK_DISTANCE = 168;

/**
 * The animated SENTRA background: deep navy gradients, a faint digital grid,
 * drifting glowing nodes joined by network lines, and a few slow radial glows.
 * Rendered on a canvas so it stays cheap, and it never intercepts pointer
 * events so the UI above remains fully interactive.
 */
export function BackgroundEffects() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    let width = 0;
    let height = 0;
    let raf = 0;
    let nodes: Node[] = [];

    const dpr = Math.min(window.devicePixelRatio || 1, 2);

    const palette = {
      cyan: '0, 217, 255',
      blue: '22, 119, 255',
      violet: '155, 108, 255',
    } as const;

    const seed = () => {
      const count = Math.max(24, Math.min(NODE_COUNT, Math.round((width * height) / 26000)));
      nodes = Array.from({ length: count }, (_, i) => ({
        x: Math.random() * width,
        y: Math.random() * height,
        vx: (Math.random() - 0.5) * 0.22,
        vy: (Math.random() - 0.5) * 0.22,
        r: 0.7 + Math.random() * 1.5,
        hue: i % 9 === 0 ? 'violet' : i % 3 === 0 ? 'blue' : 'cyan',
      }));
    };

    const resize = () => {
      width = window.innerWidth;
      height = window.innerHeight;
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      seed();
    };

    const draw = () => {
      ctx.clearRect(0, 0, width, height);

      for (const node of nodes) {
        if (!reduceMotion) {
          node.x += node.vx;
          node.y += node.vy;
          if (node.x < -20) node.x = width + 20;
          if (node.x > width + 20) node.x = -20;
          if (node.y < -20) node.y = height + 20;
          if (node.y > height + 20) node.y = -20;
        }
      }

      // Network links between nearby nodes.
      for (let i = 0; i < nodes.length; i += 1) {
        for (let j = i + 1; j < nodes.length; j += 1) {
          const a = nodes[i];
          const b = nodes[j];
          const dx = a.x - b.x;
          const dy = a.y - b.y;
          const dist = Math.hypot(dx, dy);
          if (dist > LINK_DISTANCE) continue;
          const alpha = (1 - dist / LINK_DISTANCE) * 0.16;
          ctx.strokeStyle = `rgba(0, 217, 255, ${alpha.toFixed(3)})`;
          ctx.lineWidth = 0.6;
          ctx.beginPath();
          ctx.moveTo(a.x, a.y);
          ctx.lineTo(b.x, b.y);
          ctx.stroke();
        }
      }

      // Glowing nodes.
      for (const node of nodes) {
        const rgb = palette[node.hue];
        const glow = ctx.createRadialGradient(node.x, node.y, 0, node.x, node.y, node.r * 7);
        glow.addColorStop(0, `rgba(${rgb}, 0.55)`);
        glow.addColorStop(1, `rgba(${rgb}, 0)`);
        ctx.fillStyle = glow;
        ctx.beginPath();
        ctx.arc(node.x, node.y, node.r * 7, 0, Math.PI * 2);
        ctx.fill();

        ctx.fillStyle = `rgba(${rgb}, 0.85)`;
        ctx.beginPath();
        ctx.arc(node.x, node.y, node.r, 0, Math.PI * 2);
        ctx.fill();
      }

      raf = window.requestAnimationFrame(draw);
    };

    resize();
    window.addEventListener('resize', resize);
    if (reduceMotion) {
      draw();
      window.cancelAnimationFrame(raf);
    } else {
      raf = window.requestAnimationFrame(draw);
    }

    return () => {
      window.removeEventListener('resize', resize);
      window.cancelAnimationFrame(raf);
    };
  }, []);

  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 z-0 overflow-hidden">
      {/* Deep navy radial washes */}
      <div
        className="absolute inset-0"
        style={{
          background:
            'radial-gradient(1100px 620px at 78% -8%, rgba(22,119,255,0.16), transparent 62%),' +
            'radial-gradient(900px 520px at 8% 4%, rgba(0,217,255,0.10), transparent 58%),' +
            'radial-gradient(760px 620px at 62% 108%, rgba(155,108,255,0.09), transparent 60%),' +
            'linear-gradient(180deg, #030812 0%, #02050A 55%, #020509 100%)',
        }}
      />
      {/* Faint digital grid */}
      <div className="grid-overlay absolute inset-0 opacity-[0.55]" />
      {/* Canvas particle + network layer */}
      <canvas ref={canvasRef} className="absolute inset-0" />
      {/* Slow-moving light trails */}
      <div
        className="absolute -left-40 top-1/4 h-[520px] w-[520px] rounded-full opacity-40 blur-3xl"
        style={{
          background: 'radial-gradient(circle, rgba(0,217,255,0.16), transparent 70%)',
          animation: 'sentraDrift 26s ease-in-out infinite alternate',
        }}
      />
      <div
        className="absolute -right-32 bottom-0 h-[460px] w-[460px] rounded-full opacity-35 blur-3xl"
        style={{
          background: 'radial-gradient(circle, rgba(22,119,255,0.18), transparent 70%)',
          animation: 'sentraDrift 34s ease-in-out infinite alternate-reverse',
        }}
      />
      <style>{`@keyframes sentraDrift {
        0% { transform: translate3d(0, 0, 0) scale(1); }
        100% { transform: translate3d(60px, -40px, 0) scale(1.12); }
      }`}</style>
      {/* Vignette to keep panels readable */}
      <div
        className="absolute inset-0"
        style={{ background: 'radial-gradient(120% 90% at 50% 40%, transparent 55%, rgba(2,5,10,0.72) 100%)' }}
      />
    </div>
  );
}
