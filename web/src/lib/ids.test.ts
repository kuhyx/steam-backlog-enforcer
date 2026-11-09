import { expect, it } from 'vitest'
import { uid } from './ids'

it('hands out document-unique ids with a prefix', () => {
  const a = uid()
  const b = uid('phrase')
  expect(a).toMatch(/^sbe-\d+$/)
  expect(b).toMatch(/^phrase-\d+$/)
  expect(a).not.toBe(b)
})
