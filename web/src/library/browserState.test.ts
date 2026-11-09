import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'
import { at, render, search, sort, titles, withLibrary } from '../test/browserHelpers'
import { stateFromHash, stateToHash } from './browserState'

describe('hash state', () => {
  afterEach(() => {
    at('/')
  })

  it('round-trips search, sort and filters, dropping defaults', () => {
    const s = { query: 'hollow', sort: 'hltb' as const, filters: { hideCompleted: true, installedOnly: false, pickableOnly: true } }
    expect(stateToHash(s)).toEqual({ q: 'hollow', sort: 'hltb', f: 'completed,pickable' })
    at('/library/#q=hollow&sort=hltb&f=completed,pickable')
    expect(stateFromHash()).toEqual(s)
    expect(stateToHash({ query: '', sort: 'name', filters: stateFromHash().filters })).toMatchObject({ q: '', sort: null })
  })

  it('falls back to the defaults for missing or unknown values', () => {
    at('/library/#sort=bogus&f=nope')
    expect(stateFromHash()).toEqual({
      query: '',
      sort: 'name',
      filters: { hideCompleted: false, installedOnly: false, pickableOnly: false },
    })
  })
})

describe('GameBrowser URL hash (hash-state)', () => {
  beforeEach(() => {
    withLibrary()
  })
  afterEach(() => {
    at('/')
  })

  it('writes search, sort and filters to the hash as they change, without history entries', async () => {
    at('/library/#view=installed')
    const before = history.length
    render(undefined, 'hash-state')
    await screen.findByText('5 of 5 games')
    await userEvent.selectOptions(sort(), 'hltb')
    await userEvent.click(screen.getByRole('checkbox', { name: 'Installed only' }))
    expect(location.hash).toBe('#view=installed&sort=hltb&f=installed')
    await userEvent.type(search(), 'witcher 2')
    expect(location.hash).toBe('#view=installed&sort=hltb&f=installed&q=witcher+2')
    await userEvent.clear(search())
    await userEvent.selectOptions(sort(), 'name')
    await userEvent.click(screen.getByRole('checkbox', { name: 'Installed only' }))
    expect(location.hash).toBe('#view=installed')
    expect(history.length).toBe(before)
  })

  it('clears the hash entirely once everything is back to default', async () => {
    at('/library/')
    render(undefined, 'hash-state')
    await screen.findByText('5 of 5 games')
    await userEvent.type(search(), 'x')
    expect(location.hash).toBe('#q=x')
    await userEvent.clear(search())
    expect(location.href).toMatch(/\/library\/$/)
  })

  it('restores the state from the hash on load (a reload)', async () => {
    at('/library/#q=witcher&f=pickable')
    render(undefined, 'hash-state')
    await screen.findByText(/3 of 5 games · by relevance|2 of 5 games · by relevance/)
    expect(search()).toHaveValue('witcher')
    expect(search()).toHaveAttribute('aria-expanded', 'false')
    expect(sort()).toBeDisabled()
    expect(screen.getByRole('checkbox', { name: 'Pickable only' })).toBeChecked()
    expect(titles()).toEqual(['The Witcher', 'The Witcher 2'])
  })

  it('restores the sort', async () => {
    at('/library/#sort=recent')
    render(undefined, 'hash-state')
    await screen.findByText('5 of 5 games')
    expect(sort()).toHaveValue('recent')
    expect(titles()[0]).toBe('The Witcher 2')
  })

  it('follows a hand-edited hash, and stops listening once detached', async () => {
    at('/library/')
    const el = render(undefined, 'hash-state')
    await screen.findByText('5 of 5 games')
    at('/library/#q=hollow')
    window.dispatchEvent(new HashChangeEvent('hashchange'))
    await waitFor(() => {
      expect(titles()).toEqual(['Hollow Knight'])
    })
    expect(search()).toHaveValue('hollow')
    window.dispatchEvent(new HashChangeEvent('hashchange')) // same query: input untouched
    const input = search()
    expect(input).toHaveValue('hollow')
    el.remove()
    at('/library/#q=witcher')
    window.dispatchEvent(new HashChangeEvent('hashchange'))
    expect(input).toHaveValue('hollow')
  })

  it('without hash-state never touches the URL', async () => {
    at('/picks/#keep')
    render()
    await screen.findByText('5 of 5 games')
    await userEvent.type(search(), 'hollow')
    expect(location.hash).toBe('#keep')
  })
})
