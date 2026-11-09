import { beforeEach, describe, expect, it, vi } from 'vitest'
import { q } from '../api/queries'
import { makeJob } from '../test/fixtures'
import { FakeEventSource, installEventSource, mount, stubApi } from '../test/harness'
import './jobIndicator'

beforeEach(installEventSource)

const chips = (el: Element) => [...el.querySelectorAll('a')]

// Currently RED: jobIndicator.ts update() calls unwatch() before
// this.watched.delete(id); hub.unwatch emits, which re-enters update() and
// recurses forever. Goes green once the id is deleted from the map first.
describe('<job-indicator> releasing streams', () => {
  it('stops following a job once it ends, and everything on removal', async () => {
    const id = { a: 'ji3-a', b: 'ji3-b' }
    stubApi({ 'GET /api/jobs': [makeJob({ id: id.a }), makeJob({ id: id.b })] })
    const el = mount('<job-indicator></job-indicator>')
    await vi.waitFor(() => { expect(chips(el)).toHaveLength(2) })
    const [sa, sb] = FakeEventSource.all
    q.jobs.set([makeJob({ id: id.a, state: 'succeeded' }), makeJob({ id: id.b })])
    expect(chips(el)).toHaveLength(1)
    expect(sa.closed).toBe(true)
    expect(sb.closed).toBe(false)
    expect(FakeEventSource.all).toHaveLength(2)
    el.remove()
    expect(sb.closed).toBe(true)
  })
})
