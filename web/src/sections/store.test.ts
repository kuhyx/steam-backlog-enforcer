import { screen } from '@testing-library/dom'
import { describe, expect, it } from 'vitest'
import { q } from '../api/queries'
import { makeStatus } from '../test/fixtures'
import { mount, stubApi } from '../test/harness'
import './store'

describe('store notice', () => {
  it('says the store is blocked', async () => {
    stubApi({ 'GET /api/status': makeStatus({ store_blocked: true }) })
    mount('<store-notice></store-notice>')
    expect(await screen.findByText('Store blocked')).toBeInTheDocument()
    expect(screen.getByText(/capped at 30 minutes/)).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveClass('notice-info')
  })

  it('warns when it is open', async () => {
    stubApi({ 'GET /api/status': makeStatus({ store_blocked: false }) })
    mount('<store-notice></store-notice>')
    expect(await screen.findByText('Store unblocked')).toBeInTheDocument()
    expect(screen.getByText(/re-blocks automatically/)).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveClass('notice-warning')
  })

  it('shows no notice until the status is known', () => {
    stubApi({ 'GET /api/status': () => new Promise(() => undefined) })
    const el = mount('<store-notice></store-notice>')
    expect(q.status.state.loading).toBe(true)
    expect(screen.queryByRole('status')).toBeNull()
    expect(el.childNodes).toHaveLength(0)
  })
})
