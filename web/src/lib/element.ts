// Base class for the app's stateful custom elements. Subclasses declare the
// queries they read in `setup()` via `watch()` and rebuild their light-DOM
// content in `update()`, which runs once on connect and again whenever a
// watched query changes. Everything subscribed is released on disconnect.

import type { Query, QueryState } from './query'

export abstract class LiveElement extends HTMLElement {
  private cleanups: (() => void)[] = []

  connectedCallback(): void {
    this.setup()
    this.update()
  }

  disconnectedCallback(): void {
    for (const fn of this.cleanups.splice(0)) fn()
  }

  /** Subscribe to `query`; `update()` re-runs on every change. */
  protected watch<T>(query: Query<T>): () => QueryState<T> {
    this.cleanups.push(
      query.subscribe(() => {
        this.update()
      }),
    )
    return () => query.state
  }

  /** Run `fn` on disconnect (timers, window listeners). */
  protected onCleanup(fn: () => void): void {
    this.cleanups.push(fn)
  }

  /** Re-run `update()` every `ms` (countdowns, "x ago" labels). */
  protected tick(ms: number): void {
    const id = setInterval(() => {
      this.update()
    }, ms)
    this.onCleanup(() => {
      clearInterval(id)
    })
  }

  protected setup(): void {
    // Default: nothing to watch.
  }

  protected abstract update(): void
}
