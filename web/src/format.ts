// Small display-formatting helpers shared across components.

/** Format an hour count with thousands separators, e.g. 67031.1 → "67,031 h". */
export function fmtHours(hours: number): string {
  if (hours <= 0) return '—'
  return `${Math.round(hours).toLocaleString('en-US')} h`
}

/** Format a possibly-missing per-game hour value, e.g. 44.3 → "44.3". */
export function fmtHoursPrecise(hours: number): string {
  if (hours <= 0) return '—'
  return hours.toFixed(1)
}

/** Format playtime minutes as hours, e.g. 320 → "5.3 h" (0 → "untouched"). */
export function fmtPlaytime(minutes: number): string {
  if (minutes <= 0) return 'untouched'
  return `${(minutes / 60).toFixed(1)} h`
}

/** Format a day count and its target date, e.g. (866) → "866 days · 2028-10-11". */
export function fmtEta(days: number | null): string {
  if (days === null) return 'N/A'
  const target = new Date()
  target.setDate(target.getDate() + days)
  return `${days.toLocaleString('en-US')} days · ${isoDate(target)}`
}

/** Render a Date as YYYY-MM-DD in local time. */
export function isoDate(date: Date): string {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

/** Whole days from today (local midnight) until the given ISO date string. */
export function daysUntil(isoDateStr: string): number {
  const target = new Date(`${isoDateStr}T00:00:00`)
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const ms = target.getTime() - today.getTime()
  return Math.ceil(ms / (1000 * 60 * 60 * 24))
}
