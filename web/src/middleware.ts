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

  const csp = [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'`,
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com",
    "img-src 'self' data: blob:",
    "media-src 'self' blob:",          // needed for VoiceConversation
    "connect-src 'self' ws: wss:",
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
