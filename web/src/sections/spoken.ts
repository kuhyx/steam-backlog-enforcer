// Textgate helper: paint glyphs, numbers and names; speak the sentence.

import { h, type Child } from '../lib/dom'

/** `painted` is shown (glyphs, numbers, names); `spoken` is the sentence a screen reader hears. */
export function said(spoken: string, ...painted: Child[]): HTMLSpanElement {
  return h('span', {}, h('span', { 'aria-hidden': 'true' }, ...painted), h('span', { class: 'sr-only' }, spoken))
}
