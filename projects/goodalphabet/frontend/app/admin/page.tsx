'use client'

import { useEffect, useMemo, useState } from 'react'
import { Database, RefreshCcw, Search, ShieldCheck } from 'lucide-react'

import { AppShell } from '@/app/_components/app-shell'
import { apiFetch } from '@/app/_lib/api'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'

type AdminUser = {
  user_id: string
  name: string | null
  email: string | null
  tokens: number
  hourly_requests: number
  generated: boolean | null
  stripe_subscription: string | null
  stripe_customer: string | null
  last_payment_time: string | null
  access_expires_at: string | null
  active: boolean
  time: string | null
  last_request_time: string | null
}

type DashboardPayload = {
  admin_email: string
  database: {
    kind: string
    configured: boolean
  }
  summary: {
    total_users: number
    paid_users: number
    active_paid_users: number
    total_tokens: number
  }
  users: AdminUser[]
}

function formatDate(value: string | null) {
  if (!value) return '-'
  return new Date(value).toLocaleString('zh-CN')
}

function formatNumber(value: number) {
  return value.toLocaleString('zh-CN')
}

export default function AdminPage() {
  const [data, setData] = useState<DashboardPayload | null>(null)
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [savingUserId, setSavingUserId] = useState<string | null>(null)
  const [tokenDrafts, setTokenDrafts] = useState<Record<string, string>>({})

  const users = data?.users ?? []
  const summaryCards = useMemo(() => {
    if (!data) return []
    return [
      { label: '用户总数', value: formatNumber(data.summary.total_users) },
      { label: '已支付用户', value: formatNumber(data.summary.paid_users) },
      { label: '有效会员', value: formatNumber(data.summary.active_paid_users) },
      { label: '剩余 tokens', value: formatNumber(data.summary.total_tokens) },
    ]
  }, [data])

  async function loadDashboard(nextQuery = query) {
    setLoading(true)
    setError('')
    try {
      const params = new URLSearchParams()
      if (nextQuery.trim()) params.set('q', nextQuery.trim())
      params.set('limit', '100')
      const response = await apiFetch(`/api/admin/dashboard?${params.toString()}`, { redirect: 'manual' })
      if (!response.ok) {
        const payload = await response.json().catch(() => null)
        throw new Error(payload?.detail || payload?.error || `后台接口返回 ${response.status}`)
      }
      const payload = (await response.json()) as DashboardPayload
      setData(payload)
      setTokenDrafts(
        Object.fromEntries(payload.users.map((user) => [user.user_id, String(user.tokens)])),
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载后台数据失败')
    } finally {
      setLoading(false)
    }
  }

  async function updateUser(userId: string, body: Record<string, unknown>) {
    setSavingUserId(userId)
    setError('')
    try {
      const response = await apiFetch(`/api/admin/users/${encodeURIComponent(userId)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        redirect: 'manual',
      })
      if (!response.ok) {
        const payload = await response.json().catch(() => null)
        throw new Error(payload?.detail || payload?.error || `更新失败 ${response.status}`)
      }
      await loadDashboard()
    } catch (err) {
      setError(err instanceof Error ? err.message : '更新失败')
    } finally {
      setSavingUserId(null)
    }
  }

  useEffect(() => {
    loadDashboard()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <AppShell>
      <div className="page space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="mb-1 flex items-center gap-2">
              <ShieldCheck className="size-6" />
              后台管理
            </h2>
            <p className="text-sm text-[var(--text-light)]">
              直连后端数据库接口，管理用户 token 和 30 天访问权限。
            </p>
          </div>
          <Button variant="outline" className="gap-2" onClick={() => loadDashboard()} disabled={loading}>
            <RefreshCcw className="size-4" />
            刷新
          </Button>
        </div>

        {error ? <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div> : null}

        <div className="grid gap-3 md:grid-cols-4">
          {summaryCards.map((item) => (
            <Card key={item.label}>
              <CardContent className="p-4">
                <div className="text-sm text-[var(--text-light)]">{item.label}</div>
                <div className="mt-1 text-2xl font-semibold">{item.value}</div>
              </CardContent>
            </Card>
          ))}
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <Database className="size-5" />
              数据库连接
            </CardTitle>
          </CardHeader>
          <CardContent className="grid gap-2 text-sm md:grid-cols-3">
            <div>类型：{data?.database.kind ?? '-'}</div>
            <div>已配置：{data?.database.configured ? '是' : '否'}</div>
            <div>管理员：{data?.admin_email ?? '-'}</div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex flex-wrap items-center justify-between gap-3 text-lg">
              <span>用户</span>
              <form
                className="flex w-full max-w-md gap-2"
                onSubmit={(event) => {
                  event.preventDefault()
                  loadDashboard(query)
                }}
              >
                <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索 user_id / email / name" />
                <Button type="submit" variant="secondary" className="gap-2">
                  <Search className="size-4" />
                  搜索
                </Button>
              </form>
            </CardTitle>
          </CardHeader>
          <CardContent className="overflow-x-auto p-0">
            <table className="min-w-[1100px] w-full border-collapse text-sm">
              <thead>
                <tr className="border-b bg-[var(--highlight)] text-left">
                  <th className="p-3">用户</th>
                  <th className="p-3">Tokens</th>
                  <th className="p-3">会员</th>
                  <th className="p-3">Stripe</th>
                  <th className="p-3">请求</th>
                  <th className="p-3">创建时间</th>
                  <th className="p-3">操作</th>
                </tr>
              </thead>
              <tbody>
                {users.map((user) => (
                  <tr key={user.user_id} className="border-b align-top">
                    <td className="max-w-[280px] p-3">
                      <div className="font-medium">{user.email || user.name || '-'}</div>
                      <div className="break-all text-xs text-[var(--text-light)]">{user.user_id}</div>
                    </td>
                    <td className="p-3">
                      <Input
                        className="w-32"
                        type="number"
                        min={0}
                        value={tokenDrafts[user.user_id] ?? String(user.tokens)}
                        onChange={(event) => setTokenDrafts((current) => ({ ...current, [user.user_id]: event.target.value }))}
                      />
                    </td>
                    <td className="p-3">
                      <div className={user.active ? 'font-medium text-green-700' : 'font-medium text-stone-600'}>
                        {user.active ? '有效' : '未开通'}
                      </div>
                      <div className="text-xs text-[var(--text-light)]">{formatDate(user.access_expires_at)}</div>
                    </td>
                    <td className="max-w-[260px] p-3">
                      <div className="break-all text-xs">{user.stripe_subscription || '-'}</div>
                      <div className="mt-1 text-xs text-[var(--text-light)]">{formatDate(user.last_payment_time)}</div>
                    </td>
                    <td className="p-3">
                      <div>{formatNumber(user.hourly_requests)}</div>
                      <div className="text-xs text-[var(--text-light)]">{formatDate(user.last_request_time)}</div>
                    </td>
                    <td className="p-3">{formatDate(user.time)}</td>
                    <td className="space-y-2 p-3">
                      <div className="flex flex-wrap gap-2">
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={savingUserId === user.user_id}
                          onClick={() => updateUser(user.user_id, { tokens: Number(tokenDrafts[user.user_id] || 0) })}
                        >
                          保存 token
                        </Button>
                        <Button
                          size="sm"
                          variant="secondary"
                          disabled={savingUserId === user.user_id}
                          onClick={() => updateUser(user.user_id, { grant_days: 30 })}
                        >
                          授权 30 天
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={savingUserId === user.user_id}
                          onClick={() => updateUser(user.user_id, { clear_payment: true })}
                        >
                          清除会员
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
                {!loading && users.length === 0 ? (
                  <tr>
                    <td className="p-6 text-center text-[var(--text-light)]" colSpan={7}>
                      没有匹配用户
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
            {loading ? <div className="p-6 text-center text-[var(--text-light)]">正在加载...</div> : null}
          </CardContent>
        </Card>
      </div>
    </AppShell>
  )
}
