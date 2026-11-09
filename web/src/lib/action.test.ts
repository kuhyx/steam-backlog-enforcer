import { describe, expect, it, vi } from 'vitest'
import { Action } from './action'

describe('Action', () => {
  it('reports pending around a successful run and resolves the value', async () => {
    const seen: boolean[] = []
    let release = (): void => undefined
    const gate = new Promise<void>((r) => {
      release = r
    })
    const action = new Action<[number], number>(
      async (n: number) => {
        await gate
        return n * 2
      },
      () => {
        seen.push(action.pending)
      },
    )
    const out = action.run(4)
    expect(action.pending).toBe(true)
    release()
    await expect(out).resolves.toEqual({ ok: true, value: 8 })
    expect(seen).toEqual([true, false])
    expect(action.error).toBeNull()
  })

  it('keeps the error, then clears it on the next run', async () => {
    const boom = new Error('boom')
    let fail = true
    const onChange = vi.fn()
    const action = new Action(() => (fail ? Promise.reject(boom) : Promise.resolve('fine')), onChange)
    await expect(action.run()).resolves.toEqual({ ok: false })
    expect(action.error).toBe(boom)
    expect(action.pending).toBe(false)
    fail = false
    await expect(action.run()).resolves.toEqual({ ok: true, value: 'fine' })
    expect(action.error).toBeNull()
    expect(onChange).toHaveBeenCalledTimes(4)
  })
})
