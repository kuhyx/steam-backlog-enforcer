import { screen } from '@testing-library/dom'
import { describe, expect, it } from 'vitest'
import { q } from '../api/queries'
import { makeStatus } from '../test/fixtures'
import { mount, stubApi } from '../test/harness'
import { visibleWords } from '../test/visibleWords'
import './store'

describe('store notice', () => {
  it('says the store is blocked', async () => {
    stubApi({ 'GET /api/status': makeStatus({ store_blocked: true }) })
    const el = mount('<store-notice></store-notice>')
    const notice = await screen.findByRole('status')
    expect(notice).toHaveClass('notice-info')
    expect(notice).toHaveAttribute('data-blocked', 'true')
    expect(screen.getByText(/Store blocked\. .*capped at 30 minutes/)).toHaveClass('sr-only')
    expect(visibleWords(el)).toEqual([])
  })

  it('warns when it is open', async () => {
    stubApi({ 'GET /api/status': makeStatus({ store_blocked: false }) })
    const el = mount('<store-notice></store-notice>')
    const notice = await screen.findByRole('status')
    expect(notice).toHaveClass('notice-warning')
    expect(notice).toHaveAttribute('data-blocked', 'false')
    expect(screen.getByText(/Store unblocked\. .*re-blocks automatically/)).toHaveClass('sr-only')
    expect(visibleWords(el)).toEqual([])
  })

  it('shows no notice until the status is known', () => {
    stubApi({ 'GET /api/status': () => new Promise(() => undefined) })
    const el = mount('<store-notice></store-notice>')
    expect(q.status.state.loading).toBe(true)
    expect(screen.queryByRole('status')).toBeNull()
    expect(el.childNodes).toHaveLength(0)
  })
})
