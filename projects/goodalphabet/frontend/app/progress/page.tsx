'use client'

import { useEffect, useMemo, useState } from 'react'

import { AppShell } from '@/app/_components/app-shell'
import { apiFetch } from '@/app/_lib/api'
import { Card, CardContent } from '@/components/ui/card'

type PlanSummary = {
  book_name: string; daily_count: number; start_date: string; active: number
  total_lists: number; learned_lists: number
}
type Progress = {
  book_name: string; daily_count: number; start_date: string
  learned_lists: number; total_lists: number
  learned_words: number; total_words: number; pending_reviews: number
  all_plans: PlanSummary[]
  total_study_days: number; total_learned_words_all: number
}

const CIRCUMFERENCE = 2 * Math.PI * 52

export default function ProgressPage() {
  const [progress, setProgress] = useState<Progress | null>(null)

  useEffect(() => {
    apiFetch('/api/progress').then(async (res) => {
      if (res.ok) setProgress(await res.json())
    })
  }, [])

  const pct = useMemo(() => {
    if (!progress || progress.total_words === 0) return 0
    return Math.round((progress.learned_words / progress.total_words) * 100)
  }, [progress])

  const dashLen = (pct / 100) * CIRCUMFERENCE

  return (
    <AppShell>
      <div id="page-progress" className="page">
        <h2 className="mb-4 text-xl font-semibold">学习进度</h2>

        <Card className="mb-4">
          <CardContent className="p-6">
            <div className="progress-overview">
              <div className="ring-chart-wrap">
                <svg viewBox="0 0 120 120" className="h-full w-full">
                  <circle cx="60" cy="60" r="52" fill="none" stroke="hsl(var(--border))" strokeWidth="10" />
                  <circle
                    cx="60" cy="60" r="52" fill="none"
                    stroke="hsl(var(--accent))" strokeWidth="10" strokeLinecap="round"
                    strokeDasharray={`${dashLen} ${CIRCUMFERENCE}`}
                    transform="rotate(-90 60 60)"
                  />
                  <text x="60" y="60" textAnchor="middle" dominantBaseline="central"
                    fontSize="22" fontWeight="bold" fill="var(--text)">
                    {pct}%
                  </text>
                </svg>
              </div>
              <div>
                <div className="progress-book-name">{progress?.book_name || '暂无计划'}</div>
                <div className="progress-meta">
                  {progress
                    ? <>每日 {progress.daily_count} 词 · 已学 {progress.learned_lists}/{progress.total_lists} 课<br />开始于 {progress.start_date}</>
                    : '尚未开始'
                  }
                </div>
              </div>
            </div>

            <div className="progress-grid mt-4">
              <div className="text-center">
                <div className="stat-num">{progress?.learned_words ?? 0}</div>
                <div className="stat-label">已学单词</div>
              </div>
              <div className="text-center">
                <div className="stat-num">{progress?.learned_lists ?? 0}</div>
                <div className="stat-label">已学课数</div>
              </div>
              <div className="text-center">
                <div className="stat-num">{progress?.total_words ?? 0}</div>
                <div className="stat-label">总单词数</div>
              </div>
              <div className="text-center">
                <div className="stat-num">{progress?.pending_reviews ?? 0}</div>
                <div className="stat-label">待复习</div>
              </div>
            </div>
          </CardContent>
        </Card>

        {progress?.all_plans && progress.all_plans.length > 1 && (
          <Card className="mb-4">
            <CardContent className="p-6">
              <h3 className="mb-4 text-base font-semibold">所有计划</h3>
              <div className="space-y-4">
                {progress.all_plans.map((p, i) => {
                  const barPct = p.total_lists > 0 ? Math.round((p.learned_lists / p.total_lists) * 100) : 0
                  return (
                    <div key={i}>
                      <div className="mb-1 flex items-center justify-between text-sm">
                        <span className="font-medium">{p.book_name}</span>
                        <span className="flex items-center gap-1.5">
                          <span className={`inline-block rounded px-1.5 py-0.5 text-xs text-white ${p.active ? 'bg-[hsl(var(--primary))]' : 'bg-[hsl(var(--border))] text-[var(--text)]'}`}>
                            {p.active ? '当前' : '历史'}
                          </span>
                          <span className="text-[var(--text-light)]">{p.learned_lists}/{p.total_lists} 课</span>
                        </span>
                      </div>
                      <div className="h-2 overflow-hidden rounded-full bg-[var(--highlight)]">
                        <div
                          className={`h-full rounded-full ${p.active ? 'bg-[hsl(var(--primary))]' : 'bg-[hsl(var(--border))]'}`}
                          style={{ width: `${barPct}%` }}
                        />
                      </div>
                      <div className="mt-0.5 text-xs text-[var(--text-light)]">每日{p.daily_count}词 · {p.start_date}</div>
                    </div>
                  )
                })}
              </div>
            </CardContent>
          </Card>
        )}

        <Card>
          <CardContent className="p-6">
            <h3 className="mb-4 text-base font-semibold">总体统计</h3>
            <div className="grid grid-cols-2 gap-4 text-center">
              <div>
                <div className="stat-num">{progress?.total_study_days ?? 0}</div>
                <div className="stat-label">累计学习天数</div>
              </div>
              <div>
                <div className="stat-num">{progress?.total_learned_words_all ?? 0}</div>
                <div className="stat-label">累计学习单词</div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </AppShell>
  )
}
