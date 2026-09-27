-- =============================================================================
-- Sentinel AI - Supabase / PostgreSQL schema
-- =============================================================================
-- Apply in the Supabase SQL Editor (Dashboard -> SQL Editor -> New query), or:
--     psql "$SUPABASE_URL" -f database/schema.sql
--
-- The same logical schema is implemented in Python by
-- sentinel/database/local.py (SQLite) so the application behaves identically
-- whether or not Supabase is configured.
-- =============================================================================

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------------
-- 1. users
--    Mirrors Supabase Auth identities so analyst activity can be attributed
--    without duplicating credentials in the platform.
-- ---------------------------------------------------------------------------
create table if not exists public.users (
    id           uuid primary key default gen_random_uuid(),
    auth_user_id uuid unique,
    email        text not null unique,
    display_name text,
    role         text not null default 'analyst'
                 check (role in ('viewer', 'analyst', 'admin')),
    created_at   timestamptz not null default now()
);
comment on table public.users is 'Application-level user profile; auth lives in Supabase Auth.';

-- ---------------------------------------------------------------------------
-- 2. devices
--    A device only accepts telemetry after it has been authorized through an
--    explicit pairing flow. There is no stealth enrolment path.
-- ---------------------------------------------------------------------------
create table if not exists public.devices (
    id             uuid primary key default gen_random_uuid(),
    device_id      text not null unique,
    name           text not null,
    os_name        text,
    os_version     text,
    hostname       text,
    arch           text,
    agent_version  text,
    status         text not null default 'PENDING'
                   check (status in ('PENDING', 'AUTHORIZED', 'REVOKED')),
    pairing_code   text,
    authorized_at  timestamptz,
    revoked_at     timestamptz,
    last_seen      timestamptz,
    cpu_percent    double precision,
    memory_percent double precision,
    disk_percent   double precision,
    risk_score     integer not null default 0
                   check (risk_score between 0 and 100),
    agent_ip       text,
    meta           jsonb not null default '{}'::jsonb,
    created_at     timestamptz not null default now(),
    updated_at     timestamptz not null default now()
);
create index if not exists idx_devices_last_seen on public.devices (last_seen desc);
create index if not exists idx_devices_status    on public.devices (status);

-- ---------------------------------------------------------------------------
-- 3. pairing_codes
--    Short-lived codes an operator generates in the UI and types into the
--    agent. One-time use; enforces explicit authorisation.
-- ---------------------------------------------------------------------------
create table if not exists public.pairing_codes (
    code       text primary key,
    created_at timestamptz not null default now(),
    expires_at timestamptz not null,
    used_at    timestamptz,
    used_by    text
);
create index if not exists idx_pairing_expires on public.pairing_codes (expires_at);

-- ---------------------------------------------------------------------------
-- 4. agents
-- ---------------------------------------------------------------------------
create table if not exists public.agents (
    id                   uuid primary key default gen_random_uuid(),
    device_pk            uuid not null unique references public.devices(id) on delete cascade,
    agent_version        text,
    python_version       text,
    platform             text,
    interval_s           integer not null default 10,
    last_heartbeat       timestamptz,
    consecutive_failures integer not null default 0,
    last_error           text,
    created_at           timestamptz not null default now(),
    updated_at           timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- 5. system_metrics
-- ---------------------------------------------------------------------------
create table if not exists public.system_metrics (
    id                  bigserial primary key,
    device_id           uuid not null references public.devices(id) on delete cascade,
    ts                  timestamptz not null,
    cpu_percent         double precision,
    memory_percent      double precision,
    disk_percent        double precision,
    swap_percent        double precision,
    load_average        double precision,
    process_count       integer,
    thread_count        integer,
    handle_count        integer,
    disk_free_gb        double precision,
    disk_read_mbps      double precision,
    disk_write_mbps     double precision,
    context_switch_rate double precision,
    uptime_seconds      bigint,
    temperature_c       double precision,
    raw                 jsonb not null default '{}'::jsonb
);
create index if not exists idx_sysmetrics_device_ts on public.system_metrics (device_id, ts desc);
create index if not exists idx_sysmetrics_ts         on public.system_metrics (ts desc);

-- ---------------------------------------------------------------------------
-- 6. network_metrics
--    Interface-level counters only. No payload capture, no packet inspection.
-- ---------------------------------------------------------------------------
create table if not exists public.network_metrics (
    id           bigserial primary key,
    device_id    uuid not null references public.devices(id) on delete cascade,
    ts           timestamptz not null,
    iface        text,
    bytes_sent   bigint,
    bytes_recv   bigint,
    packets_sent bigint,
    packets_recv bigint,
    errin        bigint,
    errout       bigint,
    dropin       bigint,
    dropout      bigint,
    sent_mbps    double precision,
    recv_mbps    double precision,
    connections  integer,
    raw          jsonb not null default '{}'::jsonb
);
create index if not exists idx_netmetrics_device_ts on public.network_metrics (device_id, ts desc);

-- ---------------------------------------------------------------------------
-- 7. process_snapshots
--    Deliberately excludes the full command line: process arguments routinely
--    contain tokens and passwords. Only identity + resource metadata is kept.
-- ---------------------------------------------------------------------------
create table if not exists public.process_snapshots (
    id             bigserial primary key,
    device_id      uuid not null references public.devices(id) on delete cascade,
    ts             timestamptz not null,
    pid            integer,
    ppid           integer,
    name           text,
    owner          text,
    status         text,
    cpu_percent    double precision,
    memory_percent double precision,
    rss_mb         double precision,
    num_threads    integer,
    create_time    timestamptz
);
create index if not exists idx_procs_device_ts on public.process_snapshots (device_id, ts desc);
create index if not exists idx_procs_name     on public.process_snapshots (name);

-- ---------------------------------------------------------------------------
-- 8. logs
-- ---------------------------------------------------------------------------
create table if not exists public.logs (
    id          bigserial primary key,
    device_id   uuid not null references public.devices(id) on delete cascade,
    ts          timestamptz not null,
    source      text,
    level       text check (level in ('INFO', 'WARNING', 'ERROR', 'CRITICAL', 'ANOMALY')),
    message     text,
    logger_name text,
    module      text,
    line_no     integer,
    fingerprint text,
    occurrences integer not null default 1,
    attributes  jsonb not null default '{}'::jsonb
);
create index if not exists idx_logs_device_ts  on public.logs (device_id, ts desc);
create index if not exists idx_logs_level      on public.logs (level);
create index if not exists idx_logs_fingerprint on public.logs (fingerprint);

-- ---------------------------------------------------------------------------
-- 9. anomalies
-- ---------------------------------------------------------------------------
create table if not exists public.anomalies (
    id             uuid primary key default gen_random_uuid(),
    device_id      uuid not null references public.devices(id) on delete cascade,
    ts             timestamptz not null,
    metric         text not null,
    observed_value double precision,
    expected_value double precision,
    baseline_std   double precision,
    delta          double precision,
    ratio          double precision,
    model          text,
    model_scores   jsonb not null default '{}'::jsonb,
    anomaly_score  double precision,
    risk_score     integer not null default 0 check (risk_score between 0 and 100),
    severity       text not null check (severity in ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    explanation    text,
    evidence       jsonb not null default '{}'::jsonb,
    features       jsonb not null default '{}'::jsonb,
    acknowledged   boolean not null default false,
    created_at     timestamptz not null default now()
);
create index if not exists idx_anom_device_ts on public.anomalies (device_id, ts desc);
create index if not exists idx_anom_severity  on public.anomalies (severity);
create index if not exists idx_anom_metric    on public.anomalies (metric);

-- ---------------------------------------------------------------------------
-- 10. alerts
-- ---------------------------------------------------------------------------
create table if not exists public.alerts (
    id              uuid primary key default gen_random_uuid(),
    device_id       uuid not null references public.devices(id) on delete cascade,
    anomaly_id      uuid references public.anomalies(id) on delete set null,
    ts              timestamptz not null,
    title           text not null,
    message         text,
    metric          text,
    severity        text not null check (severity in ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    risk_score      integer not null default 0 check (risk_score between 0 and 100),
    status          text not null default 'NEW'
                    check (status in ('NEW', 'ACKNOWLEDGED', 'RESOLVED')),
    acknowledged_at timestamptz,
    resolved_at     timestamptz,
    resolved_by     text,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);
create index if not exists idx_alerts_device_ts on public.alerts (device_id, ts desc);
create index if not exists idx_alerts_status    on public.alerts (status);
create index if not exists idx_alerts_severity  on public.alerts (severity);

-- ---------------------------------------------------------------------------
-- 11. risk_events
-- ---------------------------------------------------------------------------
create table if not exists public.risk_events (
    id           bigserial primary key,
    device_id    uuid not null references public.devices(id) on delete cascade,
    ts           timestamptz not null,
    window_start timestamptz,
    window_end   timestamptz,
    risk_score   integer not null default 0 check (risk_score between 0 and 100),
    severity     text not null,
    composite    jsonb not null default '{}'::jsonb,
    summary      text
);
create index if not exists idx_risk_device_ts on public.risk_events (device_id, ts desc);

-- ---------------------------------------------------------------------------
-- 12. documents
-- ---------------------------------------------------------------------------
create table if not exists public.documents (
    id           uuid primary key default gen_random_uuid(),
    filename     text not null,
    title        text,
    content_type text,
    size_bytes   bigint not null default 0,
    checksum     text,
    source       text not null default 'UPLOAD'
                 check (source in ('UPLOAD', 'SAMPLE', 'AGENT_LOG')),
    pages        integer not null default 0,
    chunk_count  integer not null default 0,
    status       text not null default 'PENDING'
                 check (status in ('PENDING', 'INDEXED', 'FAILED')),
    error        text,
    meta         jsonb not null default '{}'::jsonb,
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now()
);
create index if not exists idx_documents_created on public.documents (created_at desc);

-- ---------------------------------------------------------------------------
-- 13. document_chunks
--    `embedding` holds a float8[] so the vector index can be rebuilt after a
--    cold start without re-reading the source document. For larger corpora,
--    enable pgvector (see the optional block at the end of this file).
-- ---------------------------------------------------------------------------
create table if not exists public.document_chunks (
    id             bigserial primary key,
    document_id    uuid not null references public.documents(id) on delete cascade,
    chunk_index    integer not null,
    content        text not null,
    token_estimate integer,
    char_start     integer,
    char_end       integer,
    page           integer,
    heading        text,
    embedding      float8[],
    meta           jsonb not null default '{}'::jsonb,
    created_at     timestamptz not null default now(),
    unique (document_id, chunk_index)
);
create index if not exists idx_chunks_document on public.document_chunks (document_id, chunk_index);

-- ---------------------------------------------------------------------------
-- 14. rag_queries
-- ---------------------------------------------------------------------------
create table if not exists public.rag_queries (
    id          bigserial primary key,
    document_id uuid references public.documents(id) on delete set null,
    query       text not null,
    top_k       integer,
    provider    text,
    hit_count   integer,
    top_score   double precision,
    latency_ms  integer,
    answer      text,
    sources     jsonb not null default '[]'::jsonb,
    created_at  timestamptz not null default now()
);
create index if not exists idx_ragq_created on public.rag_queries (created_at desc);

-- ---------------------------------------------------------------------------
-- 15. ai_investigations
-- ---------------------------------------------------------------------------
create table if not exists public.ai_investigations (
    id         bigserial primary key,
    device_id  uuid references public.devices(id) on delete cascade,
    anomaly_id uuid references public.anomalies(id) on delete set null,
    question   text,
    answer     text,
    provider   text,
    model      text,
    evidence   jsonb not null default '{}'::jsonb,
    confidence double precision,
    citations  jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now()
);
create index if not exists idx_investigations_created on public.ai_investigations (created_at desc);

-- ---------------------------------------------------------------------------
-- 16. system_events
-- ---------------------------------------------------------------------------
create table if not exists public.system_events (
    id         bigserial primary key,
    ts         timestamptz not null default now(),
    level      text not null default 'INFO',
    source     text not null default 'sentinel',
    message    text,
    context    jsonb not null default '{}'::jsonb
);
create index if not exists idx_sysevts_created on public.system_events (ts desc);

-- =============================================================================
-- Row Level Security
-- =============================================================================
-- The platform is designed to run either as a trusted single-tenant service
-- (service-role key, RLS effectively open) or multi-tenant. The policies below
-- implement the multi-tenant model: every tenant-scoped table is readable and
-- writable only by authenticated members of the owning user.
-- =============================================================================

create or replace function public.current_app_user_id()
returns uuid
language sql
stable
security definer
set search_path = public
as $$
    select id from public.users where auth_user_id = auth.uid() limit 1;
$$;

do $$
declare
    t text;
begin
    foreach t in array array[
        'devices', 'agents', 'system_metrics', 'network_metrics',
        'process_snapshots', 'logs', 'anomalies', 'alerts', 'risk_events',
        'documents', 'document_chunks', 'rag_queries', 'ai_investigations',
        'system_events', 'pairing_codes'
    ]
    loop
        execute format('alter table public.%I enable row level security;', t);
    end loop;
end
$$;

-- Single-operator deployment: authenticated users may read and write telemetry.
-- Tighten further by adding `and owner_user_id = public.current_app_user_id()`
-- once a tenancy column is introduced.
drop policy if exists "sentinel_authenticated_all" on public.devices;
create policy "sentinel_authenticated_all" on public.devices
    for all to authenticated using (true) with check (true);

do $$
declare
    t text;
begin
    foreach t in array array[
        'system_metrics', 'network_metrics', 'process_snapshots', 'logs',
        'anomalies', 'alerts', 'risk_events', 'documents', 'document_chunks',
        'rag_queries', 'ai_investigations', 'system_events', 'pairing_codes',
        'agents'
    ]
    loop
        execute format('drop policy if exists sentinel_authenticated_all on public.%I;', t);
        execute format(
            'create policy sentinel_authenticated_all on public.%I '
            'for all to authenticated using (true) with check (true);', t);
    end loop;
end
$$;

-- =============================================================================
-- Row Level Security on public.users (self-service)
-- =============================================================================
alter table public.users enable row level security;
drop policy if exists "users_self_read" on public.users;
create policy "users_self_read" on public.users
    for select to authenticated using (auth_user_id = auth.uid());

-- =============================================================================
-- updated_at maintenance
-- =============================================================================
create or replace function public.touch_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at := now();
    return new;
end;
$$;

do $$
declare
    t text;
begin
    foreach t in array array['devices', 'agents', 'alerts', 'documents']
    loop
        execute format('drop trigger if exists trg_touch_updated_at on public.%I;', t);
        execute format(
            'create trigger trg_touch_updated_at before update on public.%I '
            'for each row execute function public.touch_updated_at();', t);
    end loop;
end
$$;

-- =============================================================================
-- Convenience view: latest posture per device
-- =============================================================================
create or replace view public.device_posture as
select
    d.id,
    d.device_id,
    d.name,
    d.os_name,
    d.status,
    d.last_seen,
    d.risk_score,
    d.cpu_percent,
    d.memory_percent,
    d.disk_percent,
    (select count(*) from public.alerts a
      where a.device_id = d.id and a.status <> 'RESOLVED')          as open_alerts,
    (select count(*) from public.anomalies an
      where an.device_id = d.id
        and an.ts > now() - interval '24 hours')                     as anomalies_24h
from public.devices d;

-- =============================================================================
-- OPTIONAL: pgvector upgrade path for large corpora
-- =============================================================================
-- create extension if not exists vector;
-- alter table public.document_chunks
--     add column embedding_vector vector(384);
-- create index idx_chunks_vector
--     on public.document_chunks
--     using ivfflat (embedding_vector vector_cosine_ops) with (lists = 100);
-- update public.document_chunks
--    set embedding_vector = embedding::vector
--  where embedding is not null;
