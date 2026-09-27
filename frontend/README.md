# SENTRA AI — System Intelligence

The production frontend for SENTRA AI. This is a custom **Next.js + React + TypeScript +
Tailwind CSS** application that reads real data from the existing Sentra Python backend.

The legacy Streamlit UI is still present at the repository root and is unchanged. This app is
the production UI.

---

## Stack

| Concern      | Choice                                       |
| ------------ | -------------------------------------------- |
| Framework    | Next.js 14 (App Router)                      |
| Language     | TypeScript (strict)                          |
| Styling      | Tailwind CSS 3 + a token-based design system  |
| Icons        | `lucide-react` (outline icons, no emojis)    |
| Charts       | `recharts`                                   |
| Animation    | Framer Motion + CSS keyframes                 |
| Deployment   | Vercel compatible                             |

---

## Quick start

```bash
cd frontend
npm install
cp .env.example .env.local     # then point SENTRA_API_URL at your API
npm run dev                    # http://localhost:3000
```

Production:

```bash
npm run build
npm run start
```

---

## Connecting to the backend

The browser **never** talks to Python directly. Next.js route handlers under
`src/app/api/[...path]/route.ts` proxy same-origin `/api/*` requests to the Sentra API
bridge, whose address comes from the server-only `SENTRA_API_URL` variable.

Start the bridge from the repository root:

```bash
python -m sentinel.api.serve --port 8787
```

The bridge is **additive**: every endpoint calls the same
`MonitoringService` / `AgentService` / `AnalyticsService` / `NotificationService` /
`DemoService` instances the Streamlit UI uses. No ML, RAG or AI logic was ported into
React, and no existing backend behaviour was changed.

### Endpoints

| Method | Path                    | Purpose                                  |
| ------ | ----------------------- | ---------------------------------------- |
| GET    | `/api/dashboard`        | Everything the Overview screen needs     |
| GET    | `/api/health`           | Subsystem checks and record counts       |
| GET    | `/api/overview`         | Raw service overview                     |
| GET    | `/api/series`           | Telemetry series for charts               |
| GET    | `/api/network`          | Interface counters and throughput         |
| GET    | `/api/risk`             | Composite risk score and drivers          |
| GET    | `/api/anomalies`        | Anomaly detections                       |
| GET    | `/api/alerts`           | Alert notifications                       |
| GET    | `/api/logs`             | Tailed log lines                         |
| GET    | `/api/processes`        | Process snapshots                        |
| GET    | `/api/timeline`         | Security event timeline                  |
| GET    | `/api/fleet`            | Paired devices                           |
| GET    | `/api/agent`            | Agent status and data boundary           |
| GET    | `/api/analytics`        | Distributions, correlation, reliability  |
| GET    | `/api/rag`              | Vector store stats, usage, documents     |
| GET    | `/api/documents`        | Knowledge base documents                 |
| POST   | `/api/investigate`      | Run the real investigator                |
| POST   | `/api/investigate-anomaly` | Investigate a specific anomaly         |
| POST   | `/api/rag-answer`       | RAG answer                               |
| POST   | `/api/rag-retrieve`     | RAG retrieval                            |
| POST   | `/api/ack-anomaly`      | Acknowledge an anomaly                   |
| POST   | `/api/alert-status`     | Change an alert status                   |
| POST   | `/api/device-status`    | Authorize or revoke a device             |
| POST   | `/api/run-cycle`        | Run a detection cycle                    |
| POST   | `/api/train-model`      | Train the ensemble                       |
| POST   | `/api/demo/seed`        | Seed the demo dataset                    |
| POST   | `/api/demo/clear`       | Clear the demo dataset                   |
| POST   | `/api/pairing-code`     | Create a pairing code                    |

---

## Design system

Tokens live in exactly two places and are not duplicated in components:

- `tailwind.config.ts` — colours, fonts, radii, glows, keyframes
- `src/app/globals.css` — CSS variables and the `.glass-panel`, `.nav-item`, `.badge-*`,
  `.btn-neon` primitives

| Token         | Value                    |
| ------------- | ------------------------ |
| Background    | `#02050A`                |
| Panel         | `#06111D`                |
| Panel surface | `rgba(5,12,22,0.78)`     |
| Border        | `rgba(0,217,255,0.18)`   |
| Hover border  | `rgba(0,217,255,0.60)`   |
| Cyan          | `#00D9FF`                |
| Blue          | `#1677FF`                |
| Purple        | `#9B6CFF`                |
| Green         | `#00E5A0`                |
| Warning       | `#FFB020`                |
| Danger        | `#FF4D5E`                |
| Text          | `#F2F7FF` / `#8FA7C2`    |

### Components

`SentraSidebar`, `SentraHeader`, `AppShell`, `HeroSection`, `DigitalGlobe`,
`DeviceStatusCard`, `MetricRow`, `MetricCard`, `MiniChart`, `LiveMonitoring`,
`SystemRisk`, `RiskGauge`, `RiskDriverRow`, `RecentAnomalies`, `SecurityTimeline`,
`AIInvestigation`, `Panel`, `BackgroundEffects`, `CursorGlow`.

---

## Data honesty

Every number rendered comes from the backend. Badge wording is derived from Sentra's own
documented thresholds (`CRITICAL >= 85`, `HIGH >= 70`, `MEDIUM >= 45`, else `LOW`) in
`src/lib/format.ts`. Where the backend has no reading, the UI shows `--` rather than a
placeholder value.

## Accessibility & motion

`prefers-reduced-motion` disables the particle canvas, the cursor glow, gauge transitions
and every animation.
