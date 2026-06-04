import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * Coerce a value to a Date instance.
 *
 * The bridge API stores timestamps as REAL (unix seconds, with
 * fractional milliseconds) in SQLite and returns them as JSON
 * numbers — NOT ISO strings. Before V2 #6.3, utils.ts assumed
 * `string | Date` only, so the dashboard's 'lastSeen' / 'startedAt'
 * fields crashed the Devices / Conversations pages with
 * "t.getTime is not a function" as soon as any list item was
 * rendered. This helper handles all four shapes a backend
 * could reasonably return:
 *
 *   - Date instance: returned as-is
 *   - number: treated as unix SECONDS (matches the API; we multiply
 *     by 1000 because JS Date wants milliseconds)
 *   - string: parsed by the Date constructor (accepts ISO 8601,
 *     and many other human formats)
 *   - null/undefined: returns a sentinel "epoch" Date so downstream
 *     code doesn't crash; formatRelative will then show "很久以前"
 */
function toDate(d: Date | number | string | null | undefined): Date {
  if (d instanceof Date) return d
  if (typeof d === 'number') return new Date(d * 1000)
  if (typeof d === 'string') return new Date(d)
  return new Date(0)
}

export function formatDate(date: Date | number | string | null | undefined): string {
  const d = toDate(date)
  return d.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

export function formatRelative(date: Date | number | string | null | undefined): string {
  const d = toDate(date)
  const now = Date.now()
  const diff = (now - d.getTime()) / 1000
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`
  return `${Math.floor(diff / 86400)} 天前`
}
