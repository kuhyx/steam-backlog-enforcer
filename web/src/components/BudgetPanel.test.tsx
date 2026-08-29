import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { makeBudget } from '../test/factories'
import { BudgetPanel } from './BudgetPanel'

function stubBudget(snapshot: unknown) {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => snapshot }))
}

describe('BudgetPanel', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows a loading line before the first response', () => {
    stubBudget(makeBudget())
    render(<BudgetPanel demo={false} />)
    expect(screen.getByText(/Reading budget state/)).toBeInTheDocument()
  })

  it('renders all four sections once loaded', async () => {
    stubBudget(makeBudget())
    render(<BudgetPanel demo={false} />)
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Today' })).toBeInTheDocument(),
    )
    expect(screen.getByRole('heading', { name: 'Right now' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Last 14 days' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Rules in effect' })).toBeInTheDocument()
  })

  it('surfaces a transport failure', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: false, status: 500, statusText: 'Server Error' }),
    )
    render(<BudgetPanel demo={false} />)
    await waitFor(() =>
      expect(screen.getByText(/Could not read budget state/)).toBeInTheDocument(),
    )
  })

  it('names the permission problem and still shows the rest', async () => {
    stubBudget(
      makeBudget({
        readable: false,
        state_status: 'denied',
        error: 'Cannot read the budget state file.',
        today: null,
      }),
    )
    render(<BudgetPanel demo={false} />)
    await waitFor(() =>
      expect(screen.getByText(/Cannot read the budget state file/)).toBeInTheDocument(),
    )
    // The log, history and config are all still readable — the panel must not
    // go blank just because one file is locked down.
    expect(screen.getByRole('heading', { name: 'Right now' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Rules in effect' })).toBeInTheDocument()
  })

  it('falls back to a generic message when the backend sends none', async () => {
    stubBudget(makeBudget({ readable: false, state_status: 'denied', error: null, today: null }))
    render(<BudgetPanel demo={false} />)
    await waitFor(() =>
      expect(screen.getByText(/Budget state unavailable/)).toBeInTheDocument(),
    )
  })
})
