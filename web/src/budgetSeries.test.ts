import { describe, expect, it } from 'vitest'
import { OTHER_KEY, SERIES_COLORS, UNATTRIBUTED_KEY, seriesClass } from './budgetSeries'

describe('seriesClass', () => {
  it('assigns ramp hues by legend position', () => {
    expect(seriesClass('app:1', 0)).toBe('seg cat-1')
    expect(seriesClass('app:2', 5)).toBe('seg cat-6')
  })

  it('wraps rather than emitting a seventh hue that does not exist', () => {
    expect(seriesClass('app:3', SERIES_COLORS)).toBe('seg cat-1')
  })

  it('keeps both sentinels off the ramp', () => {
    expect(seriesClass(UNATTRIBUTED_KEY, 0)).toBe('seg unattributed')
    expect(seriesClass(OTHER_KEY, 1)).toBe('seg other')
  })
})
