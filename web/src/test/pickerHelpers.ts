// Shared by the icon-word picker tests: mount it against a fake server that
// stores what it is sent, plus key and query helpers.

import { expect, vi } from 'vitest'
import type { IconChoice } from '../api/iconWordsContract'
import { ICONS } from '../icons/registry'
import { must } from './events'
import { stubApi } from './harness'
import '../icons/picker'

export const N = ICONS.length
export const [A, B, C, D] = ICONS as [(typeof ICONS)[number], (typeof ICONS)[number], (typeof ICONS)[number], (typeof ICONS)[number]]
export const url = (id: string) => `POST /api/icon-words/${id}`

/** Mount the picker against a fake server that stores what it is sent. */
export function start(icons: Record<string, IconChoice> = { [A.id]: { word: 'x', glyph: null }, [B.id]: { word: null, glyph: null } }) {
  const stored: Record<string, IconChoice> = structuredClone(icons)
  const routes: Record<string, unknown> = { 'GET /api/icon-words': () => ({ version: 1, icons: stored }) }
  for (const e of ICONS) {
    routes[url(e.id)] = ({ body }: { body: IconChoice }) => {
      stored[e.id] = { ...stored[e.id], ...body }
      return { version: 1, icons: stored }
    }
  }
  const mock = stubApi(routes as never)
  document.body.innerHTML = '<icon-words-picker></icon-words-picker>'
  return { mock, stored }
}

export const q = (sel: string): HTMLElement => must(document.querySelector<HTMLElement>(sel))
export const input = (sel: string): HTMLInputElement => must(document.querySelector<HTMLInputElement>(sel))
export const count = () => q('.picker-count').textContent
export const field = () => input('input[name=own]')
export const press = (key: string, init: KeyboardEventInit = {}, target: Element = document.body) =>
  target.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init }))
export const at = (n: number) => vi.waitFor(() => { expect(count()).toBe(`${n} / ${N}`) })
