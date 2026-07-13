'use client'

import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, CheckCircle2, Loader2, XCircle } from 'lucide-react'

import { AppShell } from '@/app/_components/app-shell'
import { apiFetch } from '@/app/_lib/api'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'

const ROUND_LABELS: Record<number, string> = { 1: '第1轮·翻译', 2: '第2轮·填空', 3: '第3轮·造句', 4: '第4轮·综合', 5: '第5轮·综合' }
const PRACTICE_TYPES: Record<number, string> = { 1: '翻译练习', 2: '填空练习', 3: '造句练习', 4: '综合练习' }

type ReviewItem = { review_id: number; list_id: number; round: number; day_number: number }
type PracticeList = { id: number; day_number: number; has_sentences: number }
type ExerciseItem = {
  id: number; type: string; prompt: string; answer: string
  blank_sentence?: string; hint_word?: string
}
type ExerciseData = {
  review_id?: number; round: number; round_name: string; language: string
  items: ExerciseItem[]; total: number
}

export default function ReviewPage() {
  const [reviews, setReviews] = useState<ReviewItem[]>([])
  const [practiceLists, setPracticeLists] = useState<PracticeList[]>([])
  const [exercise, setExercise] = useState<ExerciseData | null>(null)
  const [exerciseIdx, setExerciseIdx] = useState(0)
  const [answer, setAnswer] = useState('')
  const [feedback, setFeedback] = useState<{ passed: boolean; text: string } | null>(null)
  const [scoring, setScoring] = useState(false)
  const [correct, setCorrect] = useState(0)
  const [total, setTotal] = useState(0)
  const [isPractice, setIsPractice] = useState(false)
  const [hint, setHint] = useState<string | null>(null)
  const [done, setDone] = useState(false)
  const [loading, setLoading] = useState(false)
  const pendingRef = useRef<Promise<ExerciseData> | null>(null)
  const inputRef = useRef<HTMLInputElement | HTMLTextAreaElement>(null)

  const loadReviews = async () => {
    const [revRes, practRes] = await Promise.all([
      apiFetch('/api/reviews/today'),
      apiFetch('/api/practice/lists'),
    ])
    if (revRes.ok) setReviews(await revRes.json())
    if (practRes.ok) setPracticeLists(await practRes.json())
  }

  useEffect(() => { loadReviews() }, [])

  const startExercise = async (reviewId: number) => {
    setLoading(true)
    const data: ExerciseData = await apiFetch(`/api/reviews/${reviewId}/exercise?limit=3`).then((r) => r.json())
    if (!data.items?.length) {
      await apiFetch(`/api/reviews/${reviewId}/done`, { method: 'POST' })
      await loadReviews()
      setLoading(false)
      return
    }
    setExercise(data); setExerciseIdx(0); setCorrect(0); setTotal(data.total)
    setFeedback(null); setAnswer(''); setDone(false); setHint(null); setIsPractice(false)
    setLoading(false)
    pendingRef.current = data.total > 3
      ? apiFetch(`/api/reviews/${reviewId}/exercise?offset=3`).then((r) => r.json())
      : null
    setTimeout(() => inputRef.current?.focus(), 100)
  }

  const startPractice = async (listId: number, round: number) => {
    setLoading(true)
    const data: ExerciseData = await apiFetch(`/api/practice/${listId}/exercise?round=${round}&limit=3`).then((r) => r.json())
    if (!data.items?.length) { setLoading(false); return }
    setExercise(data); setExerciseIdx(0); setCorrect(0); setTotal(data.total)
    setFeedback(null); setAnswer(''); setDone(false); setHint(null); setIsPractice(true)
    setLoading(false)
    pendingRef.current = data.total > 3
      ? apiFetch(`/api/practice/${listId}/exercise?round=${round}&offset=3`).then((r) => r.json())
      : null
    setTimeout(() => inputRef.current?.focus(), 100)
  }

  const submit = async () => {
    if (!exercise || !answer.trim() || scoring) return
    const item = exercise.items[exerciseIdx]
    setScoring(true)
    const res = await apiFetch('/api/reviews/score', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_answer: answer, correct_answer: item.answer, exercise_type: item.type, language: exercise.language }),
    })
    const data = await res.json()
    setFeedback({ passed: data.passed, text: data.feedback })
    if (data.passed) setCorrect((c) => c + 1)
    setScoring(false)
  }

  const next = async () => {
    if (!exercise) return
    const nextIdx = exerciseIdx + 1
    if (nextIdx >= exercise.items.length) {
      if (pendingRef.current) {
        const more: ExerciseData = await pendingRef.current
        pendingRef.current = null
        if (more.items?.length) {
          setExercise({ ...exercise, items: [...exercise.items, ...more.items] })
          setExerciseIdx(nextIdx)
          setFeedback(null); setAnswer(''); setHint(null)
          setTimeout(() => inputRef.current?.focus(), 100)
          return
        }
      }
      if (!isPractice && exercise.review_id) {
        await apiFetch(`/api/reviews/${exercise.review_id}/done`, { method: 'POST' })
        await loadReviews()
      }
      setDone(true)
      return
    }
    setExerciseIdx(nextIdx)
    setFeedback(null); setAnswer(''); setHint(null)
    setTimeout(() => inputRef.current?.focus(), 100)
  }

  const retry = () => {
    setFeedback(null); setAnswer(''); setHint(null)
    setTimeout(() => inputRef.current?.focus(), 100)
  }

  const showHint = async () => {
    if (!exercise) return
    const item = exercise.items[exerciseIdx]
    const res = await apiFetch('/api/reviews/hint', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sentence: item.answer, word: item.hint_word }),
    })
    const data = await res.json()
    setHint(`首字母 ${data.first_letter}，共 ${data.length} 个字母`)
  }

  const backToList = () => {
    setExercise(null); setDone(false)
  }

  // ── Exercise view ──
  if (exercise) {
    const item = exercise.items[exerciseIdx]
    const displayTotal = total || exercise.items.length

    return (
      <AppShell>
        <div className="page">
          <div className="mb-4 flex items-center gap-3">
            <Button size="sm" variant="outline" onClick={backToList} className="gap-1 text-xs">
              <ArrowLeft className="h-3.5 w-3.5" /> 返回
            </Button>
            <h2 className="mb-0 text-xl font-semibold">{exercise.round_name}</h2>
            <span className="ml-auto text-sm text-[var(--text-light)]">{done ? displayTotal : exerciseIdx + 1} / {displayTotal}</span>
          </div>

          <Card>
            <CardContent className="p-6">
              {done ? (
                <div className="py-10 text-center">
                  <CheckCircle2 className="mx-auto mb-3 h-12 w-12 text-green-500" />
                  <h3 className="mb-1 text-lg font-semibold">练习完成！</h3>
                  <p className="text-[var(--text-light)]">正确 {correct} / {displayTotal}</p>
                  <Button className="mt-6" onClick={backToList}>返回复习列表</Button>
                </div>
              ) : (
                <>
                  <div className="mb-4 space-y-3">
                    {item.type === 'translate' && (
                      <>
                        <p className="text-xs font-medium text-[var(--text-light)]">请将以下句子翻译成中文：</p>
                        <p className="rounded bg-[var(--highlight)] px-3 py-2 text-[15px]">{item.prompt}</p>
                        <Textarea
                          ref={inputRef as React.RefObject<HTMLTextAreaElement>}
                          rows={2}
                          value={answer}
                          onChange={(e) => setAnswer(e.target.value)}
                          placeholder="输入中文翻译…"
                          onKeyDown={(e) => { if (e.ctrlKey && e.key === 'Enter') submit() }}
                        />
                      </>
                    )}
                    {item.type === 'fill' && (
                      <>
                        <p className="text-xs font-medium text-[var(--text-light)]">根据中文意思，填入正确的单词：</p>
                        <p className="rounded bg-[var(--highlight)] px-3 py-2 text-[15px]">{item.prompt}</p>
                        <p className="rounded border border-[var(--border)] px-3 py-2 text-[15px]">{item.blank_sentence}</p>
                        <Input
                          ref={inputRef as React.RefObject<HTMLInputElement>}
                          value={answer}
                          onChange={(e) => setAnswer(e.target.value)}
                          placeholder="输入单词…"
                          autoComplete="off"
                          onKeyDown={(e) => { if (e.key === 'Enter') submit() }}
                        />
                      </>
                    )}
                    {item.type === 'word_def' && (
                      <>
                        <p className="text-xs font-medium text-[var(--text-light)]">请写出这个单词的中文意思：</p>
                        <p className="rounded bg-[var(--highlight)] px-3 py-2 text-3xl font-bold">{item.prompt}</p>
                        <Input
                          ref={inputRef as React.RefObject<HTMLInputElement>}
                          value={answer}
                          onChange={(e) => setAnswer(e.target.value)}
                          placeholder="输入中文释义…"
                          autoComplete="off"
                          onKeyDown={(e) => { if (e.key === 'Enter') submit() }}
                        />
                      </>
                    )}
                    {item.type === 'def_word' && (
                      <>
                        <p className="text-xs font-medium text-[var(--text-light)]">根据释义，写出对应的单词：</p>
                        <p className="rounded bg-[var(--highlight)] px-3 py-2 text-[15px]">{item.prompt}</p>
                        <Input
                          ref={inputRef as React.RefObject<HTMLInputElement>}
                          value={answer}
                          onChange={(e) => setAnswer(e.target.value)}
                          placeholder="输入单词…"
                          autoComplete="off"
                          onKeyDown={(e) => { if (e.key === 'Enter') submit() }}
                        />
                      </>
                    )}
                    {item.type === 'write' && (
                      <>
                        <p className="text-xs font-medium text-[var(--text-light)]">根据中文意思，写出完整的句子：</p>
                        <p className="rounded bg-[var(--highlight)] px-3 py-2 text-[15px]">{item.prompt}</p>
                        <Textarea
                          ref={inputRef as React.RefObject<HTMLTextAreaElement>}
                          rows={2}
                          value={answer}
                          onChange={(e) => setAnswer(e.target.value)}
                          placeholder="输入完整句子…"
                          onKeyDown={(e) => { if (e.ctrlKey && e.key === 'Enter') submit() }}
                        />
                        {hint && <p className="text-xs text-[var(--text-light)]">提示：{hint}</p>}
                      </>
                    )}
                  </div>

                  {feedback && (
                    <div className={`mb-4 flex items-start gap-2 rounded px-3 py-2 text-sm ${feedback.passed ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'}`}>
                      {feedback.passed
                        ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
                        : <XCircle className="mt-0.5 h-4 w-4 shrink-0" />}
                      {feedback.text}
                    </div>
                  )}

                  <div className="flex gap-2">
                    {item.type === 'write' && !feedback && (
                      <Button size="sm" variant="outline" onClick={showHint} className="text-xs">提示</Button>
                    )}
                    {feedback ? (
                      <>
                        <Button size="sm" variant="outline" onClick={retry} className="text-xs">重新作答</Button>
                        <Button className="ml-auto" onClick={next}>
                          {exerciseIdx + 1 >= (exercise.items.length) && !pendingRef.current ? '完成' : '下一题'}
                        </Button>
                      </>
                    ) : (
                      <Button
                        className="ml-auto gap-1.5"
                        onClick={submit}
                        disabled={scoring || !answer.trim()}
                      >
                        {scoring && <Loader2 className="h-4 w-4 animate-spin" />}
                        提交
                      </Button>
                    )}
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        </div>
      </AppShell>
    )
  }

  // ── List view ──
  return (
    <AppShell>
      <div id="page-review" className="page">
        <h2 className="mb-4 text-xl font-semibold">今日复习</h2>

        {loading && (
          <div className="flex items-center gap-2 py-4 text-[var(--text-light)]">
            <Loader2 className="h-4 w-4 animate-spin" /> 加载中…
          </div>
        )}

        {reviews.length === 0 && !loading ? (
          <Card id="no-review" className="mb-4">
            <CardContent className="p-6 text-[var(--text-light)]">今天没有需要复习的内容 🎉</CardContent>
          </Card>
        ) : (
          <div id="review-list" className="mb-6 space-y-2">
            {reviews.map((r) => (
              <div key={r.review_id} className="review-item">
                <span>
                  第 {r.day_number} 天的单词
                  <span className="round-tag">{ROUND_LABELS[r.round] || '复习'}</span>
                </span>
                <Button style={{ margin: 0 }} onClick={() => startExercise(r.review_id)}>
                  开始练习
                </Button>
              </div>
            ))}
          </div>
        )}

        {practiceLists.length > 0 && (
          <div id="practice-section">
            <h3 className="mb-3 text-base font-semibold">自主练习</h3>
            <div id="practice-list" className="space-y-2">
              {practiceLists.map((l) => (
                <div key={l.id} className="review-item">
                  <span>第 {l.day_number} 天的单词</span>
                  <div className="flex flex-wrap gap-1.5">
                    {l.has_sentences
                      ? Object.entries(PRACTICE_TYPES).map(([r, name]) => (
                          <Button key={r} size="sm" variant="secondary" onClick={() => startPractice(l.id, parseInt(r))}>
                            {name}
                          </Button>
                        ))
                      : <span className="text-[13px] text-[var(--text-light)]">请先在今日学习中生成课文</span>
                    }
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </AppShell>
  )
}
