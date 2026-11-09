import { afterEach, describe, expect, it, vi } from 'vitest'
import { q } from '../api/queries'
import { apiError, stubApi, type Handler } from '../test/harness'
import { ServerRestart } from './serverRestart'

const reload = vi.fn()
const server = (started_at: string) => ({ stale: false, started_at, version: '1' })
const made: ServerRestart[] = []
function make() {
  const onChange = vi.fn()
  const restart = new ServerRestart(onChange)
  made.push(restart)
  return { restart, onChange }
}

afterEach(() => {
  for (const r of made.splice(0)) r.dispose()
  reload.mockClear()
})

describe('ServerRestart', () => {
  it('reloads when the first answer arrives after a restart asked before any answer', async () => {
    vi.stubGlobal('location', { reload })
    let answer: (v: unknown) => void = () => undefined
    stubApi({ 'GET /api/server': () => new Promise((r) => { answer = r }), 'POST /api/server/restart': undefined })
    const { restart, onChange } = make()
    expect(restart.restarting).toBe(false)
    await restart.action.run()
    expect(restart.restarting).toBe(true)
    expect(onChange).toHaveBeenCalled()
    expect(reload).not.toHaveBeenCalled()
    answer(server('2026-10-10T12:00:00Z'))
    await vi.waitFor(() => { expect(reload).toHaveBeenCalledTimes(1) })
  })

  it('waits for a later started_at than the one it saw', async () => {
    vi.stubGlobal('location', { reload })
    const routes: Record<string, Handler> = {
      'GET /api/server': server('2026-10-10T10:00:00Z'),
      'POST /api/server/restart': undefined,
    }
    stubApi(routes)
    q.server.set(server('2026-10-10T10:00:00Z'))
    const { restart } = make()
    await restart.action.run()
    await vi.waitFor(() => { expect(q.server.state.loading).toBe(false) })
    expect(reload).not.toHaveBeenCalled()
    q.server.set(server('2026-10-10T10:00:00Z'))
    expect(reload).not.toHaveBeenCalled()
    q.server.set(server('2026-10-10T11:00:00Z'))
    expect(reload).toHaveBeenCalledTimes(1)
  })

  it('ignores an answer without a start time, and subscribes only once', async () => {
    vi.stubGlobal('location', { reload })
    const mock = stubApi({ 'GET /api/server': apiError(500, 'op_failed'), 'POST /api/server/restart': undefined })
    const { restart } = make()
    await restart.action.run()
    await restart.action.run()
    await vi.waitFor(() => { expect(q.server.state.loading).toBe(false) })
    expect(reload).not.toHaveBeenCalled()
    expect(mock.mock.calls.filter(([p]) => p === '/api/server')).toHaveLength(1)
  })

  it('stays idle when the restart request fails', async () => {
    stubApi({ 'POST /api/server/restart': apiError(429, 'rate_limited', 'too soon') })
    const { restart } = make()
    const out = await restart.action.run()
    expect(out.ok).toBe(false)
    expect(restart.restarting).toBe(false)
  })

  it('dispose stops watching, and is safe to repeat or call early', async () => {
    vi.stubGlobal('location', { reload })
    stubApi({ 'GET /api/server': server('a'), 'POST /api/server/restart': undefined })
    const { restart } = make()
    restart.dispose()
    await restart.action.run()
    restart.dispose()
    restart.dispose()
    q.server.set(server('b'))
    expect(reload).not.toHaveBeenCalled()
  })
})
