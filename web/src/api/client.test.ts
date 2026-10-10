import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TOKEN_META } from './contract'
import { api, ApiFailure, request, sessionToken, startJob } from './client'
import { apiError, bodiesOf, Reply, stubApi } from '../test/harness'
import { makeJob, makePending } from '../test/fixtures'

function setToken(token: string | null) {
  document.head.querySelectorAll(`meta[name="${TOKEN_META}"]`).forEach((m) => m.remove())
  if (token !== null) {
    const m = document.createElement('meta')
    m.name = TOKEN_META
    m.content = token
    document.head.append(m)
  }
}

describe('sessionToken', () => {
  afterEach(() => setToken(null))
  it('reads the meta tag, empty when absent', () => {
    expect(sessionToken()).toBe('')
    setToken('abc')
    expect(sessionToken()).toBe('abc')
  })
})

describe('request', () => {
  beforeEach(() => setToken('tok'))
  afterEach(() => {
    setToken(null)
    sessionStorage.clear()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('sends no token on GET and returns the parsed body', async () => {
    const mock = stubApi({ 'GET /api/x': { a: 1 } })
    await expect(request('GET', '/api/x')).resolves.toEqual({ a: 1 })
    const headers = mock.mock.calls[0][1]?.headers as Record<string, string>
    expect(headers).toEqual({ Accept: 'application/json' })
  })

  it('sends the token and a JSON body on writes', async () => {
    const mock = stubApi({ 'POST /api/x': undefined })
    await expect(request('POST', '/api/x', { b: 2 })).resolves.toBeUndefined()
    const headers = mock.mock.calls[0][1]?.headers as Record<string, string>
    expect(headers['X-SBE-Token']).toBe('tok')
    expect(headers['Content-Type']).toBe('application/json')
    expect(bodiesOf(mock, 'POST /api/x')).toEqual([{ b: 2 }])
  })

  it('turns a transport error into a network failure', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('refused')))
    await expect(request('GET', '/api/x')).rejects.toMatchObject({ code: 'network', message: 'refused', status: 0 })
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue('weird'))
    await expect(request('GET', '/api/x')).rejects.toMatchObject({ code: 'network', message: 'weird' })
  })

  it('maps a JSON error body to its code', async () => {
    stubApi({ 'GET /api/x': apiError(409, 'busy', 'job running') })
    const err = await request('GET', '/api/x').catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiFailure)
    expect(err).toMatchObject({ code: 'busy', message: 'job running', status: 409, name: 'ApiFailure' })
  })

  it('defaults a missing error message to empty', async () => {
    stubApi({ 'GET /api/x': new Reply(400, { error: 'invalid_params' }) })
    await expect(request('GET', '/api/x')).rejects.toMatchObject({ code: 'invalid_params', message: '' })
  })

  it('maps a non-JSON error to an http failure', async () => {
    stubApi({ 'GET /api/x': new Reply(502, undefined, '<html>bad gateway</html>') })
    await expect(request('GET', '/api/x')).rejects.toMatchObject({ code: 'http', message: '502 Error', status: 502 })
  })

  describe('bad_token', () => {
    const reload = vi.fn()
    beforeEach(() => {
      reload.mockClear()
      vi.stubGlobal('location', { ...window.location, reload })
    })

    it('reloads once, then not again inside the guard window', async () => {
      stubApi({ 'POST /api/x': apiError(403, 'bad_token') })
      await expect(request('POST', '/api/x')).rejects.toMatchObject({ code: 'bad_token' })
      await expect(request('POST', '/api/x')).rejects.toMatchObject({ code: 'bad_token' })
      expect(reload).toHaveBeenCalledTimes(1)
    })

    it('does not reload for a keepalive request', async () => {
      stubApi({ 'DELETE /api/x': apiError(403, 'bad_token') })
      await expect(request('DELETE', '/api/x', undefined, true)).rejects.toBeInstanceOf(ApiFailure)
      expect(reload).not.toHaveBeenCalled()
    })

    it('never reloads blind when storage is unavailable', async () => {
      stubApi({ 'POST /api/x': apiError(403, 'bad_token') })
      vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
        throw new Error('denied')
      })
      await expect(request('POST', '/api/x')).rejects.toBeInstanceOf(ApiFailure)
      expect(reload).not.toHaveBeenCalled()
    })
  })
})

describe('api', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('hits every endpoint with the right verb and path', async () => {
    const routes: Record<string, unknown> = {}
    const keys = [
      'GET /api/status', 'GET /api/stats', 'GET /api/installed', 'GET /api/library', 'GET /api/commands',
      'GET /api/setup', 'POST /api/setup', 'GET /api/daemon', 'GET /api/server', 'POST /api/server/restart',
      'GET /api/backups', 'POST /api/backups/a%2Fb/restore', 'GET /api/jobs', 'GET /api/jobs/j1',
      'POST /api/jobs/j1/answer', 'POST /api/jobs/j1/cancel', 'POST /api/pending/p1/heartbeat',
      'POST /api/pending/p1/commit', 'DELETE /api/pending/p1',
    ]
    for (const k of keys) routes[k] = null
    const mock = stubApi(routes)
    await Promise.all([
      api.status(), api.stats(), api.installed(), api.library(), api.commands(), api.setup(),
      api.saveSetup({ steam_api_key: 'k', steam_id: 'i' }), api.daemon(), api.server(), api.restartServer(),
      api.backups(), api.restoreBackup('a/b', 'phrase'), api.jobs(), api.job('j1'),
      api.answer('j1', { prompt_id: 'q', value: 'v' }), api.cancelJob('j1'), api.heartbeat('p1'),
      api.commit('p1', 'phrase'), api.dropPending('p1'),
    ])
    expect(mock).toHaveBeenCalledTimes(keys.length)
    expect(bodiesOf(mock, 'POST /api/backups/a%2Fb/restore')).toEqual([{ confirm_phrase: 'phrase' }])
    expect(bodiesOf(mock, 'POST /api/pending/p1/commit')).toEqual([{ confirm_phrase: 'phrase' }])
  })

  it('startJob tells a job from a pending action', async () => {
    stubApi({ 'POST /api/jobs': (r) => (r.body && (r.body as { command: string }).command === 'scan' ? makeJob() : makePending()) })
    await expect(startJob({ command: 'scan', params: {} })).resolves.toMatchObject({ kind: 'job' })
    await expect(startJob({ command: 'gaming-reset', params: {} })).resolves.toMatchObject({ kind: 'pending' })
  })
})
