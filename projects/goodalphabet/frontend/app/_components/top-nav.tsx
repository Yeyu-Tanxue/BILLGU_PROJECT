'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'

import { Button } from '@/components/ui/button'

const navs = [
  { key: 'setup', label: '设置', href: '/setup' },
  { key: 'learn', label: '今日学习', href: '/learn' },
  { key: 'review', label: '复习', href: '/review' },
  { key: 'calendar', label: '日历', href: '/calendar' },
  { key: 'progress', label: '进度', href: '/progress' },
  { key: 'billing', label: '会员', href: '/billing' },
  { key: 'admin', label: '后台', href: '/admin' },
  { key: 'xhs', label: '小红书', href: '/admin/xhs' },
]

export function TopNav({ username, accessLabel, isAdmin = false }: { username: string; accessLabel?: string; isAdmin?: boolean }) {
  const pathname = usePathname()
  const visibleNavs = navs.filter((nav) => isAdmin || (nav.key !== 'admin' && nav.key !== 'xhs'))

  return (
    <nav className="top-nav">
      <div className="nav-brand">
        <span className="brand-name">Gu的辞書</span>
        <span className="brand-sub">Good Lexicon</span>
      </div>
      <div className="nav-links">
        {visibleNavs.map((nav) => (
          <Link key={nav.key} href={nav.href} className={pathname === nav.href ? 'active' : ''}>
            {nav.label}
          </Link>
        ))}
      </div>
      <div className="nav-user">
        <span>{username}</span>
        {accessLabel ? <span className="ml-2 text-xs text-white/70">{accessLabel}</span> : null}
        <Button asChild size="sm" variant="outline" className="ml-2">
          <Link href="/billing">购买会员</Link>
        </Button>
        <Button
          size="sm"
          variant="secondary"
          className="ml-2"
          onClick={() => {
            window.location.href = '/auth/logout'
          }}
        >
          退出
        </Button>
      </div>
    </nav>
  )
}
