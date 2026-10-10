import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import type { ParamSpec } from '../api/contract'
import { ParamsForm } from './ParamsForm'
import type { ParamValues } from './params'

const SPECS: ParamSpec[] = [
  { name: 'app_id', label: 'Game', type: 'app_id', required: true },
  { name: 'days', label: 'Days', type: 'int', required: false, min: 1, max: 9, help: 'How long.' },
  { name: 'note', label: 'Note', type: 'string', required: false },
]
const GAMES = [{ app_id: 5, name: 'Five' }]

function Harness({ showErrors = false, disabled = false }) {
  const [values, setValues] = useState<ParamValues>({ app_id: '', days: '', note: '' })
  return <ParamsForm specs={SPECS} values={values} onChange={setValues} games={GAMES} showErrors={showErrors} disabled={disabled} />
}

describe('ParamsForm', () => {
  it('renders one labelled field per spec, marking the required ones', () => {
    render(<Harness />)
    expect(screen.getByLabelText(/Game/)).toHaveAttribute('list')
    expect(screen.getByLabelText('Days')).toHaveAttribute('type', 'number')
    expect(screen.getByLabelText('Days')).toHaveAttribute('min', '1')
    expect(screen.getByLabelText('Note')).toHaveAttribute('type', 'text')
    expect(screen.getByLabelText('Note')).not.toHaveAttribute('inputmode')
    expect(screen.getByLabelText(/Game/)).toHaveFocus()
    expect(screen.getByText('Type an app id or pick a game from the list.')).toBeInTheDocument()
    expect(screen.getByText('How long.')).toBeInTheDocument()
  })

  it('offers the known games in a datalist and names the chosen one', async () => {
    const { container } = render(<Harness />)
    expect(container.querySelector('datalist option')).toHaveValue('5')
    await userEvent.type(screen.getByLabelText(/Game/), '5')
    expect(container.querySelector('.field-help')).toHaveTextContent('Five')
  })

  it('shows errors only once asked to', async () => {
    const { rerender } = render(<Harness />)
    expect(screen.queryByText('Game is required.')).toBeNull()
    rerender(<Harness showErrors />)
    expect(screen.getByText('Game is required.')).toBeInTheDocument()
    expect(screen.getByLabelText(/Game/)).toHaveClass('input-bad')
    expect(screen.getByLabelText(/Game/)).toHaveAttribute('aria-invalid', 'true')
  })

  it('treats a value the form has not set yet as empty', () => {
    render(<ParamsForm specs={SPECS} values={{}} onChange={() => {}} games={GAMES} showErrors={false} disabled={false} />)
    expect(screen.getByLabelText('Note')).toHaveValue('')
  })

  it('disables every field', () => {
    render(<Harness disabled />)
    expect(screen.getByLabelText('Note')).toBeDisabled()
  })
})
