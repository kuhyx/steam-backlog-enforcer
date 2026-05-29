import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  daysUntil,
  fmtEta,
  fmtHours,
  fmtHoursPrecise,
  fmtPlaytime,
  isoDate,
} from './format'

afterEach(() => {
  vi.useRealTimers()
})

describe('fmtHours', () => {
  it('returns a dash for non-positive values', () => {
    expect(fmtHours(0)).toBe('—')
    expect(fmtHours(-3)).toBe('—')
  })
  it('rounds with thousands separators', () => {
    expect(fmtHours(67031.1)).toBe('67,031 h')
  })
})

describe('fmtHoursPrecise', () => {
  it('returns a dash for non-positive values', () => {
    expect(fmtHoursPrecise(-1)).toBe('—')
  })
  it('keeps one decimal place', () => {
    expect(fmtHoursPrecise(44.28)).toBe('44.3')
  })
})

describe('fmtPlaytime', () => {
  it('reports untouched at zero', () => {
    expect(fmtPlaytime(0)).toBe('untouched')
  })
  it('converts minutes to hours', () => {
    expect(fmtPlaytime(90)).toBe('1.5 h')
  })
})

describe('fmtEta', () => {
  it('returns N/A for null', () => {
    expect(fmtEta(null)).toBe('N/A')
  })
  it('returns days and the target date', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-05-29T12:00:00'))
    const out = fmtEta(10)
    expect(out).toContain('10 days')
    expect(out).toContain('2026-06-08')
  })
})

describe('isoDate', () => {
  it('formats a date as YYYY-MM-DD', () => {
    expect(isoDate(new Date(2026, 0, 5))).toBe('2026-01-05')
  })
})

describe('daysUntil', () => {
  it('counts whole days to a future date', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-05-29T12:00:00'))
    expect(daysUntil('2026-06-08')).toBe(10)
  })
})
