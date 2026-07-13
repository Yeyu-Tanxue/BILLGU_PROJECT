'use client'

import { useEffect, useMemo, useState } from 'react'

import { AppShell } from '@/app/_components/app-shell'
import { apiFetch } from '@/app/_lib/api'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'

const WEEK = ['日', '一', '二', '三', '四', '五', '六']
const ROUND_LABELS: Record<number, string> = { 1: '第1轮·翻译', 2: '第2轮·填空', 3: '第3轮·造句', 4: '第4轮·综合', 5: '第5轮·综合' }

type CalDay = { date: string; total: number; done: number }
type ReviewByDate = { review_id: number; list_id: number; round: number; completed: number; day_number: number }

export default function CalendarPage() {
  const now = new Date()
  const [year, setYear] = useState(now.getFullYear())
  const [month, setMonth] = useState(now.getMonth() + 1)
  const [calData, setCalData] = useState<CalDay[]>([])
  const [detail, setDetail] = useState<{ date: string; reviews: ReviewByDate[] } | null>(null)

  const todayStr = useMemo(() => {
    const d = new Date()
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  }, [])

  const loadCalendar = async (y: number, m: number) => {
    const res = await apiFetch(`/api/reviews/calendar?year=${y}&month=${m}`)
    if (res.ok) setCalData(await res.json())
  }

  useEffect(() => { loadCalendar(year, month) }, [year, month])

  const changeMonth = (delta: number) => {
    let m = month + delta
    let y = year
    if (m > 12) { m = 1; y++ }
    if (m < 1) { m = 12; y-- }
    setMonth(m); setYear(y)
    setDetail(null)
  }

  const dateMap = useMemo(() => {
    const m = new Map<string, CalDay>()
    calData.forEach((d) => m.set(d.date, d))
    return m
  }, [calData])

  const cells = useMemo(() => {
    const first = new Date(year, month - 1, 1).getDay()
    const days = new Date(year, month, 0).getDate()
    return [...Array(first).fill(0), ...Array.from({ length: days }, (_, i) => i + 1)]
  }, [year, month])

  const showDateDetail = async (dateStr: string) => {
    const res = await apiFetch(`/api/reviews/by-date?date=${dateStr}`)
    if (res.ok) setDetail({ date: dateStr, reviews: await res.json() })
  }

  return (
    <AppShell>
      <div id="page-calendar" className="page">
        <div className="calendar-header">
          <Button size="sm" variant="secondary" onClick={() => changeMonth(-1)}>&lt; 上月</Button>
          <h2 className="mb-0" id="calendar-title">{year}年{month}月</h2>
          <Button size="sm" variant="secondary" onClick={() => changeMonth(1)}>下月 &gt;</Button>
        </div>

        <div className="calendar-grid" id="calendar-grid">
          {WEEK.map((w) => <div key={w} className="cal-header">{w}</div>)}
          {cells.map((d, i) => {
            if (!d) return <div key={i} className="cal-day empty" />
            const ds = `${year}-${String(month).padStart(2, '0')}-${String(d).padStart(2, '0')}`
            const info = dateMap.get(ds)
            const isToday = ds === todayStr
            return (
              <div
                key={i}
                className={`cal-day cursor-pointer hover:bg-[var(--highlight)] ${isToday ? 'ring-2 ring-[hsl(var(--primary))]' : ''} ${info ? 'has-review' : ''}`}
                onClick={() => showDateDetail(ds)}
              >
                <div className={`day-num text-sm ${isToday ? 'font-bold text-[hsl(var(--primary))]' : ''}`}>{d}</div>
                {info && (
                  <div className="cal-dots">
                    {Array.from({ length: info.done }).map((_, j) => (
                      <span key={`d${j}`} className="cal-dot" style={{ background: 'hsl(var(--accent))' }} />
                    ))}
                    {Array.from({ length: info.total - info.done }).map((_, j) => (
                      <span key={`p${j}`} className="cal-dot" />
                    ))}
                  </div>
                )}
              </div>
            )
          })}
        </div>

        {detail && (
          <Card id="calendar-detail" className="card mt-4">
            <CardContent className="p-6">
              <h3 className="mb-3 text-base font-semibold" id="calendar-detail-title">{detail.date}</h3>
              <div id="calendar-detail-list" className="space-y-2">
                {detail.reviews.length === 0 ? (
                  <p className="text-[var(--text-light)]">该日无复习安排</p>
                ) : (
                  detail.reviews.map((r) => (
                    <div key={r.review_id} className="review-item">
                      <span>
                        第 {r.day_number} 天
                        <span className="round-tag">{ROUND_LABELS[r.round] || '复习'}</span>
                      </span>
                      <span className="text-sm">{r.completed ? '✅ 已完成' : '⏳ 待完成'}</span>
                    </div>
                  ))
                )}
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </AppShell>
  )
}
