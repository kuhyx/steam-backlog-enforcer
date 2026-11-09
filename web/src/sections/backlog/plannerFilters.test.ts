import { describe, expect, it } from 'vitest'
import { makeDataset } from '../../test/factories'
import { defaultFilters, readFilters, writeFilters } from './plannerFilters'

const D = defaultFilters(makeDataset().defaults)
const write = (over: Partial<typeof D>) => {
  const p = new URLSearchParams()
  writeFilters({ ...D, ...over }, D, p)
  return p.toString()
}

describe('defaultFilters', () => {
  it('starts from the CLI thresholds', () => {
    expect(D).toMatchObject({ minCountComp: 15, minComp100: 3, minConfidenceSum: 18, protonMinTier: 'gold', basis: 'leisure', dailyHours: 4 })
  })
})

describe('planner filters in the hash', () => {
  it('writes nothing at the defaults', () => {
    expect(write({})).toBe('')
  })

  it('round-trips every non-default filter', () => {
    const f = {
      ...D,
      dailyHours: 6.5,
      minCountComp: 40,
      minComp100: 10,
      minConfidenceSum: 25,
      maxHoursPerGame: 50,
      fallbackHours: 30,
      protonTreatMissingAsPass: false,
      includeNoData: true,
      basis: 'rush' as const,
      protonMode: 'minTier' as const,
      protonMinTier: 'silver',
      playtimeMode: 'started' as const,
      targetDate: '2030-01-02',
      search: 'hollow knight',
      excluded: new Set([9, 3]),
    }
    const p = new URLSearchParams()
    writeFilters(f, D, p)
    expect(p.get('x')).toBe('3,9')
    expect(p.get('keepmissing')).toBe('0')
    expect(p.get('nodata')).toBe('1')
    expect(readFilters(new URLSearchParams(p.toString()), D)).toEqual(f)
  })

  it('falls back to the defaults for junk', () => {
    const p = new URLSearchParams('daily=&mincomp=abc&nodata=yes&basis=fast&proton=x&tier=mythic&playtime=y&target=soon&x=a,-1,0,2.5')
    expect(readFilters(p, D)).toEqual({ ...D, excluded: new Set() })
  })
})
