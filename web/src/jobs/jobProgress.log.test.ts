import { beforeEach, describe, expect, it, vi } from 'vitest'
import { installEventSource } from '../test/harness'
import { mountJob } from '../test/jobHelpers'

beforeEach(installEventSource)

const sel = (el: Element, s: string) => el.querySelector(s)

describe('<job-progress> log', () => {
  it('lists lines with their time and counts them', () => {
    const { el, send } = mountJob()
    send('log', { level: 'info', message: 'hello' })
    send('log', { level: 'warning', message: 'careful' })
    expect(sel(el, 'summary')).toHaveTextContent('Log (2 lines)')
    expect(el.querySelectorAll('.log li')).toHaveLength(2)
    expect(sel(el, '.log-info')).toHaveTextContent('10:00:00 hello')
    expect(sel(el, '.log-warning')).toHaveTextContent('careful')
    expect(sel(el, 'details')).not.toHaveAttribute('open')
  })

  it('only appends new lines, keeping the ones already shown', () => {
    const { el, send } = mountJob()
    send('log', { level: 'info', message: 'one' })
    const first = sel(el, '.log li')
    send('log', { level: 'info', message: 'two' })
    expect(sel(el, '.log li')).toBe(first)
    expect(el.querySelectorAll('.log li')).toHaveLength(2)
  })

  it('opens by itself on an error line, once, and leaves the toggle to the user', () => {
    const { el, send } = mountJob()
    send('log', { level: 'error', message: 'bad' })
    const details = sel(el, 'details') as HTMLDetailsElement
    expect(details.open).toBe(true)
    details.open = false
    send('log', { level: 'error', message: 'worse' })
    expect(details.open).toBe(false)
  })

  it('stays closed in compact mode', () => {
    const { el, send } = mountJob({ compact: true })
    send('log', { level: 'error', message: 'bad' })
    expect(sel(el, 'details')).not.toHaveAttribute('open')
    expect(sel(el, 'section')).toHaveClass('job-compact')
  })

  it('says nothing has been printed yet', () => {
    const { el } = mountJob()
    expect(sel(el, '.log')).toHaveTextContent('No output yet.')
  })

  it('rebuilds the list when the newest-lines window slides', () => {
    const { el, send } = mountJob()
    for (let i = 0; i < 502; i++) send('log', { level: 'info', message: `line ${i}` })
    expect(el.querySelectorAll('.log li')).toHaveLength(500)
    expect(sel(el, '.log li')).toHaveTextContent('line 2')
    expect(sel(el, '.log li:last-child')).toHaveTextContent('line 501')
  })
})

describe('<job-progress> lifecycle', () => {
  it('re-renders on a timer, and stops when removed', async () => {
    vi.useFakeTimers({ now: Date.parse('2026-10-10T10:00:05Z') })
    const { el, es } = mountJob({ job: { started_at: '2026-10-10T10:00:00Z' } })
    await vi.advanceTimersByTimeAsync(10)
    expect(sel(el, '.job-meta')).toHaveTextContent('0:05')
    await vi.advanceTimersByTimeAsync(3000)
    expect(sel(el, '.job-meta')).toHaveTextContent('0:08')
    el.remove()
    expect(es.closed).toBe(true)
    await vi.advanceTimersByTimeAsync(3000)
    expect(sel(el, '.job-meta')).toHaveTextContent('0:08')
  })

  it('builds a fresh frame and log state when reattached', () => {
    const { el, send } = mountJob()
    send('log', { level: 'error', message: 'bad' })
    const section = sel(el, 'section')
    el.remove()
    document.body.append(el)
    expect(sel(el, 'section')).not.toBe(section)
    expect(sel(el, 'summary')).toHaveTextContent('Log (1 lines)')
    expect(sel(el, 'details')).toHaveAttribute('open')
  })
})
