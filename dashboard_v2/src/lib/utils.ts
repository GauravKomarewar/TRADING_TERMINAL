import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function toNumber(value: number | string | null | undefined, fallback = 0): number {
  const n = typeof value === 'string' ? parseFloat(value) : value
  return n == null || Number.isNaN(n) ? fallback : n
}

export function formatINR(value: number | string | null | undefined): string {
  const n = typeof value === 'string' ? parseFloat(value) : value
  if (n == null || Number.isNaN(n)) return '—'
  return n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

export function formatNum(value: number | string | null | undefined, decimals = 2): string {
  const n = typeof value === 'string' ? parseFloat(value) : value
  if (n == null || Number.isNaN(n)) return '—'
  return n.toFixed(decimals)
}

export function pnlClass(value: number | string | null | undefined): string {
  const n = typeof value === 'string' ? parseFloat(value) : value
  if (n == null || Number.isNaN(n) || n === 0) return 'pnl-zero'
  return n > 0 ? 'pnl-positive' : 'pnl-negative'
}

export function pnlSign(value: number): string {
  if (value > 0) return '+' + formatINR(value)
  return formatINR(value)
}

export function timeAgo(ts: string | number | null): string {
  if (!ts) return '—'
  const d = typeof ts === 'number' ? ts * 1000 : new Date(ts).getTime()
  const diff = Math.floor((Date.now() - d) / 1000)
  if (diff < 5) return 'just now'
  if (diff < 60) return diff + 's ago'
  if (diff < 3600) return Math.floor(diff / 60) + 'm ago'
  return Math.floor(diff / 3600) + 'h ago'
}

export function encodeAttr(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/</g, '&lt;')
}

export function sleep(ms: number): Promise<void> {
  return new Promise(r => setTimeout(r, ms))
}

export function slugify(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
}

export function appBasePath(): string {
  const base = import.meta.env.BASE_URL || '/'
  if (base === '/') return ''
  return base.endsWith('/') ? base.slice(0, -1) : base
}

export function appRoute(path = ''): string {
  const base = appBasePath()
  if (!path) return base || '/'
  const normalized = path.startsWith('/') ? path : `/${path}`
  return `${base}${normalized}` || normalized
}
