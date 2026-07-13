import { NextRequest, NextResponse } from 'next/server'

import { auth0 } from '@/lib/auth0'

const BACKEND_BASE = (
  process.env.API_BASE_URL ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  ''
).replace(/\/$/, '')

function buildBackendUrl(request: NextRequest, pathSegments: string[]) {
  let path = `/${pathSegments.join('/')}`
  if (BACKEND_BASE.endsWith('/api') && path.startsWith('/api/')) {
    path = path.slice('/api'.length)
  }
  const query = request.nextUrl.search
  return `${BACKEND_BASE}${path}${query}`
}

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params
  const session = await auth0.getSession()
  if (!session?.user) {
    return NextResponse.json({ error: 'unauthorized' }, { status: 401 })
  }

  let accessToken = ''
  try {
    const tokenResponse = await auth0.getAccessToken()
    if (typeof tokenResponse === 'string') {
      accessToken = tokenResponse
    } else {
      accessToken = tokenResponse?.token || (tokenResponse as { accessToken?: string })?.accessToken || ''
    }
  } catch {
    return NextResponse.json({ error: 'failed_to_get_access_token' }, { status: 401 })
  }

  if (!accessToken) {
    return NextResponse.json({ error: 'empty_access_token' }, { status: 401 })
  }

  const headers = new Headers(request.headers)
  headers.delete('host')
  headers.delete('connection')
  headers.delete('content-length')
  headers.set('authorization', `Bearer ${accessToken}`)

  const hasBody = request.method !== 'GET' && request.method !== 'HEAD'
  const body = hasBody ? await request.arrayBuffer() : undefined
  const response = await fetch(buildBackendUrl(request, path), {
    method: request.method,
    headers,
    body,
    cache: 'no-store',
  } as RequestInit)

  const responseHeaders = new Headers(response.headers)
  responseHeaders.delete('content-encoding')
  responseHeaders.delete('transfer-encoding')

  return new NextResponse(response.body, {
    status: response.status,
    headers: responseHeaders,
  })
}

export async function GET(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  return proxy(request, context)
}

export async function POST(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  return proxy(request, context)
}

export async function PUT(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  return proxy(request, context)
}

export async function PATCH(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  return proxy(request, context)
}

export async function DELETE(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  return proxy(request, context)
}

export async function OPTIONS(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  return proxy(request, context)
}
