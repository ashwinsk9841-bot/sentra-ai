import type { Config } from 'tailwindcss';

/**
 * SENTRA AI design system.
 * Every colour, radius and glow used by the UI is declared here exactly once so
 * components never duplicate raw hex values or large CSS blocks.
 */
const config: Config = {
  content: [
    './src/app/**/*.{ts,tsx}',
    './src/components/**/*.{ts,tsx}',
    './src/lib/**/*.{ts,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        void: '#02050A',
        abyss: '#030812',
        panel: {
          DEFAULT: '#06111D',
          soft: '#081522',
        },
        cyan: {
          DEFAULT: '#00D9FF',
          soft: '#67E8F9',
        },
        electric: '#1677FF',
        violet: '#9B6CFF',
        matrix: '#00E5A0',
        amber: '#FFB020',
        danger: '#FF4D5E',
        ink: '#F2F7FF',
        muted: '#8FA7C2',
      },
      fontFamily: {
        display: ['var(--font-display)', 'Inter', 'system-ui', 'sans-serif'],
        sans: ['var(--font-sans)', 'Inter', 'system-ui', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      borderRadius: {
        panel: '14px',
      },
      boxShadow: {
        panel: '0 0 20px rgba(0,150,255,0.05)',
        'panel-hover':
          '0 0 28px rgba(0,217,255,0.16), 0 0 60px rgba(0,120,255,0.08)',
        'neon-cyan': '0 0 14px rgba(0,217,255,0.45)',
        'neon-green': '0 0 12px rgba(0,229,160,0.55)',
        'neon-amber': '0 0 12px rgba(255,176,32,0.5)',
        'neon-red': '0 0 12px rgba(255,77,94,0.5)',
        'neon-violet': '0 0 12px rgba(155,108,255,0.45)',
      },
      keyframes: {
        pulseDot: {
          '0%, 100%': { opacity: '1', transform: 'scale(1)' },
          '50%': { opacity: '0.35', transform: 'scale(0.82)' },
        },
        sweep: {
          '0%': { transform: 'translateX(-100%)' },
          '100%': { transform: 'translateX(200%)' },
        },
        riseIn: {
          '0%': { opacity: '0', transform: 'translateY(10px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        spinSlow: {
          '0%': { transform: 'rotate(0deg)' },
          '100%': { transform: 'rotate(360deg)' },
        },
        spinReverse: {
          '0%': { transform: 'rotate(360deg)' },
          '100%': { transform: 'rotate(0deg)' },
        },
      },
      animation: {
        'pulse-dot': 'pulseDot 2.4s ease-in-out infinite',
        sweep: 'sweep 7s linear infinite',
        'rise-in': 'riseIn 0.5s ease-out both',
        'spin-slow': 'spinSlow 26s linear infinite',
        'spin-reverse': 'spinReverse 34s linear infinite',
      },
    },
  },
  plugins: [],
};

export default config;
