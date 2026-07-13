'use client'

import { useEffect, useMemo, useState } from 'react'
import { Clipboard, ImageIcon, Loader2, RefreshCcw, Search, WandSparkles, X } from 'lucide-react'

import { AppShell } from '@/app/_components/app-shell'
import { apiFetch } from '@/app/_lib/api'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'

type Option = { value: string; label: string }
type Wordbook = { id: number; name: string; language: string; word_count?: number }
type MatchedWord = {
  id?: number
  word: string
  definition: string
  company_context?: string
  score?: number
  match_reasons?: string[]
}
type CompanyProfile = {
  company_name?: string
  source_summary?: string
  logo_url?: string
  industries?: string[]
  products?: string[]
  brands?: string[]
  milestones?: string[]
  source_warnings?: string[]
}
type Note = {
  id?: number
  selected_title: string
  titles: string[]
  body: string
  vocabulary: Array<{ word: string; definition: string; usage?: string }>
  cover_text: string
  visual_header?: { logo_url?: string; industry_info?: string; company_meta?: string[] }
  image_prompt: string
  hashtags: string[]
  cta: string
  risk_flags: string[]
  fact_check_notes?: string[]
}
type RenderedCard = { kind: string; image_url: string; image_path?: string; title?: string }
type OptionsPayload = {
  wordbooks: Wordbook[]
  styles: Option[]
  company_angles: Option[]
  defaults: { note_count: number; words_per_note: number }
}

function wordbookCountLabel(wordbook: Wordbook) {
  if (typeof wordbook.word_count !== 'number') return ''
  if (wordbook.word_count <= 0) return '未导入'
  return `${wordbook.word_count.toLocaleString('zh-CN')}词`
}

function boundedNumber(value: string, fallback: number, min: number, max: number) {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return fallback
  return Math.min(max, Math.max(min, Math.trunc(parsed)))
}

async function readJsonError(response: Response, fallback: string) {
  const payload = await response.json().catch(() => null)
  if (response.status === 401) return '未登录或登录已过期，请重新登录后再打开后台。'
  if (response.status === 403) return payload?.detail || payload?.error || '当前账号没有后台权限。'
  return payload?.detail || payload?.error || fallback
}

export default function XiaohongshuCompanyFactoryPage() {
  return (
    <AppShell>
      <XiaohongshuCompanyFactoryContent />
    </AppShell>
  )
}

function XiaohongshuCompanyFactoryContent() {
  const [options, setOptions] = useState<OptionsPayload | null>(null)
  const [wordbookId, setWordbookId] = useState('')
  const [companyName, setCompanyName] = useState('NVIDIA')
  const [companyTicker, setCompanyTicker] = useState('NVDA')
  const [companyLogoUrl, setCompanyLogoUrl] = useState('')
  const [companyProfileText, setCompanyProfileText] = useState('')
  const [angle, setAngle] = useState('technology_product')
  const [style, setStyle] = useState('story')
  const [noteCount, setNoteCount] = useState(1)
  const [wordsPerNote, setWordsPerNote] = useState(6)
  const [companyProfile, setCompanyProfile] = useState<CompanyProfile | null>(null)
  const [matchedVocabulary, setMatchedVocabulary] = useState<MatchedWord[]>([])
  const [matchedVocabularyKey, setMatchedVocabularyKey] = useState('')
  const [notes, setNotes] = useState<Note[]>([])
  const [renderedCards, setRenderedCards] = useState<Record<number, RenderedCard[]>>({})
  const [loading, setLoading] = useState('')
  const [progressMessage, setProgressMessage] = useState('')
  const [error, setError] = useState('')

  const selectedWordbook = useMemo(
    () => options?.wordbooks.find((wordbook) => String(wordbook.id) === wordbookId),
    [options?.wordbooks, wordbookId]
  )
  const currentVocabularyKey = useMemo(
    () =>
      JSON.stringify({
        wordbookId,
        companyName: companyName.trim(),
        companyTicker: companyTicker.trim(),
        companyLogoUrl: companyLogoUrl.trim(),
        companyProfileText: companyProfileText.trim(),
        angle,
        noteCount,
        wordsPerNote,
      }),
    [wordbookId, companyName, companyTicker, companyLogoUrl, companyProfileText, angle, noteCount, wordsPerNote]
  )

  useEffect(() => {
    void loadOptions()
  }, [])

  useEffect(() => {
    setMatchedVocabulary([])
    setMatchedVocabularyKey('')
    setCompanyProfile(null)
  }, [currentVocabularyKey])

  async function loadOptions() {
    setError('')
    setLoading('options')
    setProgressMessage('正在加载英文词书列表...')
    try {
      const response = await apiFetch('/api/admin/xhs/options', { redirect: 'manual' })
      if (!response.ok) {
        setError(await readJsonError(response, '加载词书失败'))
        return
      }
      const payload = (await response.json()) as OptionsPayload
      setOptions(payload)
      const defaultWordbook =
        payload.wordbooks.find((wordbook) => wordbook.language === 'en' && (wordbook.word_count || 0) > 0) ||
        payload.wordbooks.find((wordbook) => wordbook.language === 'en' && wordbook.name.includes('3000')) ||
        payload.wordbooks.find((wordbook) => wordbook.language === 'en') ||
        payload.wordbooks[0]
      if (defaultWordbook) setWordbookId(String(defaultWordbook.id))
      setNoteCount(payload.defaults?.note_count || 1)
      setWordsPerNote(payload.defaults?.words_per_note || 6)
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载词书失败')
    } finally {
      setLoading('')
      setProgressMessage('')
    }
  }

  async function previewCompany() {
    if (!wordbookId) return
    setLoading('preview')
    setProgressMessage('正在准备词书并匹配公司相关英文词。首次使用空词书会自动导入，可能需要几十秒。')
    setError('')
    try {
      const response = await apiFetch('/api/admin/xhs/company-preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          wordbook_id: Number(wordbookId),
          company_name: companyName,
          company_ticker: companyTicker,
          company_logo_url: companyLogoUrl,
          company_source_language: 'zh',
          manual_company_profile: companyProfileText,
          angle,
          note_count: noteCount,
          words_per_note: wordsPerNote,
        }),
        redirect: 'manual',
      })
      if (!response.ok) throw new Error(await readJsonError(response, '公司资料/词汇预览失败'))
      const payload = (await response.json()) as { company_profile: CompanyProfile; matched_vocabulary: MatchedWord[] }
      setCompanyProfile(payload.company_profile)
      setMatchedVocabulary(payload.matched_vocabulary)
      setMatchedVocabularyKey(currentVocabularyKey)
      setProgressMessage(
        payload.matched_vocabulary.length
          ? `已匹配 ${payload.matched_vocabulary.length} 个英文词，可以继续生成 ${noteCount} 篇图文。`
          : '没有匹配到英文词，请换一个词书或补充公司资料。'
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : '公司资料/词汇预览失败')
      setProgressMessage('')
    } finally {
      setLoading('')
    }
  }

  async function generateNotes() {
    if (!wordbookId) return
    setLoading('generate')
    setProgressMessage(`正在生成 ${noteCount} 篇中文图文，AI 生成通常需要 20-60 秒。`)
    setError('')
    try {
      const vocabulary = matchedVocabulary.length && matchedVocabularyKey === currentVocabularyKey ? matchedVocabulary : undefined
      const response = await apiFetch('/api/admin/xhs/batches', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mode: 'company_profile',
          wordbook_id: Number(wordbookId),
          scene: 'company_profile',
          topic: companyName,
          style,
          note_count: noteCount,
          words_per_note: wordsPerNote,
          company_name: companyName,
          company_ticker: companyTicker,
          company_logo_url: companyLogoUrl,
          company_source_language: 'zh',
          manual_company_profile: companyProfileText,
          angle,
          matched_vocabulary: vocabulary,
        }),
        redirect: 'manual',
      })
      if (!response.ok) throw new Error(await readJsonError(response, '公司图文生成失败'))
      const payload = (await response.json()) as {
        batch: { company_profile?: CompanyProfile; matched_vocabulary?: MatchedWord[] }
        notes: Note[]
      }
      setCompanyProfile(payload.batch.company_profile || null)
      setMatchedVocabulary(payload.batch.matched_vocabulary || [])
      setNotes(payload.notes)
      setRenderedCards({})
      setProgressMessage(`已生成 ${payload.notes.length} 篇图文。`)
    } catch (err) {
      setError(err instanceof Error ? err.message : '公司图文生成失败')
      setProgressMessage('')
    } finally {
      setLoading('')
    }
  }

  function removeMatchedWord(word: string) {
    setMatchedVocabulary((items) => items.filter((item) => item.word !== word))
  }

  async function renderNoteImages(note: Note) {
    if (!note.id) return
    setLoading(`render-${note.id}`)
    setError('')
    try {
      const response = await apiFetch(`/api/admin/xhs/notes/${note.id}/image-cards/rendered`, {
        method: 'POST',
        redirect: 'manual',
      })
      if (!response.ok) throw new Error(await readJsonError(response, '图片生成失败'))
      const payload = (await response.json()) as { cards: RenderedCard[] }
      setRenderedCards((current) => ({ ...current, [note.id as number]: payload.cards }))
    } catch (err) {
      setError(err instanceof Error ? err.message : '图片生成失败')
    } finally {
      setLoading('')
    }
  }

  return (
    <div className="page space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-sm font-semibold uppercase text-[var(--accent)]">Manual publishing only</p>
            <h2 className="mb-1 flex items-center gap-2 text-3xl font-black">
              <WandSparkles className="size-7" />
              小红书公司/产品图文生成
            </h2>
            <p className="text-sm text-[var(--text-light)]">
              客观介绍公司或产品，在中文正文里用“中文（English）”自然标注雅思、托福、GRE 等英文词汇。
            </p>
          </div>
          <Button variant="outline" onClick={loadOptions} className="gap-2">
            {loading === 'options' ? <Loader2 className="size-4 animate-spin" /> : <RefreshCcw className="size-4" />}
            {loading === 'options' ? '加载中' : '刷新词书'}
          </Button>
        </div>

        {error ? <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div> : null}
        {progressMessage ? (
          <div className="rounded border border-blue-200 bg-blue-50 p-3 text-sm text-blue-800">
            {progressMessage}
          </div>
        ) : null}

        <div className="grid gap-4 xl:grid-cols-[430px_1fr]">
          <div className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle className="text-lg">生成设置</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <label className="space-y-1 text-sm font-semibold">
                  <span>英文词书</span>
                  <Select value={wordbookId} onValueChange={setWordbookId}>
                    <SelectTrigger><SelectValue placeholder="选择 GRE / IELTS / TOEFL / CET 词书" /></SelectTrigger>
                    <SelectContent>
                      {options?.wordbooks.map((wordbook) => (
                        <SelectItem key={wordbook.id} value={String(wordbook.id)}>
                          {wordbook.name} · {wordbook.language}
                          {wordbookCountLabel(wordbook) ? ` · ${wordbookCountLabel(wordbook)}` : ''}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </label>

                <div className="grid grid-cols-[1fr_110px] gap-2">
                  <label className="space-y-1 text-sm font-semibold">
                    <span>公司/产品</span>
                    <Input value={companyName} onChange={(event) => setCompanyName(event.target.value)} />
                  </label>
                  <label className="space-y-1 text-sm font-semibold">
                    <span>Ticker</span>
                    <Input value={companyTicker} onChange={(event) => setCompanyTicker(event.target.value)} />
                  </label>
                </div>

                <label className="space-y-1 text-sm font-semibold">
                  <span>Logo URL</span>
                  <Input value={companyLogoUrl} onChange={(event) => setCompanyLogoUrl(event.target.value)} placeholder="可选：https://..." />
                </label>

                <label className="space-y-1 text-sm font-semibold">
                  <span>补充资料（可选）</span>
                  <Textarea
                    className="min-h-[130px]"
                    value={companyProfileText}
                    onChange={(event) => setCompanyProfileText(event.target.value)}
                    placeholder="系统会按公司/产品名和 Ticker 自动获取客观资料；这里可补充官网信息、产品重点或需要强调的角度。"
                  />
                </label>

                <div className="grid grid-cols-2 gap-2">
                  <label className="space-y-1 text-sm font-semibold">
                    <span>角度</span>
                    <Select value={angle} onValueChange={setAngle}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {options?.company_angles.map((item) => (
                          <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </label>
                  <label className="space-y-1 text-sm font-semibold">
                    <span>风格</span>
                    <Select value={style} onValueChange={setStyle}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {options?.styles.map((item) => (
                          <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </label>
                </div>

                <div className="grid grid-cols-2 gap-2">
                  <label className="space-y-1 text-sm font-semibold">
                    <span>篇数</span>
                    <Input type="number" min={1} max={20} value={noteCount} onChange={(event) => setNoteCount(boundedNumber(event.target.value, noteCount, 1, 20))} />
                  </label>
                  <label className="space-y-1 text-sm font-semibold">
                    <span>每篇词数</span>
                    <Input type="number" min={1} max={20} value={wordsPerNote} onChange={(event) => setWordsPerNote(boundedNumber(event.target.value, wordsPerNote, 1, 20))} />
                  </label>
                </div>

                <div className="rounded-md bg-[var(--highlight)] p-3 text-xs leading-5 text-[var(--text-light)]">
                  当前词书：{selectedWordbook ? `${selectedWordbook.name} · ${selectedWordbook.language} · ${wordbookCountLabel(selectedWordbook)}` : '未选择'}。
                  {selectedWordbook && selectedWordbook.word_count === 0 ? ' 首次预览会自动导入词汇，可能需要几十秒。' : ' '}
                  正文格式固定为中文在前、英文在括号里，例如：基础设施（infrastructure）。
                </div>

                <div className="grid grid-cols-2 gap-2">
                  <Button variant="outline" onClick={previewCompany} disabled={!!loading || !wordbookId} className="gap-2">
                    {loading === 'preview' ? <Loader2 className="size-4 animate-spin" /> : <Search className="size-4" />}
                    {loading === 'preview' ? '匹配中' : '预览词汇'}
                  </Button>
                  <Button onClick={generateNotes} disabled={!!loading || !wordbookId || !companyName.trim()} className="gap-2">
                    {loading === 'generate' ? <Loader2 className="size-4 animate-spin" /> : <WandSparkles className="size-4" />}
                    {loading === 'generate' ? '生成中' : '生成图文'}
                  </Button>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-lg">匹配词汇</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {matchedVocabulary.length ? matchedVocabulary.map((item) => (
                  <div key={item.word} className="rounded-md border border-[var(--border)] p-3">
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <div className="font-black">{item.word}</div>
                        <div className="text-xs leading-5 text-[var(--text-light)]">{item.definition}</div>
                      </div>
                      <Button variant="ghost" size="icon" onClick={() => removeMatchedWord(item.word)} aria-label="remove word">
                        <X className="size-4" />
                      </Button>
                    </div>
                  </div>
                )) : (
                  <div className="rounded-md border border-dashed border-[var(--border)] p-6 text-center text-sm text-[var(--text-light)]">
                    先点击“预览词汇”。
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          <div className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle className="text-lg">资料卡头部</CardTitle>
              </CardHeader>
              <CardContent>
                {companyProfile ? (
                  <div className="flex items-start gap-3 rounded-md bg-[var(--highlight)] p-4">
                    {companyProfile.logo_url ? <img src={companyProfile.logo_url} alt="" className="h-12 w-12 rounded border bg-white object-contain" /> : null}
                    <div>
                      <div className="font-black">{companyProfile.company_name}</div>
                      <div className="text-xs text-[var(--text-light)]">
                        {(companyProfile.industries || []).join(' · ') || selectedWordbook?.name || '行业信息可在资料里补充'}
                      </div>
                      <p className="mt-2 text-sm leading-6 text-[var(--text-light)]">{companyProfile.source_summary}</p>
                    </div>
                  </div>
                ) : (
                  <div className="rounded-md border border-dashed border-[var(--border)] p-6 text-center text-sm text-[var(--text-light)]">
                    预览后展示 Logo、行业和公司资料。
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-lg">生成结果</CardTitle>
              </CardHeader>
              <CardContent>
                {notes.length ? (
                  <div className="space-y-4">
                    {notes.map((note, index) => (
                      <div key={`${note.selected_title}-${index}`} className="rounded-md border border-[var(--border)] p-4">
                        <div className="flex flex-wrap items-start justify-between gap-2">
                          <div>
                            <div className="text-xs font-semibold uppercase text-[var(--accent)]">图文 {index + 1}</div>
                            <h3 className="mt-1 text-xl font-black">{note.selected_title}</h3>
                          </div>
                          <div className="flex flex-wrap gap-2">
                            <Button variant="outline" size="sm" onClick={() => renderNoteImages(note)} disabled={!note.id || loading === `render-${note.id}`}>
                              {loading === `render-${note.id}` ? <Loader2 className="size-4 animate-spin" /> : <ImageIcon className="size-4" />}
                              生成图片
                            </Button>
                            <Button variant="outline" size="sm" onClick={() => navigator.clipboard.writeText([note.selected_title, '', note.body, '', note.hashtags.join(' ')].join('\n'))}>
                              <Clipboard className="size-4" />
                              复制
                            </Button>
                          </div>
                        </div>
                        <p className="mt-3 whitespace-pre-wrap text-sm leading-7">{note.body}</p>
                        <div className="mt-3 flex flex-wrap gap-2">
                          {note.vocabulary.map((item) => (
                            <span key={item.word} className="rounded bg-[var(--highlight)] px-2 py-1 text-xs">
                              {item.definition}（{item.word}）
                            </span>
                          ))}
                        </div>
                        {note.risk_flags?.length ? <div className="mt-3 text-xs text-red-700">风险：{note.risk_flags.join(' / ')}</div> : null}
                        {note.id && renderedCards[note.id]?.length ? (
                          <div className="mt-4 grid gap-3 sm:grid-cols-3">
                            {renderedCards[note.id].map((card) => (
                              <a key={card.image_url} href={card.image_url} target="_blank" rel="noreferrer" className="block rounded border border-[var(--border)] bg-white p-2">
                                <img src={card.image_url} alt={card.title || card.kind} className="aspect-[3/4] w-full rounded object-cover" />
                                <div className="mt-1 text-xs text-[var(--text-light)]">{card.kind}</div>
                              </a>
                            ))}
                          </div>
                        ) : null}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="rounded-md border border-dashed border-[var(--border)] p-10 text-center text-sm text-[var(--text-light)]">
                    生成后这里会显示中文公司介绍正文和英文词汇括注。
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
    </div>
  )
}
