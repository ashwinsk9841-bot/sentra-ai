'use client';

import { useState } from 'react';
import { BackgroundEffects } from './BackgroundEffects';
import { CursorGlow } from './CursorGlow';
import { SentraSidebar } from './SentraSidebar';
import { SentraHeader } from './SentraHeader';

/**
 * The persistent SENTRA frame: fixed sidebar, fixed header, and a main column
 * that scrolls on its own so the chrome never moves.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <div className="relative min-h-screen">
      <BackgroundEffects />
      <CursorGlow />

      <SentraSidebar collapsed={collapsed} onToggle={() => setCollapsed((v) => !v)} />

      <div
        className="relative z-10 flex min-h-screen flex-col transition-[padding] duration-300"
        style={{ paddingLeft: collapsed ? 0 : 'var(--content-inset)' }}
      >
        <SentraHeader collapsed={collapsed} />
        <main className="flex-1 px-5 pb-8 pt-4 sm:px-6 lg:px-7">{children}</main>
      </div>
    </div>
  );
}
