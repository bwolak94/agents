/**
 * F28 — Next.js Edge middleware: generates a per-request CSP nonce and
 * forwards it as both a response header and an `x-nonce` request header
 * so server components can inject it into inline <script> tags.
 */
import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

// Paths that don't need CSP nonce injection (static assets, API routes)
const SKIP_PATHS = ['/_next/static', '/_next/image', '/favicon.ico', '/api/'];

function generateNonce(): string {
  // Edge runtime: use crypto.getRandomValues
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return btoa(String.fromCharCode(...bytes));
}

export function middleware(request: NextRequest) {
  const path = request.nextUrl.pathname;
  if (SKIP_PATHS.some(p => path.startsWith(p))) {
    return NextResponse.next();
  }

  const nonce = generateNonce();
  const isDev = process.env.NODE_ENV === 'development';

  // In dev, Next.js HMR requires unsafe-eval; strict-dynamic + nonce in prod
  const scriptSrc = isDev
    ? `script-src 'self' 'unsafe-eval' 'nonce-${nonce}'`
    : `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'`;

  const csp = [
    "default-src 'self'",
    scriptSrc,
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com data:",
    "img-src 'self' data: blob:",
    "media-src 'self' blob:",
    "connect-src 'self' ws: wss: http://localhost:8000",
    "worker-src 'self' blob:",
  ].join('; ');

  // Forward nonce to server components via request header
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set('x-nonce', nonce);

  const response = NextResponse.next({
    request: { headers: requestHeaders },
  });
  response.headers.set('Content-Security-Policy', csp);
  return response;
}

export const config = {
  matcher: '/((?!_next/static|_next/image|favicon\\.ico).*)',
};
