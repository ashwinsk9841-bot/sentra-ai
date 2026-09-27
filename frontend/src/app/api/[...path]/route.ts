import { NextRequest, NextResponse } from 'next/server';

/**
 * Same-origin proxy to the SENTRA AI Python backend.
 *
 * The browser only ever calls `/api/*` on its own origin. The real backend URL
 * is read from `SENTRA_API_URL` (server-side only), so no hostname, port or
 * secret is shipped to the client.
 *
 * In production `SENTRA_API_URL` is required: a missing value is reported as a
 * configuration error rather than silently falling back to localhost, which
 * would look like a healthy app in preview deployments and then fail in prod.
 */

export const dynamic = 'force-dynamic';

const DEV_BACKEND = 'http://127.0.0.1:8787';

/** Reads are cheap dashboard polls; writes may invoke the LLM and take longer. */
const READ_TIMEOUT_MS = Number(process.env.SENTRA_API_TIMEOUT_MS ?? 20_000);
const WRITE_TIMEOUT_MS = Number(process.env.SENTRA_API_WRITE_TIMEOUT_MS ?? 60_000);

/**
 * Resolves the backend origin for this request.
 *
 * Returns `null` when `SENTRA_API_URL` is missing in production, which the
 * caller turns into an actionable 500.
 */
function resolveBackend(): string | null {
  const configured = process.env.SENTRA_API_URL?.trim();
  if (configured) return configured.replace(/\/+$/, '');

  if (process.env.NODE_ENV === 'production') return null;

  return DEV_BACKEND;
}

function misconfigured(): NextResponse {
  return NextResponse.json(
    {
      ok: false,
      error:
        'SENTRA_API_URL is not set. Add the backend origin (for example ' +
        'https://sentra-api.onrender.com) to the server-side environment.',
    },
    { status: 500, headers: { 'Cache-Control': 'no-store' } },
  );
}

async function proxy(request: NextRequest, path: string[]) {
  const backend = resolveBackend();
  if (!backend) return misconfigured();

  const isWrite = request.method !== 'GET' && request.method !== 'HEAD';
  const timeoutMs = isWrite ? WRITE_TIMEOUT_MS : READ_TIMEOUT_MS;
  const target = `${backend}/api/${path.join('/')}${request.nextUrl.search}`;
  const method = request.method;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const init: RequestInit = {
      method,
      signal: controller.signal,
      cache: 'no-store',
      headers: { Accept: 'application/json' },
    };

    if (isWrite) {
      const raw = await request.text();
      init.body = raw && raw.length ? raw : '{}';
      init.headers = {
        ...init.headers,
        'Content-Type': 'application/json',
      };
    }

    const response = await fetch(target, init);
    const text = await response.text();

    return new NextResponse(text, {
      status: response.status,
      headers: {
        'Content-Type': response.headers.get('content-type') ?? 'application/json; charset=utf-8',
        'Cache-Control': 'no-store',
      },
    });
  } catch (error) {
    const aborted = error instanceof Error && error.name === 'AbortError';
    return NextResponse.json(
      {
        ok: false,
        error: aborted
          ? `Backend request timed out after ${timeoutMs}ms`
          : `Cannot reach the SENTRA backend at ${backend}. Start it with: ` +
            `python -m uvicorn sentinel.api.server:app --port 8787`,
      },
      { status: aborted ? 504 : 502, headers: { 'Cache-Control': 'no-store' } },
    );
  } finally {
    clearTimeout(timer);
  }
}

type Context = { params: { path: string[] } };

export async function GET(request: NextRequest, context: Context) {
  return proxy(request, context.params.path ?? []);
}

export async function POST(request: NextRequest, context: Context) {
  return proxy(request, context.params.path ?? []);
}
