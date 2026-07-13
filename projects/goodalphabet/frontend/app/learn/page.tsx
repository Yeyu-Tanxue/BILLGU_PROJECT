'use client'

import { useEffect, useRef, useState } from 'react'
import { CheckCircle2, Loader2, Sparkles, Square, Volume2 } from 'lucide-react'
import { toast } from 'sonner'

import { AppShell } from '@/app/_components/app-shell'
import { apiFetch } from '@/app/_lib/api'
import { Button } from '@/components/ui/button'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Card, CardContent } from '@/components/ui/card'
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Slider } from '@/components/ui/slider'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'

type Word = { word: string; phonetic?: string; definition: string }
type LearnData = {
  list_id: number
  day_number: number
  words: Word[]
  story?: string
  finished?: boolean
  language?: string
}

type HighlightSpan = { type: 'highlight'; word: string; def: string }
type TextSpan = { type: 'text'; content: string }
type Span = HighlightSpan | TextSpan
type Sentence = { spans: Span[]; text: string }
type Paragraph = { sentences: Sentence[]; paraIdx: number }

const TOKEN_SHORTAGE_TEXT = 'token不足，请联系管理员'

function isTokenShortageMessage(input: string) {
  return /(token\s*limit\s*exceeded|token\s*不足|token不足|quota|配额|额度|无法完成请求|联系管理员)/i.test(input)
}

function notifyTokenShortage(raw: string) {
  if (!isTokenShortageMessage(raw)) return false
  toast.error(TOKEN_SHORTAGE_TEXT)
  return true
}

function applyTranslationLine(
  text: string,
  target: string[],
  fallbackIndex: number
) {
  const line = text.trim()
  if (!line) return fallbackIndex

  const m = line.match(/^(\d+)[.、:：\s-]*\s*(.*)$/)
  if (m) {
    const idx = Number(m[1]) - 1
    if (idx >= 0 && idx < target.length) {
      target[idx] = m[2].trim()
      return idx
    }
    return fallbackIndex
  }

  if (fallbackIndex >= 0 && fallbackIndex < target.length) {
    target[fallbackIndex] = `${target[fallbackIndex]} ${line}`.trim()
  }
  return fallbackIndex
}

function parseStory(story: string, words: Word[]): Paragraph[] {
  const wordMap = new Map<string, string>()
  words.forEach((w) => wordMap.set(w.word.toLowerCase(), w.definition))

  const paragraphs: Paragraph[] = []
  let paraIdx = 0

  story.split('\n').forEach((rawPara) => {
    const para = rawPara.replace(/^#+\s*/, '')
    if (!para.trim()) return

    const highlights: Array<{ word: string; def: string }> = []
    const processed = para.replace(/\*\*([^*]+)\*\*/g, (_, word) => {
      const def = wordMap.get(word.toLowerCase()) || ''
      const idx = highlights.length
      highlights.push({ word, def })
      return `\x00H${idx}\x00`
    })

    const rawSentences = processed.match(/[^.!?。！？]+[.!?。！？]+|[^.!?。！？]+$/g) || [processed]
    const sentences: Sentence[] = rawSentences.map((raw) => {
      const parts = raw.split(/(\x00H\d+\x00)/)
      const spans: Span[] = parts.map((part) => {
        const m = part.match(/^\x00H(\d+)\x00$/)
        if (m) {
          const h = highlights[parseInt(m[1])]
          return { type: 'highlight' as const, word: h.word, def: h.def }
        }
        return { type: 'text' as const, content: part }
      })
      const text = raw.replace(/\x00H(\d+)\x00/g, (_, i) => highlights[parseInt(i)].word)
      return { spans, text }
    })

    paragraphs.push({ sentences, paraIdx })
    paraIdx++
  })

  return paragraphs
}

function getStoryAlertMessage(story: string) {
  const raw = story.trim()
  if (!raw) return null

  let message = raw
  try {
    const parsed = JSON.parse(raw) as { error?: { message?: string } | string; message?: string }
    if (typeof parsed.error === 'string') {
      message = parsed.error
    } else if (parsed.error && typeof parsed.error === 'object' && typeof parsed.error.message === 'string') {
      message = parsed.error.message
    } else if (typeof parsed.message === 'string') {
      message = parsed.message
    }
  } catch {
    // keep raw text
  }

  if (isTokenShortageMessage(message) || isTokenShortageMessage(raw)) {
    return TOKEN_SHORTAGE_TEXT
  }

  return null
}

interface StoryBodyProps {
  text: string
  words: Word[]
  translations: string[] | null
  translationVisible: boolean
  onSpeak: (text: string) => void
}

function StoryBody({ text, words, translations, translationVisible, onSpeak }: StoryBodyProps) {
  const paragraphs = parseStory(text, words)

  return (
    <>
      {paragraphs.map(({ sentences, paraIdx }) => (
        <div key={paraIdx}>
          <p className="mb-1 leading-relaxed text-[15px]" data-para-idx={paraIdx}>
            {sentences.map((sentence, si) => (
              <span
                key={si}
                className="sentence cursor-pointer rounded transition-colors hover:bg-[var(--highlight)]"
                onClick={(e) => {
                  if ((e.target as HTMLElement).dataset.word) return
                  onSpeak(sentence.text)
                }}
              >
                {sentence.spans.map((span, ki) =>
                  span.type === 'highlight' ? (
                    <span
                      key={ki}
                      className="highlight-word group relative cursor-pointer rounded bg-[var(--highlight)] px-0.5 font-semibold text-[var(--accent)]"
                      data-word={span.word}
                      onClick={(e) => {
                        e.stopPropagation()
                        onSpeak(span.word)
                      }}
                    >
                      {span.word}
                      {span.def && (
                        <span className="pointer-events-none absolute bottom-full left-1/2 z-50 mb-1 hidden -translate-x-1/2 whitespace-nowrap rounded bg-gray-800 px-2 py-1 text-xs text-white shadow-lg group-hover:block">
                          {span.def}
                        </span>
                      )}
                    </span>
                  ) : (
                    span.content
                  )
                )}
              </span>
            ))}
          </p>
          {translationVisible && translations?.[paraIdx] && (
            <div className="line-translation mb-3 border-l-2 border-[var(--border)] pl-2 text-[13px] italic text-[var(--text-light)]">
              {translations[paraIdx]}
            </div>
          )}
          {!translationVisible && <div className="mb-2" />}
        </div>
      ))}
    </>
  )
}

export default function LearnPage() {
  const [view, setView] = useState<'split' | 'words'>('split')
  const [listId, setListId] = useState<number | null>(null)
  const [day, setDay] = useState('')
  const [words, setWords] = useState<Word[]>([])
  const [story, setStory] = useState('')
  const [language, setLanguage] = useState('en')
  const [historyOptions, setHistoryOptions] = useState<Array<{ id: number; day_number: number }>>([])
  const [generating, setGenerating] = useState(false)
  const [markingDone, setMarkingDone] = useState(false)
  const [translations, setTranslations] = useState<string[] | null>(null)
  const [translationVisible, setTranslationVisible] = useState(false)
  const [translating, setTranslating] = useState(false)
  const [isReading, setIsReading] = useState(false)
  const [speechRate, setSpeechRate] = useState(1)
  const [historyListValue, setHistoryListValue] = useState('today')

  const audioRef = useRef<HTMLAudioElement | null>(null)
  const speechRateRef = useRef(1)
  const readState = useRef<{ chunks: string[]; idx: number; active: boolean; preloaded: HTMLAudioElement | null }>({
    chunks: [], idx: 0, active: false, preloaded: null,
  })
  const lastPopupRef = useRef<string>('')
  const languageRef = useRef('en')
  const storyAlertMessage = getStoryAlertMessage(story)

  useEffect(() => { speechRateRef.current = speechRate }, [speechRate])
  useEffect(() => { languageRef.current = language }, [language])
  useEffect(() => {
    if (!storyAlertMessage) return
    if (!isTokenShortageMessage(storyAlertMessage)) return
    if (lastPopupRef.current === storyAlertMessage) return
    lastPopupRef.current = storyAlertMessage
    toast.error(TOKEN_SHORTAGE_TEXT)
  }, [storyAlertMessage])

  const applyData = (data: Partial<LearnData>) => {
    setListId(typeof data.list_id === 'number' ? data.list_id : null)
    setDay(data.day_number ? `第 ${data.day_number} 天` : '暂无课程')
    setWords(Array.isArray(data.words) ? data.words : [])
    setStory(data.story || '')
    setLanguage(data.language || 'en')
    setTranslations(null)
    setTranslationVisible(false)
  }

  const loadToday = async () => {
    setHistoryListValue('today')
    const res = await apiFetch('/api/today')
    if (!res.ok) { applyData({}); return }
    const data = (await res.json()) as Partial<LearnData>
    if (data.finished) {
      setListId(null); setDay('全部学完！'); setWords([]); setStory('')
      return
    }
    applyData(data)
  }

  const refreshHistory = async () => {
    const res = await apiFetch('/api/lists/learned')
    if (res.ok) setHistoryOptions(await res.json())
  }

  useEffect(() => {
    loadToday()
    refreshHistory()
  }, [])

  const makeTtsUrl = (text: string) =>
    `/bff/api/tts?text=${encodeURIComponent(text)}&lang=${languageRef.current}`

  const speak = (text: string) => {
    if (audioRef.current) { audioRef.current.pause(); audioRef.current = null }
    const audio = new Audio(makeTtsUrl(text))
    audio.playbackRate = speechRateRef.current
    audio.play().catch(() => {})
    audioRef.current = audio
  }

  const generateStory = async () => {
    if (!listId || generating) return
    setGenerating(true)
    setStory('')
    setTranslations(null)
    setTranslationVisible(false)
    try {
      const res = await apiFetch(`/api/generate-story/${listId}`, { method: 'POST' })
      if (!res.ok || !res.body) {
        const message = await res.text().catch(() => '')
        notifyTokenShortage(message)
        setStory(message || `生成失败：${res.status}`)
        return
      }
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let accumulated = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''
        for (const line of lines) {
          if (!line.startsWith('data:')) continue
          const data = line.slice(5).trim()
          if (data === '[DONE]') return
          try {
            const parsed = JSON.parse(data)
            if (parsed.error) {
              notifyTokenShortage(String(parsed.error))
              setStory(parsed.error)
              return
            }
            if (parsed.chunk) { accumulated += parsed.chunk; setStory(accumulated) }
          } catch { /* ignore */ }
        }
      }
    } finally {
      setGenerating(false)
    }
  }

  const markDone = async () => {
    if (!listId || markingDone) return
    setMarkingDone(true)
    try {
      const res = await apiFetch(`/api/today/${listId}/done`, { method: 'POST' })
      if (!res.ok) return
      await loadToday()
      await refreshHistory()
    } finally {
      setMarkingDone(false)
    }
  }

  const toggleTranslation = async () => {
    if (translationVisible) { setTranslationVisible(false); return }
    // If translations exist and contain any non-empty line, just show them.
    if (translations && translations.some((t) => (t || '').trim() !== '')) { setTranslationVisible(true); return }

    const texts = story
      .split('\n')
      .map((l) => l.replace(/^#+\s*/, '').replace(/\*\*([^*]+)\*\*/g, '$1').trim())
      .filter(Boolean)
    if (!texts.length) return

    setTranslating(true)
    setTranslations(Array.from({ length: texts.length }, () => ''))
    try {
      const res = await apiFetch('/api/translate-lines/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ texts, source_lang: language }),
      })
      if (!res.ok) {
        const message = await res.text().catch(() => '')
        notifyTokenShortage(message)
        setTranslationVisible(false)
        return
      }

      if (!res.body) {
        setTranslationVisible(false)
        return
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let sseBuffer = ''
      let translationBuffer = ''
      let lastIndex = -1

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        sseBuffer += decoder.decode(value, { stream: true })
        const lines = sseBuffer.split('\n')
        sseBuffer = lines.pop() ?? ''

        for (const line of lines) {
          if (!line.startsWith('data:')) continue
          const data = line.slice(5).trim()
          if (data === '[DONE]') {
            if (translationBuffer.trim()) {
              setTranslations((prev) => {
                const next = prev ? [...prev] : Array.from({ length: texts.length }, () => '')
                lastIndex = applyTranslationLine(translationBuffer, next, lastIndex)
                return next
              })
              setTranslationVisible(true)
            }
            return
          }

          try {
            const parsed = JSON.parse(data) as { chunk?: string; error?: string }
            if (parsed.error) {
              notifyTokenShortage(String(parsed.error))
              setTranslationVisible(false)
              return
            }
            if (!parsed.chunk) continue

            translationBuffer += parsed.chunk
            const chunkLines = translationBuffer.split('\n')
            translationBuffer = chunkLines.pop() ?? ''

            if (!chunkLines.length) continue
            setTranslations((prev) => {
              const next = prev ? [...prev] : Array.from({ length: texts.length }, () => '')
              for (const chunkLine of chunkLines) {
                lastIndex = applyTranslationLine(chunkLine, next, lastIndex)
              }
              return next
            })
            setTranslationVisible(true)
          } catch {
            // ignore malformed SSE chunk
          }
        }
      }
    } catch (error) {
      notifyTokenShortage(String(error))
      setTranslationVisible(false)
    } finally {
      setTranslating(false)
    }
  }

  const preloadNext = (idx: number) => {
    const s = readState.current
    s.preloaded = idx < s.chunks.length ? new Audio(makeTtsUrl(s.chunks[idx])) : null
    if (s.preloaded) s.preloaded.preload = 'auto'
  }

  const playChunk = (idx: number) => {
    const s = readState.current
    if (!s.active || idx >= s.chunks.length) { s.active = false; setIsReading(false); return }
    s.idx = idx
    const audio = (s.preloaded && idx > 0) ? (s.preloaded) : new Audio(makeTtsUrl(s.chunks[idx]))
    s.preloaded = null
    audio.playbackRate = speechRateRef.current
    audio.onended = () => playChunk(idx + 1)
    audio.onerror = () => playChunk(idx + 1)
    audio.play().catch(() => playChunk(idx + 1))
    audioRef.current = audio
    preloadNext(idx + 1)
  }

  const readAloud = () => {
    stopReading()
    const chunks = story
      .split('\n')
      .map((l) => l.replace(/^#+\s*/, '').replace(/\*\*([^*]+)\*\*/g, '$1').trim())
      .filter(Boolean)
    if (!chunks.length) return
    const s = readState.current
    s.chunks = chunks; s.idx = 0; s.active = true
    setIsReading(true)
    playChunk(0)
  }

  const stopReading = () => {
    readState.current.active = false
    readState.current.chunks = []
    readState.current.preloaded = null
    if (audioRef.current) { audioRef.current.pause(); audioRef.current = null }
    setIsReading(false)
  }

  return (
    <AppShell>
      <div id="page-learn" className="page">
        {/* Header */}
        <div className="mb-4 flex items-center justify-between">
          <h2 className="mb-0 text-xl font-semibold">
            今日学习
            {day && <span className="ml-2 text-base font-normal text-[var(--text-light)]">· {day}</span>}
          </h2>
          <div className="flex items-center gap-2">
            <Tabs value={view} onValueChange={(v) => setView(v as 'split' | 'words')}>
              <TabsList>
                <TabsTrigger value="split">左右视图</TabsTrigger>
                <TabsTrigger value="words">单词优先</TabsTrigger>
              </TabsList>
            </Tabs>
            <Select
              value={historyListValue}
              onValueChange={async (value) => {
                setHistoryListValue(value)
                if (value === 'today') return loadToday()
                const res = await apiFetch(`/api/lists/${value}`)
                if (!res.ok) return
                applyData(await res.json())
              }}
            >
              <SelectTrigger className="h-8 w-[136px] text-[13px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value="today">今日课程</SelectItem>
                  {historyOptions.map((o) => (
                    <SelectItem key={o.id} value={String(o.id)}>第 {o.day_number} 天</SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </div>
        </div>

        {/* Main layout */}
        <div className={`learn-layout ${view === 'words' ? 'words-view' : ''}`}>
          {/* Story card */}
          <Card id="story-card">
            <CardContent className="p-6">
              <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-base font-semibold">课文</h3>
                <div className="flex flex-wrap items-center gap-2">
                  {story && (
                    <>
                      <Button
                        size="sm"
                        variant={translationVisible ? 'default' : 'outline'}
                        onClick={toggleTranslation}
                        disabled={translating}
                        className="gap-1 text-xs"
                      >
                        {translating ? <Loader2 className="h-3 w-3 animate-spin" /> : ''}
                        {translating ? '翻译中…' : translationVisible ? '隐藏翻译' : '显示翻译'}
                      </Button>
                      {isReading ? (
                        <Button size="sm" variant="outline" onClick={stopReading} className="gap-1 text-xs">
                          <Square className="h-3 w-3" /> 停止
                        </Button>
                      ) : (
                        <Button size="sm" variant="outline" onClick={readAloud} className="gap-1 text-xs">
                          <Volume2 className="h-3 w-3" /> 朗读全文
                        </Button>
                      )}
                      <div className="flex items-center gap-1 text-xs text-[var(--text-light)]">
                        <span>速度</span>
                        <Slider
                          min={0.5}
                          max={2}
                          step={0.1}
                          value={[speechRate]}
                          onValueChange={(value) => setSpeechRate(value[0] ?? 1)}
                          className="w-20"
                        />
                        <span className="w-6 text-right">{speechRate.toFixed(1)}x</span>
                      </div>
                    </>
                  )}
                  {listId && (
                    <Button
                      size="sm"
                      variant={story ? 'outline' : 'default'}
                      onClick={generateStory}
                      disabled={generating}
                      className="gap-1.5 text-xs"
                    >
                      {generating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                      {generating ? '生成中…' : story ? '重新生成' : '生成课文'}
                    </Button>
                  )}
                </div>
              </div>

              {storyAlertMessage ? (
                <Alert variant="destructive" className="mb-4">
                  <AlertTitle>生成失败</AlertTitle>
                  <AlertDescription>{storyAlertMessage}</AlertDescription>
                </Alert>
              ) : story ? (
                <div className="text-[var(--text)]">
                  <StoryBody
                    text={story}
                    words={words}
                    translations={translations}
                    translationVisible={translationVisible}
                    onSpeak={speak}
                  />
                </div>
              ) : (
                <div className="flex h-44 flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-[var(--border)]">
                  <Sparkles className="h-8 w-8 text-[var(--border)]" />
                  <p className="text-sm text-[var(--text-light)]">
                    {listId ? '点击"生成课文"让 AI 编写包含本日单词的短文' : '暂无课程内容'}
                  </p>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Word list card */}
          <Card id="word-list-card">
            <CardContent className="p-6">
              <h3 className="mb-1 text-base font-semibold">
                单词
                {words.length > 0 && (
                  <span className="ml-1.5 text-sm font-normal text-[var(--text-light)]">{words.length} 个</span>
                )}
              </h3>
              <div id="word-list" className="divide-y divide-[var(--highlight)]">
                {words.map((w) => (
                  <div key={w.word} className="flex items-start gap-3 py-3">
                    <Button
                      onClick={() => speak(w.word)}
                      size="sm"
                      variant="outline"
                      className="mt-0.5 h-7 w-7 shrink-0 p-0 text-[var(--text-light)]"
                      title="朗读"
                    >
                      <Volume2 className="h-4 w-4" />
                    </Button>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-baseline gap-x-2">
                        <span className="text-[15px] font-semibold">{w.word}</span>
                        {w.phonetic && (
                          <span className="text-xs text-[var(--text-light)]">{w.phonetic}</span>
                        )}
                      </div>
                      <p className="mt-0.5 text-sm leading-snug text-[#666]">{w.definition}</p>
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Done button */}
        {listId && (
          <Button
            className="mt-4 w-full gap-2 text-base"
            onClick={markDone}
            disabled={markingDone}
          >
            {markingDone ? <Loader2 className="h-5 w-5 animate-spin" /> : <CheckCircle2 className="h-5 w-5" />}
            学完了，下一课
          </Button>
        )}
      </div>
    </AppShell>
  )
}
