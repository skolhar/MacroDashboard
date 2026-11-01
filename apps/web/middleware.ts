import { NextRequest, NextResponse } from 'next/server';

function equal(a: string, b: string): boolean {
  let mismatch = a.length ^ b.length;
  for (let index = 0; index < Math.max(a.length, b.length); index++) mismatch |= (a.charCodeAt(index) || 0) ^ (b.charCodeAt(index) || 0);
  return mismatch === 0;
}

export function middleware(request: NextRequest) {
  const user = process.env.RESEARCH_UI_USER;
  const password = process.env.RESEARCH_UI_PASSWORD;
  if (!user || !password || !process.env.RESEARCH_OPERATOR_TOKEN) return new NextResponse('Not found', { status: 404 });
  const authorization = request.headers.get('authorization') || '';
  let presented = '';
  if (authorization.startsWith('Basic ')) {
    try { presented = atob(authorization.slice(6)); } catch { /* malformed credentials */ }
  }
  if (!equal(presented, `${user}:${password}`)) return new NextResponse('Private research authentication required', { status: 401, headers: { 'WWW-Authenticate': 'Basic realm="SmartHedge Private Research"', 'Cache-Control': 'no-store' } });
  return NextResponse.next();
}

export const config = { matcher: ['/intelligence/:path*'] };
