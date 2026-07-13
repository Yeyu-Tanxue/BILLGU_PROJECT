import { NextResponse } from 'next/server'

import { auth0 } from '@/lib/auth0'

function adminEmails() {
  return new Set(
    (process.env.ADMIN_EMAILS || '')
      .split(',')
      .map((item) => item.trim().toLowerCase())
      .filter(Boolean),
  )
}

export async function GET() {
  const session = await auth0.getSession()
  if (!session?.user) {
    return NextResponse.json({ error: 'unauthorized' }, { status: 401 })
  }

  const email = (session.user.email || '').trim().toLowerCase()
  const admins = adminEmails()

  return NextResponse.json({
    sub: session.user.sub,
    name: session.user.name,
    email: session.user.email,
    is_admin: admins.size > 0 && admins.has(email),
  })
}
