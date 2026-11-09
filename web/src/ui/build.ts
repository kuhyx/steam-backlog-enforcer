// DOM builders for the shared bits every screen uses (was ui/Page.tsx and
// ui/Notice.tsx). Static page chrome lives in .astro components; these are
// for content a custom element renders from live data.

import { explain } from '../api/errors'
import { h, type Child } from '../lib/dom'

export type Tone = 'info' | 'success' | 'warning' | 'danger'

export function notice(tone: Tone, title: string | null, ...children: Child[]): HTMLDivElement {
  return h(
    'div',
    { class: `notice notice-${tone}`, role: tone === 'danger' ? 'alert' : 'status' },
    title ? h('strong', { class: 'notice-title' }, title) : null,
    children.length ? h('div', { class: 'notice-text' }, ...children) : null,
  )
}

/** An ApiFailure (or anything thrown) as a titled, actionable message. */
export function errorNotice(error: unknown, ...children: Child[]): HTMLDivElement {
  const e = explain(error)
  return notice(
    'danger',
    e.title,
    e.detail ? h('p', { class: 'm0' }, e.detail) : null,
    h('p', { class: 'm0 muted' }, e.hint),
    ...children,
  )
}

export function copyButton(text: string, label = 'Copy'): HTMLButtonElement {
  const btn = h('button', { type: 'button', class: 'btn btn-ghost btn-small' }, label)
  btn.addEventListener('click', () => {
    // No clipboard API outside a secure context: the command stays selectable.
    if (!('clipboard' in navigator)) return
    void navigator.clipboard.writeText(text).then(() => {
      btn.textContent = 'Copied'
      setTimeout(() => {
        btn.textContent = label
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
  return h('p', { class: 'loading', role: 'status' }, h('span', { class: 'spinner', 'aria-hidden': 'true' }), ` Loading ${what}…`)
}

export function empty(...children: Child[]): HTMLParagraphElement {
  return h('p', { class: 'empty' }, ...children)
}

export interface CardOptions {
  aside?: Child
  className?: string
}

export function card(title: string | null, body: Child, { aside, className = '' }: CardOptions = {}): HTMLElement {
  const head =
    title || aside ? h('div', { class: 'box-head' }, title ? h('h2', {}, title) : null, aside ?? null) : null
  return h('section', { class: `box ${className}`.trim(), 'aria-label': title }, head, body)
}

/** Label/value rows; values are right-aligned so they line up across cards. */
export function facts(rows: readonly (readonly [Child, Child])[]): HTMLDListElement {
  return h(
    'dl',
    { class: 'facts' },
    rows.map(([k, v]) => h('div', { class: 'fact' }, h('dt', {}, k), h('dd', {}, v))),
  )
}

export function pill(tone: string, text: string): HTMLSpanElement {
  return h('span', { class: `pill pill-${tone}` }, text)
}

export function link(href: string, text: Child, className = 'btn btn-ghost btn-small'): HTMLAnchorElement {
  return h('a', { href, class: className }, text)
}
