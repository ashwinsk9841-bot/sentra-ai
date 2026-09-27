# SENTRA AI

**System intelligence for infrastructure that has to stay up.**

SENTRA AI is one website. It ingests metrics, logs, process and network data
from authorised devices, detects anomalies with scikit-learn, scores risk from
real signals, and lets an analyst ask questions in plain language against a
RAG index of their own runbooks and documents.

You open one URL. Nothing else is required of the user.

---

## Architecture

The browser never talks to the backend directly, and never sees a backend
hostname, port, or secret. That is what makes this a single-URL product rather
than two half-products.

```
  browser
     |  https://<your-vercel-domain>
     v
  Next.js 14  (Vercel)
     |  - renders the 14 product routes
     |  - /api/* route handler  ->  SENTRA_API_URL (server-side)
     v
  FastAPI  (Render / Railway / Fly)
     |  MonitoringService, AnalyticsService, AgentService,
     |  NotificationService, RAG + investigator
     v
  Supabase  (Postgres)        telemetry, anomalies, alerts, risk, documents
     |
     local fallback: SQLite + Chroma under ./data
```

The proxy lives at `frontend/src/app/api/[...path]/route.ts`. It is the only
network egress from the frontend, and `SENTRA_API_URL` is read server-side so
it is never bundled into client JavaScript.

Because the browser is same-origin, **CORS is not required and is off by
default**. Set `SENTRA_CORS_ORIGINS` only if you want to call the API directly
from another origin.

---

## Run it locally, one command

```bash
pip install -r requirements.txt
cd frontend && npm install && cd ..
python scripts/dev.py
```

Open <http://localhost:3000>. That is the only URL you need.

`scripts/dev.py` starts the FastAPI backend on `127.0.0.1:8787` and the
frontend on `127.0.0.1:3000`, waits for the backend health check, and tears
both down (including child process trees) on Ctrl+C.

Override ports or skip a service with:

```bash
SENTRA_FRONTEND_PORT=3100 SENTRA_BACKEND_PORT=8888 python scripts/dev.py
SKIP_BACKEND=1 python scripts/dev.py     # frontend only
```

### Running the pieces separately

```bash
python -m uvicorn sentinel.api.server:app --port 8787   # backend
cd frontend && npm run dev                                # frontend
```

Interactive API docs are served at <http://localhost:8787/docs>.

---

## Configuration

Configuration is resolved once from the environment and never written back to
disk. Secrets are surfaced to the UI only as masked metadata.

| File | Purpose |
| --- | --- |
| `.env.example` | Backend variables. Copy to `.env`. |
| `frontend/.env.example` | Frontend variables. Copy to `frontend/.env.local`. |

Copying `.env.example` verbatim is safe: placeholder values such as
`https://your-project.supabase.co` are detected and treated as **unset**, so a
fresh clone starts cleanly on the local SQLite store with no configuration
errors. `tests/test_config.py` locks this behaviour in.

### Database

`SUPABASE_URL` + `SUPABASE_KEY` select the Supabase repository automatically.
Otherwise the local SQLite store under `./data` is used. Both implement the
same interface, so behaviour is identical.

`SUPABASE_SERVICE_KEY` (the `service_role` key) is required **in production**,
because the anon key cannot insert telemetry while row level security is on.
Keep it server-side only.

### AI features are optional

With no `LLM_API_KEY`, the investigator falls back to a deterministic analyser
and embeddings fall back to local vectors. Every feature keeps working; summaries
are simply not model-generated. Set `LLM_API_KEY` to enable model-backed answers.

---

## Deploy

### 1. Supabase

1. Create a project.
2. Run `sentinel/database/schema.sql` in the SQL editor. It creates 16 tables,
   indexes, triggers, row level security policies and a `device_posture` view.
3. Copy the project URL, anon key and service-role key.

`sentinel/database/schema.sql` is validated against the Python repository by
`tests/test_schema_contract.py`, which checks every table, every written column,
every `jsonb` column, boolean types, foreign-key targets, and that RLS is
enabled on all telemetry tables.

### 2. Deploy to Render (one service, one URL)

The repository builds into a **single container** that runs both processes:

```
browser -> https://sentra-ai.onrender.com/     ONE public port
            |- /          -> Next.js 14      (the UI)
            `- /api/*     -> FastAPI         (internal port 8000, loopback)
                             -> Supabase
```

`render.yaml` is a ready blueprint for it:

```bash
render blueprint launch
```

Choose **Web Service**, and:

| Setting | Value |
| --- | --- |
| Environment | Docker |
| Dockerfile path | `./Dockerfile` |
| Docker context | `.` |
| Build command | *leave empty* - the Dockerfile builds |
| Start command | *leave empty* - the image `CMD` starts it |
| Health check path | `/api/health` |
| Instance count | 1 |

Render builds the image and publishes only the port named by `$PORT`. FastAPI
binds an internal port that is never exposed, and the browser stays same-origin,
so no backend hostname, port or secret reaches the client.

Scaling: run a single instance, because the service graph is process-local
(scikit-learn models and the Chroma client). Scale with instances, not workers.

Build and run the same image locally:

```bash
docker build -t sentra-ai .
docker run --rm -p 10000:10000 --env-file .env -e PORT=10000 sentra-ai
# open http://localhost:10000
```

Deploying the two processes to separate hosts also still works: run
`uvicorn sentinel.api.server:app --host 0.0.0.0 --port $PORT` for the backend and
set the frontend's `SENTRA_API_URL` to that origin. See section 3.

### 3. Split frontend and backend (optional)

If you prefer two services, deploy the backend on Render/Railway/Fly:

```bash
uvicorn sentinel.api.server:app --host 0.0.0.0 --port $PORT
```

and the frontend on Vercel. `vercel.json` builds `frontend/` for you, so no
project settings need changing. Then set one variable:

| Variable | Value |
| --- | --- |
| `SENTRA_API_URL` | the backend origin, e.g. `https://sentra-api.onrender.com` |

`SENTRA_API_URL` is **required** in production and is read **server-side only** -
it is never `NEXT_PUBLIC_`, so it is never inlined into the browser bundle. The
proxy returns a clear 500 naming the variable rather than silently falling back
to localhost, so a misconfigured deploy fails visibly instead of appearing
healthy.

Health probe: `GET /health` returns `{"ok":true,"status":"healthy","store":...}`.

### 4. Connect a device

Devices are authorised explicitly through a pairing code; there is no stealth
enrolment path. Generate a code in the dashboard, then on the monitored host:

```bash
export AGENT_INGEST_URL=https://sentra-api.onrender.com
export AGENT_INGEST_KEY=<key>
python -m sentinel.agent --register --pairing-code <CODE> --name "web-01"
python -m sentinel.agent --log-file app=/var/log/app.log
```

The agent collects system metrics, process snapshots and the log files you
explicitly name. It deliberately does **not** capture full command lines, which
routinely contain tokens and passwords.

Set `DEMO_MODE=false` once real devices are reporting.

---

## Tests

```bash
python -m pytest
```

88 tests covering configuration resolution, the published API contract, and the
SQL schema contract. They run in a few seconds and need no network or database.

---

## API

All responses share one envelope:

```json
{ "ok": true, "data": { } }
```

### Product surface

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Service and store status |
| GET | `/api/devices` | Authorised devices |
| GET | `/api/metrics` | Metric series |
| GET | `/api/monitoring` | Dashboard bundle |
| GET | `/api/anomalies` | Detected anomalies |
| GET | `/api/alerts` | Alert feed |
| GET | `/api/processes` | Process snapshots |
| GET | `/api/network` | Interface counters |
| GET | `/api/logs` | Log entries |
| GET | `/api/risk` | Risk score and drivers |
| GET | `/api/investigation` | Investigation history |
| POST | `/api/investigation` | Run an investigation |
| GET | `/api/rag` | RAG statistics and documents |
| POST | `/api/rag/query` | Answer from the corpus |
| GET | `/api/agents` | Agent fleet and health |
| GET | `/api/security` | Security posture |
| GET | `/api/analytics` | Reliability and correlation |

### Compatibility aliases

The original bridge paths are preserved, so existing clients keep working:
`/api/dashboard`, `/api/series`, `/api/timeseries`, `/api/overview`,
`/api/timeline`, `/api/agent`, `/api/fleet`, `/api/documents`,
`/api/rag-answer`, `/api/rag-retrieve`, `/api/investigate`,
`/api/investigations`, `/api/investigate-anomaly`, `/api/ack-anomaly`,
`/api/anomalies/acknowledge`, `/api/alert-status`, `/api/alerts/status`,
`/api/device-status`, `/api/devices/status`, `/api/pairing-code`,
`/api/run-cycle`, `/api/train-model`, `/api/demo/seed`, `/api/demo/clear`.

`/api/metrics` and `/api/series` are the same handler, so metric polling keeps
working whichever name a client uses.

---

## Privacy

- Process snapshots exclude command lines.
- No packet capture; network metrics are interface counters only.
- The agent reads only log files you name explicitly.
- RLS is enabled on every telemetry table; the service-role key never reaches
  the browser.

---

## Layout

```
sentinel/
  api/         FastAPI app (server.py) and the original bridge (serve.py)
  services/    monitoring, analytics, agent, notifications, demo
  database/    repository interface, Supabase, local SQLite, schema.sql
  ml/          anomaly detection and risk scoring
  rag/         chunking, embeddings, retrieval
  agent/       collector and sender for authorised hosts
frontend/      Next.js 14 app, 14 routes
scripts/dev.py one-command local stack
tests/         config, API contract, schema contract
```

`app.py`, `app_pages/`, `ai/`, `ml/`, `pages/`, `rag/` and `ui/` are the
original Streamlit implementation. It is preserved and still runnable, but it
is not the production interface.
