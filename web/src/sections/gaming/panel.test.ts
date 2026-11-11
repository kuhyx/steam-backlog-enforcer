import { screen } from '@testing-library/dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { makeBudget, makeBudgetRules } from '../../test/factories'
import { apiError, flush, mount, stubApi, type Handler } from '../../test/harness'
import { isDemo } from './panel'

const goto = (url: string) => {
  history.replaceState(null, '', url)
}

afterEach(() => {
  goto('/')
})

describe('isDemo', () => {
  it('reads ?demo=1 and the legacy ?demo=true', () => {
    expect(isDemo('?demo=1')).toBe(true)
    expect(isDemo('?demo=true')).toBe(true)
    expect(isDemo('?demo=0')).toBe(false)
    expect(isDemo('')).toBe(false)
    goto('/gaming/?demo=1')
    expect(isDemo()).toBe(true)
  })
})

describe('<budget-mode-link>', () => {
  it('offers the demo budget from production', () => {
    goto('/gaming/')
    mount('<budget-mode-link></budget-mode-link>')
    expect(screen.getByRole('link', { name: 'Show demo budget' })).toHaveAttribute('href', '/gaming/?demo=1')
  })

  it('links back to production from the demo', () => {
    goto('/gaming/?demo=1')
    mount('<budget-mode-link></budget-mode-link>')
    expect(screen.getByRole('link', { name: 'Show production budget' })).toHaveAttribute('href', '/gaming/')
  })
})

describe('<budget-panel>', () => {
  it('shows a loading line before the first response', () => {
    stubApi({ 'GET /api/budget': () => new Promise(() => undefined) })
    mount('<budget-panel></budget-panel>')
    expect(screen.getByText(/Loading budget state/)).toBeInTheDocument()
  })

  it('reads the production budget and renders all four sections', async () => {
    goto('/gaming/')
    const mock = stubApi({ 'GET /api/budget': makeBudget() })
    mount('<budget-panel></budget-panel>')
    expect(await screen.findByRole('heading', { name: 'Today' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Right now' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Last 14 days' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Rules in effect' })).toBeInTheDocument()
    expect(mock.mock.calls.map(([p]) => p)).toEqual(['/api/budget'])
  })

  it('reads the demo run on ?demo=1', async () => {
    goto('/gaming/?demo=1')
    const mock = stubApi({ 'GET /api/budget?demo=1': makeBudget({ rules: makeBudgetRules({ demo: true }) }) })
    mount('<budget-panel></budget-panel>')
    expect(await screen.findByText(/demo \(short budget/)).toBeInTheDocument()
    expect(mock.mock.calls.map(([p]) => p)).toEqual(['/api/budget?demo=1'])
  })

  it('surfaces a transport failure', async () => {
    stubApi({ 'GET /api/budget': () => Promise.reject(new Error('API returned 500 Server Error')) })
    mount('<budget-panel></budget-panel>')
    expect((await screen.findByText('Could not read budget state: API returned 500 Server Error')).closest('p')).toHaveClass('error')
    expect(screen.getByText('./run.sh serve')).toBeInTheDocument()
  })

  it('names the permission problem and still shows the rest', async () => {
    stubApi({
      'GET /api/budget': makeBudget({ readable: false, state_status: 'denied', error: 'Cannot read the budget state file.', today: null }),
    })
    mount('<budget-panel></budget-panel>')
    expect(await screen.findByText(/Cannot read the budget state file/)).toBeInTheDocument()
    // The log, history and config are all still readable: the panel must not
    // go blank just because one file is locked down.
    expect(screen.getByRole('heading', { name: 'Right now' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Rules in effect' })).toBeInTheDocument()
  })

  it('polls every 5 s and stops once removed', async () => {
    vi.useFakeTimers()
    const mock = stubApi({ 'GET /api/budget': makeBudget() })
    const el = mount('<budget-panel></budget-panel>')
    await flush(10)
    expect(mock).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(5000)
    expect(mock).toHaveBeenCalledTimes(2)
    el.remove()
    await vi.advanceTimersByTimeAsync(20_000)
    expect(mock).toHaveBeenCalledTimes(2)
  })

  it('reports a non-ok response', async () => {
    stubApi({ 'GET /api/budget': apiError(500, 'op_failed') })
    mount('<budget-panel></budget-panel>')
    expect(await screen.findByText('Could not read budget state: API returned 500 Error')).toBeInTheDocument()
  })

  it('reports a non-Error rejection as text', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue('network down'))
    mount('<budget-panel></budget-panel>')
    expect(await screen.findByText('Could not read budget state: network down')).toBeInTheDocument()
  })

  it('recovers on the next good poll', async () => {
    vi.useFakeTimers()
    const routes: Record<string, Handler> = { 'GET /api/budget': apiError(500, 'op_failed') }
    stubApi(routes)
    mount('<budget-panel></budget-panel>')
    await flush(10)
    expect(screen.getByText(/Could not read budget state/)).toBeInTheDocument()
    routes['GET /api/budget'] = makeBudget()
    await vi.advanceTimersByTimeAsync(5000)
    expect(screen.queryByText(/Could not read budget state/)).toBeNull()
    expect(screen.getByRole('heading', { name: 'Today' })).toBeInTheDocument()
  })

  // Browser automation always drives a hidden tab: this is the case that used
  // to leave the panel stuck on its loading text forever.
  it('loads and polls while the tab is hidden', async () => {
    Object.defineProperty(document, 'hidden', { value: true, configurable: true })
    try {
      vi.useFakeTimers()
      const mock = stubApi({ 'GET /api/budget': makeBudget() })
      mount('<budget-panel></budget-panel>')
      await flush(10)
      expect(screen.getByRole('heading', { name: 'Today' })).toBeInTheDocument()
      await vi.advanceTimersByTimeAsync(10_000)
      expect(mock).toHaveBeenCalledTimes(3)
    } finally {
      Object.defineProperty(document, 'hidden', { value: false, configurable: true })
    }
  })

  it('drops a response that arrives after removal', async () => {
    let resolve: (value: unknown) => void = () => undefined
    stubApi({ 'GET /api/budget': () => new Promise((r) => (resolve = r)) })
    const el = mount('<budget-panel></budget-panel>')
    el.remove()
    resolve(makeBudget())
    await flush(10)
    expect(el.querySelector('.budget')).toBeNull()
    expect(el).toHaveTextContent('Loading budget state')
  })
})
