'use client';

import { useEffect, useRef } from 'react';

/**
 * A soft cyan/blue glow that follows the cursor.
 *
 * The position is interpolated with a spring-ish lerp inside a rAF loop so the
 * light trails the pointer slightly instead of snapping to it, and the whole
 * layer is `pointer-events-none` so it never blocks interaction.
 */
export function CursorGlow() {
  const glowRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduceMotion) return;

    const target = { x: window.innerWidth / 2, y: window.innerHeight / 2 };
    const current = { ...target };
    let raf = 0;
    let visible = false;

    const onMove = (event: PointerEvent) => {
      target.x = event.clientX;
      target.y = event.clientY;
      if (!visible) {
        visible = true;
        current.x = target.x;
        current.y = target.y;
        if (glowRef.current) glowRef.current.style.opacity = '1';
      }
    };

    const onLeave = () => {
      visible = false;
      if (glowRef.current) glowRef.current.style.opacity = '0';
    };

    const tick = () => {
      current.x += (target.x - current.x) * 0.12;
      current.y += (target.y - current.y) * 0.12;
      if (glowRef.current) {
        glowRef.current.style.transform = `translate3d(${current.x - 190}px, ${current.y - 190}px, 0)`;
      }
      raf = window.requestAnimationFrame(tick);
    };

    window.addEventListener('pointermove', onMove, { passive: true });
    window.addEventListener('pointerleave', onLeave);
    raf = window.requestAnimationFrame(tick);

    return () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerleave', onLeave);
      window.cancelAnimationFrame(raf);
    };
  }, []);

  return (
    <div
      aria-hidden
      className="pointer-events-none fixed inset-0 z-[1] hidden overflow-hidden md:block"
    >
      <div
        ref={glowRef}
        className="absolute left-0 top-0 h-[380px] w-[380px] rounded-full opacity-0 transition-opacity duration-500"
        style={{
          background:
            'radial-gradient(circle, rgba(0,217,255,0.10) 0%, rgba(0,120,255,0.05) 38%, rgba(0,80,255,0.02) 58%, transparent 72%)',
          filter: 'blur(6px)',
        }}
      />
    </div>
  );
}
