import { describe, expect, it } from 'vitest'
import type { ParamSpec } from '../api/contract'
import { initialValues, paramError, toParams } from './params'

const spec = (over: Partial<ParamSpec>): ParamSpec => ({
  name: 'n', label: 'Count', type: 'int', required: true, ...over,
})
const games = [{ app_id: 5, name: 'Five' }]

describe('paramError', () => {
  it('requires a value unless there is a default or it is optional', () => {
    expect(paramError(spec({}), ' ', [])).toBe('Count is required.')
    expect(paramError(spec({ default: 3 }), '', [])).toBeNull()
    expect(paramError(spec({ required: false }), '', [])).toBeNull()
  })

  it('accepts any text for a string', () => {
    expect(paramError(spec({ type: 'string' }), 'anything', [])).toBeNull()
  })

  it('wants whole numbers', () => {
    expect(paramError(spec({}), '1.5', [])).toBe('Count must be a whole number.')
    expect(paramError(spec({}), '-3', [])).toBeNull()
  })

  it('checks int bounds', () => {
    const s = spec({ min: 1, max: 5 })
    expect(paramError(s, '0', [])).toBe('At least 1.')
    expect(paramError(s, '6', [])).toBe('At most 5.')
    expect(paramError(s, '3', [])).toBeNull()
    expect(paramError(spec({}), '99', [])).toBeNull()
  })

  it('checks an app id against the known library', () => {
    const s = spec({ type: 'app_id' })
    expect(paramError(s, '0', games)).toBe('Enter a Steam app id.')
    expect(paramError(s, '9', games)).toBe('App 9 is not in your library snapshot.')
    expect(paramError(s, '5', games)).toBeNull()
    expect(paramError(s, '9', [])).toBeNull()
  })
})

describe('toParams', () => {
  const specs = [
    spec({ name: 'a', type: 'int', default: 7 }),
    spec({ name: 'b', type: 'string' }),
    spec({ name: 'c', type: 'app_id', required: false }),
    spec({ name: 'd', type: 'int' }),
  ]

  it('converts, applies defaults and omits empties', () => {
    expect(toParams(specs, { a: '', b: ' hi ', c: '42' })).toEqual({ a: 7, b: 'hi', c: 42 })
  })

  it('keeps a typed int', () => {
    expect(toParams(specs, { a: '2', d: '9' })).toEqual({ a: 2, d: 9 })
  })
})

describe('initialValues', () => {
  const specs = [spec({ name: 'a', default: 4 }), spec({ name: 'b', type: 'string' }), spec({ name: 'c' })]

  it('prefers the preset, then the default, then empty', () => {
    expect(initialValues(specs, { a: 1 })).toEqual({ a: '1', b: '', c: '' })
    expect(initialValues(specs)).toEqual({ a: '4', b: '', c: '' })
  })
})
