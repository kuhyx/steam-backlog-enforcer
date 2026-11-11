// Library page sections (was screens/Library.tsx): the uninstall card's live
// count, and the All games / Installed switch over the cover grid and the
// installed table. The chosen view lives in the URL hash next to the
// browser's search state, so a reload comes back to it.

import { q } from '../api/queries'
import { define, h, hx } from '../lib/dom'
import { LiveElement } from '../lib/element'
import '../library/gameBrowser'
import { readHash, writeHash } from '../library/hashState'
import { card, empty, errorNotice, glyph, loading, pill } from '../ui/build'
import { bytes } from '../ui/format'

type View = 'all' | 'installed'

/** View key, spoken label, painted glyph. */
const VIEWS: [View, string, string][] = [
  ['all', 'All games', '🗂️'],
  ['installed', 'Installed', '💾'],
]

const viewFromHash = (): View => (readHash().get('view') === 'installed' ? 'installed' : 'all')

/** "Uninstall N…": how many installed games an uninstall would remove. */
export class UninstallCardElement extends LiveElement {
  protected override setup(): void {
    this.watch(q.installed)
  }

  protected update(): void {
    const removable = (q.installed.state.data?.games ?? []).filter((g) => !g.assigned && !g.protected)
    const label = `Uninstall ${removable.length}…`
    // Rebuild the card only when its label changes: it may hold focus.
    if (this.firstElementChild?.getAttribute('label') === label) return
    this.replaceChildren(hx('command-card', { name: 'uninstall', label }))
  }
}

/** `installed` as a table. */
export class InstalledTableElement extends LiveElement {
  protected override setup(): void {
    this.watch(q.installed)
  }

  protected update(): void {
    const { data, error } = q.installed.state
    const games = data?.games ?? []
    const total = games.reduce((a, g) => a + g.size_bytes, 0)
    this.replaceChildren(
      card(
        'Installed',
        [
          error ? errorNotice(error) : null,
          !data && !error ? loading('installed games') : null,
          data && games.length === 0 ? empty('No games installed.') : null,
          games.length > 0
            ? h(
                'div',
                { class: 'tbl', tabindex: 0, role: 'region', 'aria-label': 'Installed games' },
                h(
                  'table',
                  {},
                  h(
                    'thead',
                    {},
                    h(
                      'tr',
                      {},
                      h('th', { scope: 'col' }, glyph('🎮', 'Game')),
                      h('th', { scope: 'col' }, glyph('#', 'App id')),
                      h('th', { scope: 'col', class: 'num' }, glyph('💽', 'Size')),
                      h('th', { scope: 'col' }, glyph('🏷️', 'Role')),
                    ),
                  ),
                  h(
                    'tbody',
                    {},
                    games.map((g) =>
                      h(
                        'tr',
                        {},
                        h('td', {}, g.name),
                        h('td', { class: 'mono muted' }, g.app_id),
                        h('td', { class: 'num' }, bytes(g.size_bytes)),
                        h(
                          'td',
                          {},
                          g.assigned ? pill('accent', 'assigned', '🎯') : null,
                          g.protected ? pill('neutral', 'protected', '🛡️') : null,
                          !g.assigned && !g.protected ? glyph('🗑️', 'uninstall candidate', 'muted') : null,
                        ),
                      ),
                    ),
                  ),
                ),
              )
            : null,
        ],
        {
          icon: '💾',
          aside: data
            ? h(
                'span',
                { class: 'muted' },
                h('span', { 'aria-hidden': 'true' }, `🎮 ${games.length} · 💽 ${bytes(total)}`),
                h('span', { class: 'sr-only' }, `${games.length} games · ${bytes(total)}`),
              )
            : null,
        },
      ),
    )
  }
}

/**
 * The view switch. Both views stay mounted and the other is hidden, so the
 * browser keeps its search, caret and scroll across a switch.
 */
export class LibraryViewElement extends HTMLElement {
  private readonly buttons = new Map<View, HTMLButtonElement>()
  private readonly panes = new Map<View, HTMLDivElement>([
    ['all', h('div', {}, hx('game-browser', { 'hash-state': true }))],
    ['installed', h('div', {}, hx('installed-table'))],
  ])
  private readonly onHash = () => {
    this.show(viewFromHash())
  }

  connectedCallback(): void {
    if (!this.firstChild) {
      const seg = h(
        'div',
        { class: 'seg', role: 'group', 'aria-label': 'Library view' },
        VIEWS.map(([key, label, icon]) => {
          const btn = h(
            'button',
            {
              type: 'button',
              class: 'btn btn-ghost btn-small',
              'aria-label': label,
              onclick: () => {
                writeHash({ view: key === 'all' ? null : key })
                this.show(key)
              },
            },
            h('span', { 'aria-hidden': 'true' }, icon),
          )
          this.buttons.set(key, btn)
          return btn
        }),
      )
      this.replaceChildren(seg, ...this.panes.values())
    }
    this.show(viewFromHash())
    window.addEventListener('hashchange', this.onHash)
  }

  disconnectedCallback(): void {
    window.removeEventListener('hashchange', this.onHash)
  }

  private show(view: View): void {
    for (const [key, btn] of this.buttons) btn.setAttribute('aria-pressed', String(key === view))
    for (const [key, pane] of this.panes) pane.hidden = key !== view
  }
}

define('uninstall-card', UninstallCardElement)
define('installed-table', InstalledTableElement)
define('library-view', LibraryViewElement)
