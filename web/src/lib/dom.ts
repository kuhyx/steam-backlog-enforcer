// Tiny DOM builder shared by every custom element (after dufs-cloud's
// elements/dom.ts): `on*` attrs become listeners, `true` is a bare boolean
// attribute, `false`/null/undefined attrs and children are skipped, and
// child arrays are flattened so `rows.map(...)` can be passed directly.

export type Attr = string | number | boolean | null | undefined | EventListener
export type Child = Node | string | number | null | undefined | false | readonly Child[]

/** Append `child` (flattening arrays, skipping empties) to `el`. */
export function append(el: Element, child: Child): void {
  if (child === null || child === undefined || child === false) return
  if (Array.isArray(child)) {
    for (const c of child as readonly Child[]) append(el, c)
    return
  }
  el.append(typeof child === 'number' ? String(child) : (child as Node | string))
}

export function h<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attrs: Record<string, Attr> = {},
  ...children: Child[]
): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag)
  for (const [key, value] of Object.entries(attrs)) {
    if (typeof value === 'function') el.addEventListener(key.slice(2).toLowerCase(), value)
    else if (value === true) el.setAttribute(key, '')
    else if (value !== false && value !== null && value !== undefined) el.setAttribute(key, String(value))
  }
  for (const child of children) append(el, child)
  return el
}

/** An element by tag name that is not in HTMLElementTagNameMap (custom elements). */
export function hx(tag: string, attrs: Record<string, Attr> = {}, ...children: Child[]): HTMLElement {
  return h(tag as 'div', attrs, ...children)
}

export function define(tag: string, ctor: CustomElementConstructor): void {
  if (!customElements.get(tag)) customElements.define(tag, ctor)
}

/** The parsed JSON of attribute `name`, or `fallback` when absent or invalid. */
export function jsonAttr<T>(el: Element, name: string, fallback: T): T {
  const raw = el.getAttribute(name)
  if (raw === null) return fallback
  try {
    return JSON.parse(raw) as T
  } catch {
    return fallback
  }
}
