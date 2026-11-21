import { isIP } from 'node:net';
import type { NextRequest } from 'next/server';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const hopByHop = ['connection', 'content-length', 'host', 'keep-alive', 'proxy-authenticate', 'proxy-authorization', 'te', 'trailer', 'transfer-encoding', 'upgrade'];

type RouteContext = { params: Promise<{ segments: string[] }> };

async function proxy(request: NextRequest, { params }: RouteContext) {
  const { segments } = await params;
  const base = process.env.API_INTERNAL_URL || 'http://127.0.0.1:8000';
  const target = new URL(`/api/v1/${segments.map(encodeURIComponent).join('/')}${request.nextUrl.search}`, base);
  const headers = new Headers(request.headers);
  for (const header of hopByHop) headers.delete(header);
  headers.set('accept-encoding', 'identity');
  headers.set('x-forwarded-host', request.headers.get('host') || request.nextUrl.host);
  headers.set('x-forwarded-proto', request.nextUrl.protocol.replace(':', ''));
  headers.delete('x-forwarded-for');
  const edgeAddress = request.headers.get('x-real-ip');
  headers.delete('x-real-ip');
  if (process.env.TRUST_EDGE_PROXY === 'true' && edgeAddress && isIP(edgeAddress)) {
    headers.set('x-forwarded-for', edgeAddress);
  }
  const body = request.method === 'GET' || request.method === 'HEAD' ? null : request.body;

  try {
    const options: RequestInit & { duplex?: 'half' } = {
      method: request.method,
      headers,
      body,
      cache: 'no-store',
      redirect: 'manual',
      signal: request.signal,
    };
    if (body) options.duplex = 'half';
    const upstream = await fetch(target, options);
    const responseHeaders = new Headers(upstream.headers);
    for (const header of hopByHop) responseHeaders.delete(header);
    responseHeaders.delete('content-encoding');
    responseHeaders.delete('set-cookie');
    for (const cookie of upstream.headers.getSetCookie()) responseHeaders.append('set-cookie', cookie);
    return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
  } catch {
    return Response.json({ detail: 'The processing service is temporarily unavailable. Please try again.' }, { status: 503 });
  }
}

export const GET = proxy;
export const HEAD = proxy;
export const POST = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
export const OPTIONS = proxy;
