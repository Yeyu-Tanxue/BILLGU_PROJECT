'use client'

import { useEffect, useMemo, useState } from 'react'

import { AppShell } from '@/app/_components/app-shell'
import { apiFetch } from '@/app/_lib/api'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Slider } from '@/components/ui/slider'

const PRESET_TAGS = ['日常生活', '科技', '旅行', '美食', '体育', '商务', '影视娱乐', '校园']

type Book = { id: number; name: string; language: string }
type Plan = { id: number; book_name: string; daily_count: number; learned_lists: number; total_lists: number; start_date: string; interests?: string }

function asBookArray(value: unknown): Book[] {
  return Array.isArray(value) ? (value as Book[]) : []
}

function asPlanArray(value: unknown): Plan[] {
  return Array.isArray(value) ? (value as Plan[]) : []
}

export default function SetupPage() {
  const [books, setBooks] = useState<Book[]>([])
  const [language, setLanguage] = useState('en')
  const [bookId, setBookId] = useState('')
  const [dailyCount, setDailyCount] = useState(30)
  const [selectedTags, setSelectedTags] = useState<string[]>([])
  const [customTags, setCustomTags] = useState('')
  const [currentPlan, setCurrentPlan] = useState<Plan | null>(null)
  const [history, setHistory] = useState<Plan[]>([])
  const [pendingDelete, setPendingDelete] = useState<number | null>(null)
  const [pendingRestore, setPendingRestore] = useState<number | null>(null)
  const [createError, setCreateError] = useState('')

  // Edit interests for current plan
  const [editInterestTags, setEditInterestTags] = useState<string[]>([])
  const [editCustomTags, setEditCustomTags] = useState('')
  const [interestMsg, setInterestMsg] = useState('')

  const filteredBooks = useMemo(() => books.filter((b) => b.language === language), [books, language])

  useEffect(() => {
    if (filteredBooks.length === 0) { setBookId(''); return }
    if (!filteredBooks.some((b) => String(b.id) === bookId)) {
      setBookId(String(filteredBooks[0].id))
    }
  }, [filteredBooks, bookId])

  useEffect(() => {
    apiFetch('/api/wordbooks').then(async (res) => {
      if (res.ok) setBooks(asBookArray(await res.json()))
      else setCreateError('单词书加载失败，请刷新页面后重试。')
    })
  }, [language])

  const loadPlans = async () => {
    const [currentRes, historyRes] = await Promise.all([
      apiFetch('/api/plan'),
      apiFetch('/api/plan/history'),
    ])
    if (currentRes.ok) {
      const plan = (await currentRes.json()) as Plan | null
      setCurrentPlan(plan)
      if (plan?.interests) {
        try {
          const interests: string[] = JSON.parse(plan.interests)
          setEditInterestTags(interests.filter((t) => PRESET_TAGS.includes(t)))
          setEditCustomTags(interests.filter((t) => !PRESET_TAGS.includes(t)).join('，'))
        } catch { /* ignore */ }
      }
    }
    if (historyRes.ok) setHistory(asPlanArray(await historyRes.json()))
  }

  useEffect(() => { loadPlans() }, [])

  const saveInterests = async () => {
    const interests = [
      ...editInterestTags,
      ...editCustomTags.split(/[,，]/).map((s) => s.trim()).filter(Boolean),
    ]
    const res = await apiFetch('/api/plan/interests', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ interests }),
    })
    setInterestMsg(res.ok ? '✓ 已保存，新课文将使用新话题' : '保存失败，请重试')
    setTimeout(() => setInterestMsg(''), 3000)
  }

  return (
    <AppShell>
      <div id="page-setup" className="page">
        {currentPlan && (
          <Card id="current-plan-card" className="card mb-4">
            <CardContent className="p-6">
              <div className="mb-2 flex items-center justify-between">
                <h3>当前计划</h3>
                <span className="text-[13px] text-[var(--text-light)]">进度 {currentPlan.learned_lists}/{currentPlan.total_lists}</span>
              </div>
              <p className="mb-4">{currentPlan.book_name} · 每日{currentPlan.daily_count}词 · 开始于{currentPlan.start_date}</p>

              <label className="mb-2 block text-sm font-semibold">课文话题偏好（可修改）</label>
              <div className="interest-tags mb-2" id="plan-interest-tags">
                {PRESET_TAGS.map((tag) => (
                  <span
                    key={tag}
                    className={`tag ${editInterestTags.includes(tag) ? 'selected' : ''}`}
                    onClick={() => setEditInterestTags((prev) =>
                      prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag]
                    )}
                  >
                    {tag}
                  </span>
                ))}
              </div>
              <Input
                className="mb-2"
                value={editCustomTags}
                onChange={(e) => setEditCustomTags(e.target.value)}
                placeholder="自定义话题，用逗号分隔"
              />
              <div className="flex items-center gap-3">
                <Button size="sm" variant="secondary" onClick={saveInterests}>保存话题</Button>
                {interestMsg && (
                  <span className={`text-sm ${interestMsg.startsWith('✓') ? 'text-green-600' : 'text-red-600'}`}>
                    {interestMsg}
                  </span>
                )}
              </div>
            </CardContent>
          </Card>
        )}

        {history.length > 0 && (
          <Card id="history-plan-card" className="card mb-4">
            <CardContent className="p-6">
              <h3 className="mb-3">历史计划</h3>
              <div id="history-plan-list" className="space-y-3">
                {history.map((item) => {
                  let interests: string[] = []
                  try { interests = JSON.parse(item.interests || '[]') } catch { /* ignore */ }
                  return (
                    <div key={item.id} className="review-item">
                      <div>
                        <div><b>{item.book_name}</b> · 每日{item.daily_count}词</div>
                        <div className="text-[13px] text-[var(--text-light)]">
                          {item.start_date} · 进度 {item.learned_lists}/{item.total_lists}
                          {interests.length > 0 && ` · 话题：${interests.join('、')}`}
                        </div>
                      </div>
                      <div className="flex gap-1.5">
                        <Button size="sm" variant="outline" onClick={() => setPendingRestore(item.id)}>恢复</Button>
                        <Button size="sm" variant="secondary" onClick={() => setPendingDelete(item.id)}>删除</Button>
                      </div>
                    </div>
                  )
                })}
              </div>
            </CardContent>
          </Card>
        )}

        <h2>创建新计划</h2>
        <Card className="card">
          <CardContent className="space-y-3 p-6">
            <label>选择语言</label>
            <Select value={language} onValueChange={setLanguage}>
              <SelectTrigger>
                <SelectValue placeholder="选择语言" />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value="en">英语</SelectItem>
                  <SelectItem value="ja">日语</SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>

            <label>选择单词书</label>
            <Select value={bookId} onValueChange={setBookId}>
              <SelectTrigger>
                <SelectValue placeholder="选择单词书" />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {filteredBooks.map((b) => (
                    <SelectItem key={b.id} value={String(b.id)}>{b.name}</SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>

            <label>每日单词量</label>
            <div className="slider-group">
              <Slider
                min={10}
                max={100}
                step={5}
                value={[dailyCount]}
                onValueChange={(value) => setDailyCount(value[0] ?? dailyCount)}
              />
              <span>{dailyCount}</span>词/天
            </div>

            <label>课文话题（可多选）</label>
            <div className="interest-tags" id="interest-tags">
              {PRESET_TAGS.map((tag) => (
                <span
                  key={tag}
                  className={`tag ${selectedTags.includes(tag) ? 'selected' : ''}`}
                  onClick={() => setSelectedTags((prev) => prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag])}
                >
                  {tag}
                </span>
              ))}
            </div>
            <Input value={customTags} onChange={(e) => setCustomTags(e.target.value)} placeholder="自定义话题，用逗号分隔" />
            <Button
              onClick={async () => {
                setCreateError('')
                if (!bookId) { setCreateError('请先选择一个单词书。'); return }
                const interests = [...selectedTags, ...customTags.split(/[,，]/).map((s) => s.trim()).filter(Boolean)]
                const res = await apiFetch('/api/plan', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ book_id: Number(bookId), daily_count: dailyCount, interests }),
                })
                if (!res.ok) {
                  let detail = '创建计划失败，请稍后重试。'
                  try {
                    const body = await res.json()
                    detail = body?.detail || body?.error || detail
                  } catch { /* no-op */ }
                  setCreateError(String(detail))
                  return
                }
                window.location.href = '/learn'
              }}
            >
              创建计划
            </Button>
            {createError && <p className="text-sm text-red-600">{createError}</p>}
          </CardContent>
        </Card>
      </div>

      <Dialog open={pendingDelete !== null} onOpenChange={(o) => !o && setPendingDelete(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>删除历史计划</DialogTitle>
            <DialogDescription>确定删除此计划吗？所有学习记录将被永久删除。</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPendingDelete(null)}>取消</Button>
            <Button
              variant="secondary"
              onClick={async () => {
                if (pendingDelete) {
                  await apiFetch(`/api/plan/${pendingDelete}`, { method: 'DELETE' })
                  setHistory((prev) => prev.filter((p) => p.id !== pendingDelete))
                }
                setPendingDelete(null)
              }}
            >
              删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={pendingRestore !== null} onOpenChange={(o) => !o && setPendingRestore(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>恢复历史计划</DialogTitle>
            <DialogDescription>恢复此计划？当前计划将被归档。</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPendingRestore(null)}>取消</Button>
            <Button
              onClick={async () => {
                if (pendingRestore) {
                  await apiFetch(`/api/plan/${pendingRestore}/restore`, { method: 'POST' })
                  window.location.href = '/learn'
                }
                setPendingRestore(null)
              }}
            >
              确认恢复
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </AppShell>
  )
}
