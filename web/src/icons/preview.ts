// The icon as it looks where the UI paints it, for the /words picker: inert
// replicas built from the same pieces as the real call sites (no handlers),
// showing the current glyph and word.

import type { JobState } from '../api/jobContract'
import { stateBadge } from '../jobs/progress'
import { h } from '../lib/dom'
import { NAV } from '../shell/nav'
import { notice, type Tone } from '../ui/build'
import type { IconId } from './registry'
import { iconMark, iconWord } from './render'

function inContext(id: IconId): HTMLElement {
  const [group = '', ...rest] = id.split('.')
  const tail = rest.join('.')
  const word = iconWord(id)
  const paired = word ? ' has-word' : ''
  switch (group) {
    case 'nav':
      return h(
        'span',
        { class: `nav-link active${paired}` },
        iconMark(id, 'nav-icon'),
        word,
        NAV.filter((n) => n.icon === id).map((n) => h('kbd', {}, n.key)),
      )
    case 'palette':
      return h('span', { class: 'btn btn-ghost palette-btn' }, iconMark(id, ''), word, h('kbd', {}, '⌃K'))
    case 'job':
      return stateBadge(tail.replace(/^state\./, '') as JobState)
    case 'notice':
      return notice(tail as Tone, null)
    default:
      return h('span', { class: 'btn btn-ghost' }, iconMark(id, 'cmd-icon'), word)
  }
}

export function contextPreview(id: IconId): HTMLDivElement {
  return h('div', { class: 'picker-context', inert: true }, inContext(id))
}
