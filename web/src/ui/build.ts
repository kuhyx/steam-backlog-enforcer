// DOM builders for the shared bits every screen uses (was ui/Page.tsx and
// ui/Notice.tsx). Static page chrome lives in .astro components; these are
// for content a custom element renders from live data.

import { explain } from '../api/errors'
import { h, type Child } from '../lib/dom'

export type Tone = 'info' | 'success' | 'warning' | 'danger'

const TONE_ICON: Record<Tone, string> = {
  info: 'ℹ️',
  success: '✅',
  warning: '⚠️',
  danger: '⛔',
}

export function notice(tone: Tone, title: string | null, ...children: Child[]): HTMLDivElement {
  const el = h(
    'div',
    { class: `notice notice-${tone}`, role: tone === 'danger' ? 'alert' : 'status' },
    h('span', { class: 'notice-icon', 'aria-hidden': 'true' }, TONE_ICON[tone]),
    title ? h('strong', { class: 'notice-title' }, title) : null,
  )
  if (children.length) {
    el.append(h('div', { class: 'notice-text' }, ...children))
  }
  return el
}

export function errorNotice(error: unknown, ...children: Child[]): HTMLDivElement {
  // Textgate: the explanation (title + hint) is spoken only; the ⛔ icon,
  // danger tone and the server's own message stay visible.
  const e = explain(error)
  const el = notice('danger', null, e.detail ? h('p', { class: 'm0' }, e.detail) : null, ...children)
  el.dataset.code = e.code
  el.setAttribute('aria-label', `${e.title}. ${e.hint}`)
  return el
}

export function copyButton(text: string): HTMLButtonElement {
  const btn = h('button', { type: 'button', class: 'btn btn-ghost btn-small', 'aria-label': 'Copy command' }, '📋')
  btn.addEventListener('click', () => {
    if (!('clipboard' in navigator)) return
    void navigator.clipboard.writeText(text).then(() => {
      btn.textContent = '✅'
      btn.setAttribute('aria-label', 'Copied')
      setTimeout(() => {
        btn.textContent = '📋'
        btn.setAttribute('aria-label', 'Copy command')
      }, 2000)
    })
  })
  return btn
}

/** A shell command with a copy button — the recovery path when the UI cannot act. */
export function commandLine(command: string): HTMLDivElement {
  return h('div', { class: 'cmdline' }, h('code', {}, command), copyButton(command))
}

export function loading(what: string): HTMLParagraphElement {
  return h('p', { class: 'loading', role: 'status' }, h('span', { class: 'spinner', 'aria-hidden': 'true' }), h('span', { class: 'sr-only' }, `Loading ${what}`))
}

/** Empty-state marker: 📭 painted, the caller's sentence spoken only. */
export function empty(label: string): HTMLParagraphElement {
  return h(
    'p',
    { class: 'empty', 'aria-label': label },
    h('span', { class: 'empty-icon', 'aria-hidden': 'true' }, '📭'),
    ...(label ? [h('span', { class: 'sr-only' }, label)] : []),
  )
}

export interface CardOptions {
  aside?: Child
  className?: string
}

export function card(title: string | null, body: Child, { aside, className = '' }: CardOptions = {}): HTMLElement {
  const head =
    title || aside ? h('div', { class: 'box-head' }, title ? h('h2', {}, title) : null, aside ?? null) : null
  return h('section', { class: `box ${className}`.trim(), 'aria-label': title ?? '' }, head, body)
}

/** Label/value rows; values are right-aligned so they line up across cards. */
export function facts(rows: readonly (readonly [Child, Child])[]): HTMLDListElement {
  return h(
    'dl',
    { class: 'facts' },
    rows.map(([k, v]) => h('div', { class: 'fact' }, h('dt', {}, k), h('dd', {}, v))),
  )
}

const TONE_PILL_ICON: Record<string, string> = {
  info: 'ℹ️',
  success: '✅',
  warning: '⚠️',
  danger: '⛔',
  kept: '📌',
  excluded: '🚫',
  idle: '⏸️',
  running: '▶️',
}

export function pill(tone: string, text: string): HTMLSpanElement {
  const icon = TONE_PILL_ICON[tone] ?? ''
  return h('span', { class: `pill pill-${tone}` }, icon && h('span', { class: 'pill-icon', 'aria-hidden': 'true' }, icon), text)
}

export function link(href: string, text: Child, className = 'btn btn-ghost btn-small'): HTMLAnchorElement {
  return h('a', { href, class: className }, text)
}
