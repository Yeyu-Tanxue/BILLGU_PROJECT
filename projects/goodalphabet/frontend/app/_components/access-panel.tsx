'use client'

import { AlertTriangle, CalendarClock, CreditCard } from 'lucide-react'

import { AccessCheckoutButton } from '@/app/_components/access-checkout-button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

export type BillingStatus = {
  active: boolean
  has_access: boolean
  tokens: number
  checkout_configured: boolean
  access_expires_at: string | null
  days_remaining: number | null
  last_payment_at: string | null
}

type AccessPanelProps = {
  status: BillingStatus | null
  title?: string
  description?: string
  sourceOverride?: string
  className?: string
}

export function AccessPanel({
  status,
  title = '会员访问',
  description = '支付一次即可获得 30 天应用访问权限。',
  sourceOverride,
  className,
}: AccessPanelProps) {
  const accessLabel = status?.active
    ? status.access_expires_at
      ? `当前有效，${new Date(status.access_expires_at).toLocaleDateString('zh-CN')} 到期`
      : '当前有效'
    : status && status.tokens > 0
      ? `试用中，剩余 ${status.tokens.toLocaleString('zh-CN')} tokens`
    : '未开通'

  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-xl">
          <CreditCard className="size-5" />
          {title}
        </CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="rounded-md border border-dashed p-4">
          <div className="flex items-center gap-2 text-sm font-medium">
            <CalendarClock className="size-4" />
            {accessLabel}
          </div>
          {!status?.has_access ? (
            <p className="mt-2 flex items-start gap-2 text-sm text-stone-600">
              <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-600" />
              token 用完后可支付一次开通 30 天，不会自动续费。
            </p>
          ) : null}
          {status?.days_remaining ? <p className="mt-2 text-sm text-stone-600">剩余 {status.days_remaining} 天</p> : null}
        </div>

        {status?.has_access ? null : status === null || status.checkout_configured ? (
          <AccessCheckoutButton sourceOverride={sourceOverride} />
        ) : (
          <p className="text-sm text-red-600">Stripe 价格未配置，暂时无法创建支付链接。</p>
        )}
      </CardContent>
    </Card>
  )
}
