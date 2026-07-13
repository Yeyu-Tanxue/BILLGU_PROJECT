'use client'

import Link from 'next/link'
import { useEffect, useMemo, useState } from 'react'
import { CheckCircle2, XCircle } from 'lucide-react'

import { AppShell } from '@/app/_components/app-shell'
import { AccessPanel, type BillingStatus } from '@/app/_components/access-panel'
import { apiFetch } from '@/app/_lib/api'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'

function getQueryValue(name: string) {
  if (typeof window === 'undefined') return null
  return new URLSearchParams(window.location.search).get(name)
}

export default function BillingPage() {
  const [status, setStatus] = useState<BillingStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [checkoutResult, setCheckoutResult] = useState<string | null>(null)
  const [returnTo, setReturnTo] = useState('/setup')

  useEffect(() => {
    setCheckoutResult(getQueryValue('checkout'))
    const requestedReturnTo = getQueryValue('returnTo')
    if (requestedReturnTo?.startsWith('/')) {
      setReturnTo(requestedReturnTo)
    }

    ;(async () => {
      try {
        const response = await apiFetch('/api/billing/status', { redirect: 'manual' })
        if (response.ok) {
          setStatus((await response.json()) as BillingStatus)
        }
      } finally {
        setLoading(false)
      }
    })()
  }, [])

  const resultAlert = useMemo(() => {
    if (checkoutResult === 'success') {
      return (
        <Alert className="border-green-200 bg-green-50 text-green-950">
          <CheckCircle2 className="size-4" />
          <AlertTitle>支付已完成</AlertTitle>
          <AlertDescription>会员权限会在 Stripe webhook 到达后自动刷新。</AlertDescription>
        </Alert>
      )
    }

    if (checkoutResult === 'cancelled') {
      return (
        <Alert variant="destructive">
          <XCircle className="size-4" />
          <AlertTitle>支付已取消</AlertTitle>
          <AlertDescription>你可以重新发起支付，成功后开通 30 天访问权限。</AlertDescription>
        </Alert>
      )
    }

    return null
  }, [checkoutResult])

  return (
    <AppShell>
      <div className="page mx-auto max-w-2xl space-y-4">
        {resultAlert}
        <AccessPanel status={status} sourceOverride={returnTo} />
        {loading ? <p className="text-sm text-[var(--text-light)]">正在同步会员状态...</p> : null}
        <Button asChild variant="outline">
          <Link href={returnTo}>返回学习</Link>
        </Button>
      </div>
    </AppShell>
  )
}
