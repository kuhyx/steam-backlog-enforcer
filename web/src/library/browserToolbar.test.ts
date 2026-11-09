import { screen, waitFor, within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { render, search, sort, titles, withLibrary } from '../test/browserHelpers'

describe('GameBrowser toolbar', () => {
  beforeEach(() => {
    withLibrary()
  })

  it('sorts by the chosen key', async () => {
    render()
    await screen.findByText('5 of 5 games')
    await userEvent.selectOptions(sort(), 'recent')
    await waitFor(() => {
      expect(titles()[0]).toBe('The Witcher 2')
    })
    await userEvent.selectOptions(sort(), 'hltb')
    await waitFor(() => {
      expect(titles()[0]).toBe('Hollow Knight')
    })
  })

  it('filters', async () => {
    render()
    await screen.findByText('5 of 5 games')
    const box = (name: string) => screen.getByRole('checkbox', { name })
    await userEvent.click(box('Installed only'))
    await waitFor(() => {
      expect(titles()).toEqual(['The Witcher 2'])
    })
    await userEvent.click(box('Installed only'))
    await userEvent.click(box('Pickable only'))
    await waitFor(() => {
      expect(titles()).not.toContain('The Witcher 3')
    })
    await userEvent.click(box('Hide completed'))
    await waitFor(() => {
      expect(titles()).not.toContain('The Witcher')
    })
  })

  it('"wicher" finds the Witcher titles by relevance and locks the sort', async () => {
    render()
    await screen.findByText('5 of 5 games')
    const input = search()
    await userEvent.type(input, 'wicher')
    // The grid trails the box by a frame: wait for the final keystroke's grid.
    await waitFor(() => {
      expect(titles()).toEqual(['The Witcher', 'The Witcher 2', 'The Witcher 3'])
    })
    screen.getByText(/by relevance/)
    expect(sort()).toBeDisabled()
    expect(search()).toBe(input)
    expect(input).toHaveFocus()
    expect(within(screen.getByRole('listbox')).getAllByRole('option')).toHaveLength(3)
  })

  it('"witcher 3" does not return Age of Empires III', async () => {
    render()
    await screen.findByText('5 of 5 games')
    await userEvent.type(search(), 'witcher 3')
    await waitFor(() => {
      expect(titles()[0]).toBe('The Witcher 3')
    })
    expect(titles()).not.toContain('Age of Empires III')
  })

  it('an app id finds that game', async () => {
    render()
    await screen.findByText('5 of 5 games')
    await userEvent.type(search(), '5')
    await waitFor(() => {
      expect(titles()[0]).toBe('Hollow Knight')
    })
  })

  it('builds its toolbar once across a re-attach', async () => {
    const el = render()
    await screen.findByText('5 of 5 games')
    const input = search()
    el.remove()
    document.body.append(el)
    await waitFor(() => {
      expect(titles()).toHaveLength(5)
    })
    expect(search()).toBe(input)
    expect(screen.getAllByRole('combobox', { name: 'Search your games' })).toHaveLength(1)
  })
})
