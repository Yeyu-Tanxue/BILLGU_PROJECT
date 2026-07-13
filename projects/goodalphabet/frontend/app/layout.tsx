import type { Metadata } from 'next'
import { ThemeBoot } from '@/app/_components/theme-boot'
import { Toaster } from '@/components/ui/sonner'
import './globals.css'

export const metadata: Metadata = {
  title: 'Gu 的辞書',
  description: 'A modernized learning app.',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <head>
        <link href="https://fonts.googleapis.com/css2?family=Noto+Serif:wght@700&display=swap" rel="stylesheet" />
      </head>
      <body suppressHydrationWarning>
        <ThemeBoot />
        {children}
        <Toaster />
      </body>
    </html>
  )
}
