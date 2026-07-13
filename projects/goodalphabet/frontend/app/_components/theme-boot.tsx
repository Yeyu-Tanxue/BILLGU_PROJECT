'use client'

import { useEffect } from 'react'

const MORANDI_THEMES = [
  { bg: '#f1f0ed', nav: '#7b8895', primary: '#7b8895', primaryHover: '#6a7882', card: '#faf9f7', border: '#d9d4ce', highlight: '#e4e0db', accent: '#c2a0a0', accentHover: '#b08e8e', tagSelected: '#8e9daa', warm: '#d4b5a0' },
  { bg: '#f3efed', nav: '#b59d97', primary: '#b59d97', primaryHover: '#a48c86', card: '#faf8f7', border: '#dbd5d0', highlight: '#e8dfdb', accent: '#8a9caa', accentHover: '#7a8c9a', tagSelected: '#ae9590', warm: '#a8b5a2' },
  { bg: '#eff2ef', nav: '#889d8d', primary: '#889d8d', primaryHover: '#788f7e', card: '#f8faf8', border: '#d2d9d3', highlight: '#dfe5e0', accent: '#a898b0', accentHover: '#9888a0', tagSelected: '#8da496', warm: '#c4aeaa' },
  { bg: '#f0eff2', nav: '#988ca2', primary: '#988ca2', primaryHover: '#877b90', card: '#f9f8fa', border: '#d6d1db', highlight: '#e2dde7', accent: '#8ea396', accentHover: '#7e9386', tagSelected: '#9a8fa4', warm: '#c4b5a0' },
  { bg: '#f2f0ec', nav: '#a49686', primary: '#a49686', primaryHover: '#938576', card: '#faf8f5', border: '#dbd5cd', highlight: '#e5dfd7', accent: '#8a9daa', accentHover: '#7a8d9a', tagSelected: '#a69a8e', warm: '#b8a0a0' },
  { bg: '#f2eeef', nav: '#ad9199', primary: '#ad9199', primaryHover: '#9c8088', card: '#faf8f8', border: '#dbd4d6', highlight: '#e6dfe1', accent: '#8f9e82', accentHover: '#7f8e72', tagSelected: '#a68d94', warm: '#c8b8a0' },
  { bg: '#eef1f0', nav: '#7e9a98', primary: '#7e9a98', primaryHover: '#6e8a88', card: '#f8faf9', border: '#d0d8d6', highlight: '#dde4e2', accent: '#b89a8a', accentHover: '#a8897a', tagSelected: '#88a5a2', warm: '#c4a8b0' },
]

export function ThemeBoot() {
  const toHslTuple = (hex: string) => {
    const clean = hex.replace('#', '')
    const full = clean.length === 3 ? clean.split('').map((ch) => ch + ch).join('') : clean
    const r = parseInt(full.slice(0, 2), 16) / 255
    const g = parseInt(full.slice(2, 4), 16) / 255
    const b = parseInt(full.slice(4, 6), 16) / 255

    const max = Math.max(r, g, b)
    const min = Math.min(r, g, b)
    let h = 0
    let s = 0
    const l = (max + min) / 2

    if (max !== min) {
      const d = max - min
      s = l > 0.5 ? d / (2 - max - min) : d / (max + min)
      switch (max) {
        case r:
          h = (g - b) / d + (g < b ? 6 : 0)
          break
        case g:
          h = (b - r) / d + 2
          break
        default:
          h = (r - g) / d + 4
      }
      h /= 6
    }

    return `${Math.round(h * 360)} ${Math.round(s * 100)}% ${Math.round(l * 100)}%`
  }

  useEffect(() => {
    const selected = MORANDI_THEMES[Math.floor(Math.random() * MORANDI_THEMES.length)]
    const style = document.documentElement.style
    style.setProperty('--bg', selected.bg)
    style.setProperty('--nav', selected.nav)
    style.setProperty('--highlight', selected.highlight)
    style.setProperty('--primary-hover', selected.primaryHover)
    style.setProperty('--accent-hover', selected.accentHover)
    style.setProperty('--tag-selected', selected.tagSelected)
    style.setProperty('--warm', selected.warm)

    // Keep shadcn tokens in HSL tuple format so classes like bg-primary remain valid.
    style.setProperty('--primary', toHslTuple(selected.primary))
    style.setProperty('--card', toHslTuple(selected.card))
    style.setProperty('--border', toHslTuple(selected.border))
    style.setProperty('--accent', toHslTuple(selected.accent))
    style.setProperty('--ring', toHslTuple(selected.primary))
  }, [])

  return null
}
