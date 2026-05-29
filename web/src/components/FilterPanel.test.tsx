import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { Filters } from '../types'
import { makeDataset, makeFilters } from '../test/factories'
import { FilterPanel } from './FilterPanel'

function setup(over: Partial<Filters> = {}) {
  const update = vi.fn()
  const onReset = vi.fn()
  render(
    <FilterPanel
      filters={makeFilters(over)}
      defaults={makeDataset().defaults}
      update={update}
      onReset={onReset}
    />,
  )
  return { update, onReset, user: userEvent.setup() }
}

describe('FilterPanel', () => {
  it('renders the Filters heading', () => {
    setup()
    expect(screen.getByRole('heading', { name: 'Filters' })).toBeInTheDocument()
  })

  it('switches the estimate basis when a segment is clicked', async () => {
    const { update, user } = setup()
    await user.click(screen.getByRole('button', { name: 'Rush' }))
    expect(update).toHaveBeenCalledWith({ basis: 'rush' })
  })

  it('switches ProtonDB to min-tier mode and reveals the tier select', async () => {
    const { update, user } = setup()
    await user.click(screen.getByRole('button', { name: 'Min tier' }))
    expect(update).toHaveBeenCalledWith({ protonMode: 'minTier' })
  })

  it('shows the tier dropdown when already in min-tier mode', () => {
    setup({ protonMode: 'minTier' })
    expect(screen.getByRole('combobox')).toBeInTheDocument()
  })

  it('switches ProtonDB back to playable mode', async () => {
    const { update, user } = setup({ protonMode: 'minTier' })
    await user.click(screen.getByRole('button', { name: /Playable \(CLI rule\)/i }))
    expect(update).toHaveBeenCalledWith({ protonMode: 'playable' })
  })

  it('toggles the include-no-data option', async () => {
    const { update, user } = setup()
    await user.click(screen.getByLabelText(/Include games with no HLTB data/i))
    expect(update).toHaveBeenCalledWith({ includeNoData: true })
  })

  it('reveals the fallback slider when no-data games are included', () => {
    setup({ includeNoData: true })
    expect(screen.getByText(/Fallback estimate/i)).toBeInTheDocument()
  })

  it('calls onReset when the reset button is clicked', async () => {
    const { onReset, user } = setup()
    await user.click(screen.getByRole('button', { name: /Reset to CLI defaults/i }))
    expect(onReset).toHaveBeenCalledTimes(1)
  })

  it('updates daily hours and min completions via sliders', () => {
    const { update } = setup()
    const sliders = screen.getAllByRole('slider')
    fireEvent.change(sliders[0], { target: { value: '8' } })
    expect(update).toHaveBeenCalledWith({ dailyHours: 8 })
    fireEvent.change(sliders[1], { target: { value: '40' } })
    expect(update).toHaveBeenCalledWith({ minCountComp: 40 })
  })

  it('updates advanced confidence and the max-hours cap', () => {
    const { update } = setup()
    const sliders = screen.getAllByRole('slider')
    fireEvent.change(sliders[2], { target: { value: '10' } })
    expect(update).toHaveBeenCalledWith({ minComp100: 10 })
    fireEvent.change(sliders[3], { target: { value: '25' } })
    expect(update).toHaveBeenCalledWith({ minConfidenceSum: 25 })
    fireEvent.change(sliders[4], { target: { value: '50' } })
    expect(update).toHaveBeenCalledWith({ maxHoursPerGame: 50 })
  })

  it('switches the playtime mode', async () => {
    const { update, user } = setup()
    await user.click(screen.getByRole('button', { name: 'Started' }))
    expect(update).toHaveBeenCalledWith({ playtimeMode: 'started' })
  })

  it('updates and clears the target date', async () => {
    const { update, user } = setup({ targetDate: '2030-01-01' })
    const date = document.querySelector('input[type=date]')
    fireEvent.change(date as Element, { target: { value: '2031-02-03' } })
    expect(update).toHaveBeenCalledWith({ targetDate: '2031-02-03' })
    await user.click(screen.getByRole('button', { name: 'Clear' }))
    expect(update).toHaveBeenCalledWith({ targetDate: '' })
  })

  it('updates the min tier and treat-missing toggle in min-tier mode', async () => {
    const { update, user } = setup({ protonMode: 'minTier' })
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'silver' } })
    expect(update).toHaveBeenCalledWith({ protonMinTier: 'silver' })
    await user.click(screen.getByLabelText(/Keep games with no ProtonDB data/i))
    expect(update).toHaveBeenCalledWith({ protonTreatMissingAsPass: false })
  })

  it('updates the fallback estimate when no-data games are included', () => {
    const { update } = setup({ includeNoData: true })
    const sliders = screen.getAllByRole('slider')
    fireEvent.change(sliders[sliders.length - 1], { target: { value: '30' } })
    expect(update).toHaveBeenCalledWith({ fallbackHours: 30 })
  })

  it('shows the hours-cap value when maxHoursPerGame is set', () => {
    setup({ maxHoursPerGame: 50 })
    expect(screen.getByText('50 h')).toBeInTheDocument()
  })
})
