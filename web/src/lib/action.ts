// A mutation without React Query: tracks pending/error for one async call
// and reports every change so the owning element can re-render.

export class Action<A extends unknown[], R> {
  pending = false
  error: unknown = null
  private readonly fn: (...args: A) => Promise<R>
  private readonly onChange: () => void

  constructor(fn: (...args: A) => Promise<R>, onChange: () => void) {
    this.fn = fn
    this.onChange = onChange
  }

  /** Run once; resolves to the result, or undefined when it failed. */
  async run(...args: A): Promise<{ ok: true; value: R } | { ok: false }> {
    this.pending = true
    this.error = null
    this.onChange()
    try {
      const value = await this.fn(...args)
      return { ok: true, value }
    } catch (e) {
      this.error = e
      return { ok: false }
    } finally {
      this.pending = false
      this.onChange()
    }
  }
}
