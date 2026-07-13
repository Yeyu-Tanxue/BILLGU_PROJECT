'use client'

import { useState } from 'react'
import { Loader2, Sparkles } from 'lucide-react'
import { usePathname } from 'next/navigation'

import { apiFetch } from '@/app/_lib/api'
import { Button } from '@/components/ui/button'

type AccessCheckoutButtonProps = {
  className?: string
  sourceOverride?: string
  label?: string
}

export function AccessCheckoutButton({
  className,
  sourceOverride,
  label = '支付一次，解锁 30 天',
}: AccessCheckoutButtonProps) {
  const pathname = usePathname()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const source = sourceOverride || pathname

  const startCheckout = async () => {
    setLoading(true)
    setError('')

    try {
      const response = await apiFetch('/api/billing/checkout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source }),
      })

      const contentType = response.headers.get('content-type') || ''
      const payload = contentType.includes('application/json')
        ? (await response.json())
        : { error: await response.text() }

      if (!response.ok || !payload.url) {
        throw new Error(payload.detail || payload.error || 'Checkout 不可用')
      }

      window.location.href = payload.url
    } catch (checkoutError) {
      setError(checkoutError instanceof Error ? checkoutError.message : 'Checkout 不可用')
      setLoading(false)
    }
  }

  return (
    <div className={className}>
      <Button type="button" onClick={startCheckout} disabled={loading} className="gap-2">
        {loading ? <Loader2 className="size-4 animate-spin" /> : <Sparkles className="size-4" />}
        {label}
      </Button>
      {error ? <p className="mt-2 text-sm text-red-600">{error}</p> : null}
    </div>
  )
}
