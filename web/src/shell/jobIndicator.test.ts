import { beforeEach, describe, expect, it, vi } from 'vitest'
import { q } from '../api/queries'
import { makeJob } from '../test/fixtures'
import { FakeEventSource, installEventSource, mount, stubApi } from '../test/harness'
import './jobIndicator'

beforeEach(installEventSource)

const chips = (el: Element) => [...el.querySelectorAll('a')]
const emit = (type: string, seq: number, body: Record<string, unknown>) => {
  FakeEventSource.last.emit(type, { seq, ts: 't', type, ...body })
}


describe('<job-indicator>', () => {
  it('renders nothing while no job is active', async () => {
    stubApi({ 'GET /api/jobs': [makeJob({ id: 'ji-done', state: 'succeeded' })] })
    const el = mount('<job-indicator></job-indicator>')
    expect(el.children).toHaveLength(0)
    await vi.waitFor(() => { expect(q.jobs.state.loading).toBe(false) })
    expect(el.children).toHaveLength(0)
    expect(FakeEventSource.all).toHaveLength(0)
  })

  it('shows at most two running jobs as links with their progress', async () => {
    const id = { a: 'ji1-a', b: 'ji1-b', c: 'ji1-c' }
    stubApi({
      'GET /api/jobs': [
        makeJob({ id: id.a, command: 'scan', progress: { step: 2, total: 8, label: 'Scanning' } }),
        makeJob({ id: id.b, command: 'check', progress: { step: 1, total: null, label: 'Checking' } }),
        makeJob({ id: id.c, command: 'done' }),
      ],
    })
    const el = mount('<job-indicator></job-indicator>')
    await vi.waitFor(() => { expect(chips(el)).toHaveLength(2) })
    const [first, second] = chips(el)
    expect(first).toHaveAttribute('aria-label', 'Scan: Scanning')
    expect(first).toHaveTextContent('2/8')
    expect(first).toHaveAttribute('href', `/jobs/?id=${id.a}`)
    expect(first).not.toHaveClass('jobchip-wait')
    expect(second).toHaveTextContent('…')
    expect(first.querySelector('[role=progressbar]')).toHaveAttribute('aria-valuenow', '25')
    expect(second.querySelector('[role=progressbar]')).not.toHaveAttribute('aria-valuenow')
    expect(el.querySelector('.jobchips')).toHaveAttribute('aria-label', 'Running jobs')
    expect(FakeEventSource.all).toHaveLength(2)
  })

  it('says "running" for a job with no progress yet', async () => {
    stubApi({ 'GET /api/jobs': [makeJob({ id: 'ji2-a', command: 'scan' })] })
    const el = mount('<job-indicator></job-indicator>')
    await vi.waitFor(() => { expect(chips(el)).toHaveLength(1) })
    expect(chips(el)[0]).toHaveAttribute('aria-label', 'Scan: running')
  })

  it('treats a zero total like an unknown one', async () => {
    stubApi({ 'GET /api/jobs': [makeJob({ id: 'ji2-b', progress: { step: 0, total: 0, label: 'x' } })] })
    const el = mount('<job-indicator></job-indicator>')
    await vi.waitFor(() => { expect(chips(el)).toHaveLength(1) })
    expect(chips(el)[0]).toHaveTextContent('…')
  })

  it('follows live events and flags a job that needs input', async () => {
    stubApi({ 'GET /api/jobs': [makeJob({ id: 'live-chip', command: 'scan' })] })
    const el = mount('<job-indicator></job-indicator>')
    await vi.waitFor(() => { expect(chips(el)).toHaveLength(1) })
    emit('progress', 1, { step: 3, total: 6, label: 'Halfway' })
    expect(chips(el)[0]).toHaveTextContent('3/6')
    expect(chips(el)[0]).toHaveAttribute('aria-label', 'Scan: Halfway')
    emit('state', 2, { state: 'waiting_input' })
    expect(chips(el)[0]).toHaveAttribute('aria-label', 'Scan: needs your input')
    expect(chips(el)[0]).toHaveClass('jobchip-wait')
    expect(chips(el)[0]).toHaveTextContent('needs input')
  })
})
