import { describe, expect, it } from 'vitest'
import { BUILD_STAMP, commitId } from './buildStamp'

describe('build stamp', () => {
  it('is the short commit plus a per-build time part', () => {
    expect(BUILD_STAMP).toMatch(/^[0-9a-f]{7,}\.[0-9a-z]+$/)
  })

  it('falls back when git is unavailable', () => {
    expect(
      commitId(() => {
        throw new Error('not a repo')
      }),
    ).toBe('unknown')
    expect(commitId(() => 'abc1234\n')).toBe('abc1234')
  })
})
