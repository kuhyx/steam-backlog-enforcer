import { fireEvent, getByLabelText, getByRole, getByText, queryByRole } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { makeDataset, makeFilters } from '../../test/factories'
import type { Filters } from '../../types'
import { FilterPanel } from './filterPanel'

function setup(over: Partial<Filters> = {}) {
  const update = vi.fn()
  const onReset = vi.fn()
  const panel = new FilterPanel(makeDataset().defaults, update, onReset)
  panel.sync(makeFilters(over))
  document.body.append(panel.el)
  return { el: panel.el, panel, update, onReset, user: userEvent.setup() }
}
const slider = (el: HTMLElement, name: string) => getByRole(el, 'slider', { name })

describe('FilterPanel', () => {
  it('renders the Filters heading and the CLI default hint', () => {
    const { el } = setup()
    expect(getByRole(el, 'heading', { name: 'Filters' })).toBeInTheDocument()
    expect(getByText(el, 'Higher = more reliable HLTB times (CLI default 15).')).toBeInTheDocument()
  })

  it('switches the estimate basis when a segment is clicked', async () => {
    const { el, update, user } = setup()
    expect(getByRole(el, 'button', { name: 'Leisure' })).toHaveClass('seg active')
    await user.click(getByRole(el, 'button', { name: 'Rush' }))
    expect(update).toHaveBeenCalledWith({ basis: 'rush' })
  })

  it('switches ProtonDB to min-tier mode; the tier select is hidden until then', async () => {
    const { el, update, user } = setup()
    expect(queryByRole(el, 'combobox')).toBeNull()
    await user.click(getByRole(el, 'button', { name: 'Min tier' }))
    expect(update).toHaveBeenCalledWith({ protonMode: 'minTier' })
  })

  it('shows the tier dropdown when already in min-tier mode', () => {
    const { el } = setup({ protonMode: 'minTier', protonMinTier: 'silver' })
    expect(getByRole(el, 'combobox')).toHaveValue('silver')
  })

  it('switches ProtonDB back to playable mode', async () => {
    const { el, update, user } = setup({ protonMode: 'minTier' })
    await user.click(getByRole(el, 'button', { name: /Playable \(CLI rule\)/i }))
    expect(update).toHaveBeenCalledWith({ protonMode: 'playable' })
  })

  it('toggles the include-no-data option', async () => {
    const { el, update, user } = setup()
    await user.click(getByLabelText(el, /Include games with no HLTB data/i))
    expect(update).toHaveBeenCalledWith({ includeNoData: true })
  })

  it('reveals the fallback slider when no-data games are included', () => {
    const { el, panel } = setup()
    expect(queryByRole(el, 'slider', { name: 'Fallback estimate' })).toBeNull()
    panel.sync(makeFilters({ includeNoData: true }))
    expect(getByText(el, /Fallback estimate/i)).toBeVisible()
  })

  it('calls onReset when the reset button is clicked', async () => {
    const { el, onReset, user } = setup()
    await user.click(getByRole(el, 'button', { name: /Reset to CLI defaults/i }))
    expect(onReset).toHaveBeenCalledTimes(1)
  })

  it('updates daily hours and min completions via sliders', () => {
    const { el, update } = setup()
    fireEvent.input(slider(el, 'Daily play time'), { target: { value: '8' } })
    expect(update).toHaveBeenCalledWith({ dailyHours: 8 })
    fireEvent.input(slider(el, 'Min HLTB completions'), { target: { value: '40' } })
    expect(update).toHaveBeenCalledWith({ minCountComp: 40 })
  })

  it('updates advanced confidence and the max-hours cap', () => {
    const { el, update } = setup()
    fireEvent.input(slider(el, 'Min polled completionist times'), { target: { value: '10' } })
    expect(update).toHaveBeenCalledWith({ minComp100: 10 })
    fireEvent.input(slider(el, 'Min confidence sum'), { target: { value: '25' } })
    expect(update).toHaveBeenCalledWith({ minConfidenceSum: 25 })
    fireEvent.input(slider(el, 'Max time per game'), { target: { value: '50' } })
    expect(update).toHaveBeenCalledWith({ maxHoursPerGame: 50 })
  })

  it('switches the playtime mode', async () => {
    const { el, update, user } = setup()
    await user.click(getByRole(el, 'button', { name: 'Started' }))
    expect(update).toHaveBeenCalledWith({ playtimeMode: 'started' })
  })

  it('updates and clears the target date', async () => {
    const { el, update, user } = setup({ targetDate: '2030-01-01' })
    const date = getByLabelText(el, 'Target finish date')
    expect(date).toHaveValue('2030-01-01')
    fireEvent.input(date, { target: { value: '2031-02-03' } })
    expect(update).toHaveBeenCalledWith({ targetDate: '2031-02-03' })
    await user.click(getByRole(el, 'button', { name: 'Clear' }))
    expect(update).toHaveBeenCalledWith({ targetDate: '' })
  })

  it('hides Clear without a target date', () => {
    expect(queryByRole(setup().el, 'button', { name: 'Clear' })).toBeNull()
  })

  it('updates the min tier and treat-missing toggle in min-tier mode', async () => {
    const { el, update, user } = setup({ protonMode: 'minTier' })
    fireEvent.change(getByRole(el, 'combobox'), { target: { value: 'silver' } })
    expect(update).toHaveBeenCalledWith({ protonMinTier: 'silver' })
    await user.click(getByLabelText(el, /Keep games with no ProtonDB data/i))
    expect(update).toHaveBeenCalledWith({ protonTreatMissingAsPass: false })
  })

  it('updates the fallback estimate when no-data games are included', () => {
    const { el, update } = setup({ includeNoData: true })
    fireEvent.input(slider(el, 'Fallback estimate'), { target: { value: '30' } })
    expect(update).toHaveBeenCalledWith({ fallbackHours: 30 })
  })

  it('shows each slider value, the hours cap as off or N h', () => {
    const { el, panel } = setup()
    expect(getByText(el, '4 h/day')).toBeInTheDocument()
    expect(getByText(el, '∞')).toBeInTheDocument()
    panel.sync(makeFilters({ maxHoursPerGame: 50 }))
    expect(getByText(el, '50 h')).toBeInTheDocument()
  })

  it('syncs values in place without replacing the controls', () => {
    const { el, panel } = setup()
    const before = slider(el, 'Daily play time')
    panel.sync(makeFilters({ dailyHours: 9 }))
    expect(slider(el, 'Daily play time')).toBe(before)
    expect(before).toHaveValue('9')
  })
})
