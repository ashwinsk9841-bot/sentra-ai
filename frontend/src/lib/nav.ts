import type { LucideIcon } from 'lucide-react';
import {
  Activity,
  BarChart3,
  Bell,
  FileText,
  FolderSearch,
  LayoutDashboard,
  Network,
  ScrollText,
  Server,
  Settings,
  ShieldCheck,
  Sparkles,
  SquareTerminal,
  TriangleAlert,
} from 'lucide-react';

export interface NavEntry {
  href: string;
  label: string;
  icon: LucideIcon;
  group: 'monitor' | 'analyse' | 'manage';
}

/** The SENTRA AI navigation, in the exact order of the design specification. */
export const NAV: NavEntry[] = [
  { href: '/', label: 'Overview', icon: LayoutDashboard, group: 'monitor' },
  { href: '/monitoring', label: 'Live Monitoring', icon: Activity, group: 'monitor' },
  { href: '/processes', label: 'Processes', icon: SquareTerminal, group: 'monitor' },
  { href: '/network', label: 'Network', icon: Network, group: 'monitor' },
  { href: '/logs', label: 'Logs', icon: ScrollText, group: 'monitor' },
  { href: '/anomalies', label: 'Anomalies', icon: TriangleAlert, group: 'analyse' },
  { href: '/alerts', label: 'Alerts', icon: Bell, group: 'analyse' },
  { href: '/investigation', label: 'AI Investigation', icon: Sparkles, group: 'analyse' },
  { href: '/devices', label: 'Devices', icon: Server, group: 'analyse' },
  { href: '/documents', label: 'Documents', icon: FileText, group: 'analyse' },
  { href: '/rag', label: 'RAG Lab', icon: FolderSearch, group: 'analyse' },
  { href: '/analytics', label: 'Analytics', icon: BarChart3, group: 'analyse' },
  { href: '/security', label: 'Security Health', icon: ShieldCheck, group: 'manage' },
  { href: '/settings', label: 'Settings', icon: Settings, group: 'manage' },
];

export const NAV_GROUPS: { id: NavEntry['group']; label: string }[] = [
  { id: 'monitor', label: 'Monitor' },
  { id: 'analyse', label: 'Analyse' },
  { id: 'manage', label: 'Manage' },
];
