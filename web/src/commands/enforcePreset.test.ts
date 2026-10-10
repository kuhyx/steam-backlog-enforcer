import { describe, expect, it } from 'vitest'
import type { ParamSpec } from '../api/contract'
import { makeSpec } from '../test/fixtures'
import { enforcePreset } from './enforcePreset'

const DEMO: ParamSpec = { name: 'demo', label: 'Demo mode', type: 'int', required: false, default: 0, min: 0, max: 1 }
const enforce = makeSpec('enforce', { kind: 'screen', params: [DEMO], privileged: true, cancellable: true })

describe('enforcePreset', () => {
  it('leaves other commands and an unpreset enforce alone', () => {
    const scan = makeSpec('scan')
    expect(enforcePreset(scan, { demo: 1 })).toEqual({ spec: scan, fixed: {} })
    expect(enforcePreset(enforce, undefined)).toEqual({ spec: enforce, fixed: {} })
    expect(enforcePreset(enforce, { other: 1 })).toEqual({ spec: enforce, fixed: {} })
  })

  it('makes the demo a cancellable user job with no mode field', () => {
    const { spec, fixed } = enforcePreset(enforce, { demo: 1 })
    expect(fixed).toEqual({ demo: 1 })
    expect(spec.params).toEqual([])
    expect(spec.privileged).toBe(false)
    expect(spec.cancellable).toBe(true)
    expect(spec.description).toMatch(/60-second demo budget/)
  })

  it('makes the restart a root op that cannot be cancelled', () => {
    const { spec, fixed } = enforcePreset(enforce, { demo: '0' })
    expect(fixed).toEqual({ demo: 0 })
    expect(spec.params).toEqual([])
    expect(spec.privileged).toBe(true)
    expect(spec.cancellable).toBe(false)
    expect(spec.description).toMatch(/^Restart the enforcer daemon/)
  })
})
