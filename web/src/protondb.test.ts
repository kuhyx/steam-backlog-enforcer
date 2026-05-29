import { describe, expect, it } from 'vitest'
import { isPlayable, passesMinTier, tierLabel } from './protondb'

describe('isPlayable (faithful CLI compound rule)', () => {
  it('keeps games with no rating or pending', () => {
    expect(isPlayable('', '')).toBe(true)
    expect(isPlayable('pending', '')).toBe(true)
  })

  it('single rating must be gold-or-better', () => {
    expect(isPlayable('platinum', '')).toBe(true)
    expect(isPlayable('gold', '')).toBe(true)
    expect(isPlayable('silver', '')).toBe(false)
  })

  it('rejects when either rating is below silver', () => {
    expect(isPlayable('gold', 'bronze')).toBe(false)
    expect(isPlayable('bronze', 'gold')).toBe(false)
  })

  it('rejects when neither rating reaches gold', () => {
    expect(isPlayable('silver', 'silver')).toBe(false)
  })

  it('accepts when one is gold-or-better and the other silver-or-better', () => {
    expect(isPlayable('gold', 'silver')).toBe(true)
    expect(isPlayable('silver', 'gold')).toBe(true)
    expect(isPlayable('platinum', 'platinum')).toBe(true)
  })

  it('treats unknown tiers as below silver', () => {
    expect(isPlayable('mystery', 'mystery')).toBe(false)
  })
})

describe('passesMinTier', () => {
  it('honours treatMissingAsPass when no data', () => {
    expect(passesMinTier('', '', 'gold', true)).toBe(true)
    expect(passesMinTier('', '', 'gold', false)).toBe(false)
    expect(passesMinTier('pending', 'pending', 'gold', false)).toBe(false)
  })

  it('uses the best of the two ratings', () => {
    expect(passesMinTier('silver', 'gold', 'gold', false)).toBe(true)
    expect(passesMinTier('silver', 'silver', 'gold', false)).toBe(false)
    expect(passesMinTier('platinum', '', 'gold', false)).toBe(true)
  })
})

describe('tierLabel', () => {
  it('renders a dash, single, or paired label', () => {
    expect(tierLabel('', '')).toBe('—')
    expect(tierLabel('gold', 'gold')).toBe('gold')
    expect(tierLabel('gold', '')).toBe('gold')
    expect(tierLabel('gold', 'silver')).toBe('gold / silver')
  })
})
