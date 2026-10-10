import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { makeBudget } from '../test/factories'
import { makeSpec } from '../test/fixtures'
import { renderRouted, stubApi } from '../test/harness'
import { Gaming } from './Gaming'

const SPECS = [makeSpec('gaming-reset'), makeSpec('block-gaming'), makeSpec('gaming-unblock')]

describe('Gaming', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('shows the production budget and the three gaming controls', async () => {
    const mock = stubApi({ 'GET /api/commands': SPECS, 'GET /api/budget': makeBudget() })
    renderRouted(<Gaming demo={false} />)
    expect(await screen.findByRole('heading', { name: 'Today' })).toBeInTheDocument()
    for (const name of ['Reset today…', 'Block gaming…', 'Release mounts…']) {
      expect(screen.getAllByText(name).length).toBeGreaterThan(0)
    }
    expect(mock.mock.calls.some(([p]) => p === '/api/budget')).toBe(true)
    expect(screen.getByRole('link', { name: 'Show demo budget' })).toHaveAttribute('href', '/gaming?demo=true')
  })

  it('reads the demo run when asked, and links back', async () => {
    const mock = stubApi({ 'GET /api/commands': SPECS, 'GET /api/budget?demo=1': makeBudget() })
    renderRouted(<Gaming demo />)
    await screen.findByRole('heading', { name: 'Today' })
    expect(mock.mock.calls.some(([p]) => p === '/api/budget?demo=1')).toBe(true)
    const link = screen.getByRole('link', { name: 'Show production budget' })
    expect(link).toHaveAttribute('href', '/gaming?demo=false')
    await userEvent.click(link)
  })
})
