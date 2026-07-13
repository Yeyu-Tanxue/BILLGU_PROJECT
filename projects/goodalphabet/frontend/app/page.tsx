import { auth0 } from '@/lib/auth0'
import { redirect } from 'next/navigation'

export default async function HomePage() {
  const session = await auth0.getSession()

  if (session?.user) {
    redirect('/setup')
  }

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-3xl items-center px-4 py-10">
      <div className="w-full rounded-xl border bg-card p-6 shadow-sm">
        <h1 className="text-2xl font-semibold">Gu 的辞書</h1>
        <p className="mt-2 text-sm text-muted-foreground">登录后可创建计划、生成课文、逐句翻译、安排复习并追踪学习进度。</p>

        <ul className="mt-4 list-disc space-y-1 pl-5 text-sm text-[var(--text-light)]">
          <li>智能生成每天课文，支持关键词高亮与朗读</li>
          <li>逐句翻译支持流式显示，并可自动保存翻译结果</li>
          <li>按间隔重复安排复习，提供翻译/填空/造句练习</li>
          <li>查看日历与进度面板，清楚掌握学习节奏</li>
        </ul>

        <div className="mt-6">
          <a
            href="/auth/login"
            className="inline-flex items-center rounded-md border border-[var(--nav)] bg-[var(--nav)] px-4 py-2 text-sm font-medium text-white shadow-sm hover:opacity-90"
          >
            立即登录开始学习
          </a>
        </div>
      </div>
    </main>
  )
}
