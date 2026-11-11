import { screen } from '@testing-library/dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiError, flush, mount, stubApi } from '../../test/harness'
import { names, show } from '../../test/plannerHelpers'

afterEach(() => {
  history.replaceState(null, '', '/')
})

describe('<game-table> loading', () => {
  it('shows loading until the dataset arrives', () => {
    stubApi({ 'GET /api/dataset': () => new Promise(() => undefined) })
    mount('<game-table></game-table>')
    expect(screen.getByRole('status')).toHaveTextContent('Loading backlog')
    expect(document.querySelector('game-table .spinner')).not.toBeNull()
  })

  it('renders the planner once data loads', async () => {
    await show()
    expect(screen.getByRole('heading', { name: 'Backlog Completion Planner' })).toBeInTheDocument()
    expect(screen.getByText(/CLI default qualifies/i)).toBeInTheDocument()
  })

  it('shows an error when the API call fails', async () => {
    stubApi({ 'GET /api/dataset': apiError(500, 'boom') })
    mount('<game-table></game-table>')
    await flush()
    expect(screen.getByRole('alert')).toHaveAttribute('data-code')
    expect(screen.getByText('./run.sh serve')).toBeInTheDocument()
  })

  it('handles a non-Error rejection', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue('network down'))
    mount('<game-table></game-table>')
    await flush()
    expect(screen.getByText(/network down/i)).toBeInTheDocument()
  })
})

describe('<game-table> hash changes', () => {
  it('re-reads a hand-edited hash', async () => {
    await show()
    history.replaceState(null, '', '#f.name=gam')
    window.dispatchEvent(new HashChangeEvent('hashchange'))
    expect(screen.getByRole('searchbox', { name: 'Filter Game' })).toHaveValue('gam')
    expect(names()).toEqual(['Gamma'])
  })

  it('stops listening for hash changes once removed', async () => {
    const { el } = await show()
    el.remove()
    history.replaceState(null, '', '#f.name=gam')
    window.dispatchEvent(new HashChangeEvent('hashchange'))
    expect(location.hash).toBe('#f.name=gam')
  })
})
