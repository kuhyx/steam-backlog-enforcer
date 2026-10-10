import { describe, expect, it } from 'vitest'
import { ago, bytes, clock, dateTime, duration } from './format'

describe('ui format', () => {
  it('bytes scales units and trims decimals', () => {
    expect(bytes(0)).toBe('0 B')
    expect(bytes(1536)).toBe('1.5 KB')
    expect(bytes(20 * 1024 ** 2)).toBe('20 MB')
    expect(bytes(5 * 1024 ** 5)).toBe('5120 TB')
  })

  it('clock renders m:ss and h:mm:ss, never negative', () => {
    expect(clock(75)).toBe('1:15')
    expect(clock(3725)).toBe('1:02:05')
    expect(clock(-4)).toBe('0:00')
  })

  it('ago buckets', () => {
    const now = Date.parse('2026-10-10T12:00:00Z')
    const at = (s: number) => new Date(now - s * 1000).toISOString()
    expect(ago(null, now)).toBe('—')
    expect(ago(at(10), now)).toBe('just now')
    expect(ago(at(300), now)).toBe('5 min ago')
    expect(ago(at(7200), now)).toBe('2 h ago')
    expect(ago(at(172_800), now)).toBe('2 d ago')
  })

  it('ago defaults to the current time', () => {
    expect(ago(new Date().toISOString())).toBe('just now')
  })

  it('dateTime formats or dashes', () => {
    expect(dateTime(null)).toBe('—')
    expect(dateTime('2026-10-10T12:00:00Z')).toMatch(/\d/)
  })

  it('duration spans start to end, or to now while running', () => {
    expect(duration(null, null)).toBe('—')
    expect(duration('2026-10-10T10:00:00Z', '2026-10-10T10:01:05Z')).toBe('1:05')
    expect(duration('2026-10-10T10:00:00Z', null, Date.parse('2026-10-10T10:00:30Z'))).toBe('0:30')
    expect(duration(new Date().toISOString(), null)).toBe('0:00')
  })
})
