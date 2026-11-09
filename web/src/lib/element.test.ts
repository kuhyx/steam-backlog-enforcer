import { afterEach, describe, expect, it, vi } from 'vitest'
import { LiveElement } from './element'
import { Query } from './query'

const query = new Query(() => Promise.resolve('v'))
const updates: string[] = []

class Probe extends LiveElement {
  read: (() => { data: string | undefined }) | null = null
  protected override setup(): void {
    this.read = this.watch(query)
    this.tick(100)
    this.onCleanup(() => updates.push('cleanup'))
  }
  protected update(): void {
    updates.push(this.read?.().data ?? 'none')
  }
}
class Bare extends LiveElement {
  runs = 0
  protected update(): void {
    this.runs += 1
  }
}
customElements.define('x-probe', Probe)
customElements.define('x-bare', Bare)

describe('LiveElement', () => {
  afterEach(() => {
    updates.length = 0
  })

  it('runs setup then update on connect, and re-updates on query changes', async () => {
    const el = new Probe()
    document.body.append(el)
    expect(updates).toEqual(['none'])
    await query.refetch()
    expect(updates.at(-1)).toBe('v')
  })

  it('ticks while connected and releases everything on disconnect', async () => {
    vi.useFakeTimers()
    const el = new Probe()
    document.body.append(el)
    updates.length = 0
    vi.advanceTimersByTime(250)
    expect(updates).toHaveLength(2)
    el.remove()
    expect(updates.at(-1)).toBe('cleanup')
    updates.length = 0
    vi.advanceTimersByTime(500)
    await query.refetch()
    expect(updates).toEqual([])
  })

  it('works without overriding setup', () => {
    const el = new Bare()
    document.body.append(el)
    expect(el.runs).toBe(1)
    el.remove()
  })
})
