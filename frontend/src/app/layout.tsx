import type { Metadata, Viewport } from 'next';
import { Inter, Space_Grotesk } from 'next/font/google';
import './globals.css';
import { AppShell } from '@/components/AppShell';

const inter = Inter({
  subsets: ['latin'],
  variable: '--font-sans',
  display: 'swap',
});

const display = Space_Grotesk({
  subsets: ['latin'],
  variable: '--font-display',
  display: 'swap',
});

export const metadata: Metadata = {
  title: 'SENTRA AI — System Intelligence',
  description:
    'Real-Time AI System Intelligence. Monitor system behavior, detect anomalies and investigate risks with AI.',
  applicationName: 'SENTRA AI',
  authors: [{ name: 'SENTRA AI' }],
  keywords: ['SENTRA AI', 'System Intelligence', 'Anomaly Detection', 'AI Investigation'],
};

export const viewport: Viewport = {
  themeColor: '#02050A',
  width: 'device-width',
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${display.variable}`}>
      <body className="bg-void text-ink antialiased">
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
