'use client'

import { useEffect, useMemo, useState } from 'react'
import { usePathname } from 'next/navigation'

import { TopNav } from '@/app/_components/top-nav'
import { AccessPanel, type BillingStatus } from '@/app/_components/access-panel'
import { apiFetch } from '@/app/_lib/api'

export function AppShell({ children }: { children: React.ReactNode }) {
  const [username, setUsername] = useState('')
  const [isAdmin, setIsAdmin] = useState(false)
  const [billingStatus, setBillingStatus] = useState<BillingStatus | null>(null)
  const [ready, setReady] = useState(false)
  const pathname = usePathname()
  const isBillingPage = pathname === '/billing'
  const isAdminPage = pathname === '/admin' || pathname === '/admin/xhs'

  useEffect(() => {
    let cancelled = false

    ;(async () => {
      try {
        const sessionRes = await fetch('/bff/session', { credentials: 'include' })

        if (sessionRes.ok) {
          const data = (await sessionRes.json()) as { name?: string; email?: string; is_admin?: boolean }
          if (!cancelled) {
            setUsername(data.name || data.email || '')
            setIsAdmin(Boolean(data.is_admin))
          }
        }

        if (!isAdminPage) {
          const billingRes = await apiFetch('/api/billing/status', { redirect: 'manual' })
          if (!cancelled && billingRes.ok) {
            setBillingStatus((await billingRes.json()) as BillingStatus)
          }
        }
      } catch {
        if (!cancelled) {
          setBillingStatus(null)
        }
      } finally {
        if (!cancelled) {
          setReady(true)
        }

      }
    })()

    return () => {
      cancelled = true
    }
  }, [isAdminPage, isBillingPage])

  const accessLabel = useMemo(() => {
    if (billingStatus?.active && billingStatus.access_expires_at) {
      return `有效期至 ${new Date(billingStatus.access_expires_at).toLocaleDateString('zh-CN')}`
    }
    if (billingStatus?.active) {
      return '会员有效'
    }
    if (billingStatus && billingStatus.tokens > 0) {
      return `试用 ${billingStatus.tokens.toLocaleString('zh-CN')} tokens`
    }
    return '未开通'
  }, [billingStatus])

  if (!ready && !isBillingPage) {
    return <main>Loading...</main>
  }

  return (
    <>
      <TopNav username={username} accessLabel={accessLabel} isAdmin={isAdmin} />
      {isAdminPage && !isAdmin ? (
        <main className="page space-y-4">
          <div className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700">
            当前账号没有后台权限。请确认生产环境已配置 <code>ADMIN_EMAILS</code>，并且当前登录邮箱在白名单内。
          </div>
        </main>
      ) : !billingStatus?.has_access && !isBillingPage && !isAdminPage ? (
        <main className="space-y-6">
          <AccessPanel
            status={billingStatus}
            sourceOverride={pathname}
            className="mx-auto max-w-2xl"
          />
        </main>
      ) : (
        <main>{children}</main>
      )}
    </>
  )
}
