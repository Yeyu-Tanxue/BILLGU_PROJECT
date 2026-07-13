import { auth0 } from '@/lib/auth0'
import { redirect } from 'next/navigation'

export default async function LoginPage() {
  const session = await auth0.getSession()

  if (session?.user) {
    redirect('/setup')
  }

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-md items-center px-4 py-10">
      <div className="w-full rounded-xl border bg-card p-6 shadow-sm">
        <h1 className="text-2xl font-semibold">登录</h1>
        <p className="mt-2 text-sm text-muted-foreground">请使用 Auth0 登录。登录成功后会进入设置页创建计划。</p>
        <p className="mt-2 text-xs text-[var(--text-light)]">功能包含：每日课文生成、流式翻译、复习练习、进度统计。</p>
        <div className="mt-6">
          <a
            href="/auth/login"
            className="inline-flex items-center rounded-md border border-[var(--nav)] bg-[var(--nav)] px-4 py-2 text-sm font-medium text-white shadow-sm hover:opacity-90"
          >
            使用账号登录
          </a>
        </div>
      </div>
    </main>
  )
}
