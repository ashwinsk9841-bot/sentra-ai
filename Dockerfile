# =============================================================================
# SENTRA AI - single-container production image
#
#   ONE container  ->  ONE public port  ->  ONE URL
#
#   browser -> https://sentra-ai.onrender.com/
#              |- /            -> Next.js 14        (React UI, all pages)
#              `- /api/*       -> FastAPI backend   (via the existing
#                                  frontend/src/app/api/[...path] route
#                                  handler, server-side)
#                                 -> Supabase
#
# WHY THERE IS NO NGINX / SEPARATE PROXY
# ---------------------------------------
# The repository already ships a same-origin proxy: the Next.js catch-all route
# handler `frontend/src/app/api/[...path]/route.ts` forwards /api/* to the
# backend and serves everything else itself. Reusing it means:
#
#   * exactly one process can own the public port, so there is no port race
#   * no extra proxy layer to misconfigure between two services
#   * SENTRA_API_URL stays server-side, so no backend hostname or secret is
#     ever sent to the browser
#   * the existing behaviour (including its explicit misconfiguration error)
#     is preserved exactly
#
# The backend therefore binds an INTERNAL port only. It is reachable from the
# Next.js server on the loopback interface inside this container and is never
# published.
#
# PORT CONTRACT
# -------------
#   $PORT                  Render assigns it (usually 10000). Next.js binds it.
#                          The public port is never hardcoded.
#   $SENTRA_API_PORT       internal FastAPI port, default 8000. Not published.
# =============================================================================

# -----------------------------------------------------------------------------
# Stage 1 - build the Next.js frontend
# -----------------------------------------------------------------------------
FROM node:22-bookworm-slim AS frontend-build

WORKDIR /build

# Dependencies first so the npm layer is cached independently of source edits.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

# Then the frontend sources and config.
COPY frontend/ ./

# No NEXT_PUBLIC_* values are needed: the browser is same-origin and talks only
# to /api/*. Secrets are read server-side at runtime, never baked into the
# client bundle. `next build` runs with production settings.
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build


# -----------------------------------------------------------------------------
# Stage 2 - install Python backend dependencies
# -----------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS backend-deps

# build-essential is required to compile wheels for packages that ship no
# prebuilt wheel for this interpreter/platform (chromadb, psutil and friends).
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./

# The pinned set is preserved exactly as committed: FastAPI, pandas/numpy,
# scikit-learn/scipy, Supabase, ChromaDB (RAG), psutil and pypdf. Nothing is
# removed and nothing new is added, because the code already imports all of it.
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt


# -----------------------------------------------------------------------------
# Final image - Node runtime + Python runtime, one entrypoint
# -----------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

LABEL org.opencontainers.image.title="SENTRA AI" \
      org.opencontainers.image.description="SENTRA AI - Next.js frontend and FastAPI backend in one container"

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    NEXT_TELEMETRY_DISABLED=1 \
    NODE_ENV=production

# Runtime OS packages:
#   ca-certificates  TLS for Supabase / OpenAI calls
#   curl             container HEALTHCHECK
#   libgomp1         OpenMP runtime that scikit-learn/scipy link against;
#                    without it sklearn aborts on first use
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl libgomp1 gnupg \
 && mkdir -p /etc/apt/keyrings \
 && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
      | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
 && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" \
      > /etc/apt/sources.list.d/nodesource.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends nodejs \
 && apt-get purge -y gnupg && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --- Python backend (from stage 2) -------------------------------------------
COPY --from=backend-deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=backend-deps /usr/local/bin /usr/local/bin

# --- Backend source ----------------------------------------------------------
# These are the only Python packages the ASGI app imports. The legacy Streamlit
# tree (app.py, pages/, ui/, app_pages/) is intentionally not shipped: the
# Docker image serves the Next.js UI, and keeping it out of the image avoids
# two competing frontends.
COPY sentinel/ ./sentinel/
COPY agent/    ./agent/
COPY ai/       ./ai/
COPY ml/       ./ml/
COPY rag/      ./rag/
COPY database/ ./database/

# --- Next.js runtime (built in stage 1) --------------------------------------
# node_modules and .next come from the builder, so the final image contains no
# TypeScript toolchain output and no dev-only install step.
COPY --from=frontend-build /build/node_modules      /app/frontend/node_modules
COPY --from=frontend-build /build/.next             /app/frontend/.next
# next-env.d.ts is deliberately absent: it is generated by `next build` in
# stage 1, is not committed to the repository, and `next start` does not need it.
# Copying it would fail the build on a fresh clone.
COPY frontend/package.json frontend/package-lock.json \
     frontend/next.config.mjs frontend/postcss.config.mjs \
     frontend/tailwind.config.ts frontend/tsconfig.json \
                                                  /app/frontend/

# --- Process supervisor ------------------------------------------------------
COPY scripts/docker_start.py /app/scripts/docker_start.py

# Writable locations: the local SQLite/Chroma fallback store and the telemetry
# data directory. SENTINEL_DATA_DIR points here by default.
RUN mkdir -p /app/data /app/frontend/.next \
 && chmod +x /app/scripts/docker_start.py

# `next start` serves as PID 1's child; the supervisor in docker_start.py owns
# both processes and forwards termination to them, so the platform's SIGTERM
# stops the whole container cleanly.
STOPSIGNAL SIGTERM

# No port is hardcoded and no EXPOSE is declared: Render assigns $PORT and
# docker_start.py binds exactly that. Only Next.js is published; the FastAPI
# port is internal to this container and never reachable from outside.

# Confirms the public port is serving. /api/health is a real end-to-end check:
# it is served by Next.js and forwarded to FastAPI by the existing proxy.
HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${PORT:-3000}/api/health" || exit 1

CMD ["python", "scripts/docker_start.py"]
