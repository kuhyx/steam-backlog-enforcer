import { afterEach, describe, expect, it, vi } from 'vitest'
import { q } from '../api/queries'
import { button } from '../test/events'
import { apiError, mount, stubApi, type Handler } from '../test/harness'
import './health'

const server = (over = {}) => ({ stale: false, started_at: '2026-10-10T10:00:00Z', version: '1.2.3', ...over })
const daemon = (state: string) => ({ state, started_at: null, pid: null, journal_tail: [], restart_available_at: null })
const pill = (el: Element, text: string) => [...el.querySelectorAll('.pill')].find((p) => p.textContent === text)
const never = () => new Promise(() => undefined)

describe('<health-badges>', () => {
  it('is neutral while nothing has loaded', () => {
    stubApi({ 'GET /api/server': never, 'GET /api/daemon': never })
    const el = mount('<health-badges></health-badges>')
    expect(pill(el, 'Server ok')).toHaveClass('pill-success')
    expect(pill(el, 'Daemon …')).toHaveClass('pill-neutral')
    expect(pill(el, 'Server ok')).not.toHaveAttribute('title')
  })

  it('shows a healthy server with its version, and a running daemon', async () => {
    stubApi({ 'GET /api/server': server(), 'GET /api/daemon': daemon('running') })
    const el = mount('<health-badges></health-badges>')
    await vi.waitFor(() => { expect(pill(el, 'Daemon running')).toHaveClass('pill-success') })
    expect(pill(el, 'Server ok')).toHaveAttribute('title', 'v1.2.3')
  })

  it('flags a stale server and a restarting daemon', async () => {
    stubApi({ 'GET /api/server': server({ stale: true }), 'GET /api/daemon': daemon('restarting') })
    const el = mount('<health-badges></health-badges>')
    await vi.waitFor(() => { expect(pill(el, 'Server stale')).toHaveClass('pill-warning') })
    expect(pill(el, 'Daemon restarting')).toHaveClass('pill-warning')
  })

  it('flags a dead server and an unreachable daemon', async () => {
    stubApi({ 'GET /api/server': apiError(500, 'op_failed'), 'GET /api/daemon': daemon('unreachable') })
    const el = mount('<health-badges></health-badges>')
    await vi.waitFor(() => { expect(pill(el, 'Server down')).toHaveClass('pill-danger') })
    await vi.waitFor(() => { expect(pill(el, 'Daemon unreachable')).toHaveClass('pill-danger') })
  })
})

describe('<stale-banner>', () => {
  const reload = vi.fn()
  afterEach(() => {
    reload.mockClear()
  })

  it('is absent while the code is current, or unknown', async () => {
    stubApi({ 'GET /api/server': server() })
    const el = mount('<stale-banner></stale-banner>')
    expect(el.children).toHaveLength(0)
    await vi.waitFor(() => { expect(q.server.state.loading).toBe(false) })
    expect(el.children).toHaveLength(0)
  })

  it('offers a restart, then reloads once the new process answers', async () => {
    vi.stubGlobal('location', { reload })
    const routes: Record<string, Handler> = { 'GET /api/server': server({ stale: true }), 'POST /api/server/restart': undefined }
    stubApi(routes)
    const el = mount('<stale-banner></stale-banner>')
    await vi.waitFor(() => { expect(el).toHaveTextContent('The web server is running stale code.') })
    expect(el.firstElementChild).toHaveAttribute('role', 'status')
    button(el, 'Restart server').click()
    await vi.waitFor(() => { expect(button(el, 'Restarting…')).toBeDisabled() })
    expect(reload).not.toHaveBeenCalled()
    routes['GET /api/server'] = server({ stale: false, started_at: '2026-10-10T11:00:00Z' })
    q.server.invalidate()
    await vi.waitFor(() => { expect(reload).toHaveBeenCalledTimes(1) })
    el.remove()
  })

  it('disables the button while the request is in flight', async () => {
    stubApi({ 'GET /api/server': server({ stale: true }), 'POST /api/server/restart': never })
    const el = mount('<stale-banner></stale-banner>')
    await vi.waitFor(() => { expect(el).toHaveTextContent('stale code') })
    button(el, 'Restart server').click()
    await vi.waitFor(() => { expect(button(el, 'Restart server')).toBeDisabled() })
  })

  it('shows why a restart was refused', async () => {
    stubApi({ 'GET /api/server': server({ stale: true }), 'POST /api/server/restart': apiError(429, 'rate_limited', 'too soon') })
    const el = mount('<stale-banner></stale-banner>')
    await vi.waitFor(() => { expect(el).toHaveTextContent('stale code') })
    button(el, 'Restart server').click()
    await vi.waitFor(() => { expect(el).toHaveTextContent('too soon') })
    expect(button(el, 'Restart server')).toBeEnabled()
  })
})
