import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { PhraseField } from './PhraseField'

function Harness({ initial = '', autoFocus = false }: { initial?: string; autoFocus?: boolean }) {
  const [v, setV] = useState(initial)
  return <PhraseField phrase="reset it" value={v} onChange={setV} autoFocus={autoFocus} />
}

describe('PhraseField', () => {
  it('counts characters while the prefix is right', async () => {
    render(<Harness />)
    await userEvent.type(screen.getByLabelText('Type the phrase to confirm'), 'res')
    expect(screen.getByText('3 of 8 characters')).toBeInTheDocument()
    expect(screen.getByRole('textbox')).toHaveAttribute('aria-invalid', 'false')
  })

  it('marks a mismatch', async () => {
    render(<Harness />)
    await userEvent.type(screen.getByRole('textbox'), 'rx')
    expect(screen.getByText(/Does not match/)).toBeInTheDocument()
    expect(screen.getByRole('textbox')).toHaveClass('input-bad')
    expect(screen.getByRole('textbox')).toHaveAttribute('aria-invalid', 'true')
  })

  it('confirms the full phrase, ignoring surrounding whitespace', () => {
    render(<Harness initial=" reset it " />)
    expect(screen.getByText('Matches.')).toBeInTheDocument()
    expect(screen.getByRole('textbox')).toHaveClass('input-ok')
  })

  it('colours each target character by whether it was typed right', () => {
    const { container } = render(<Harness initial="rx" />)
    const spans = [...container.querySelectorAll('.phrase-target span')]
    expect(spans[0]).toHaveClass('ok')
    expect(spans[1]).toHaveClass('bad')
    expect(spans[2]).not.toHaveClass('ok')
  })

  it('blocks paste and drop', () => {
    render(<Harness />)
    const input = screen.getByRole('textbox')
    expect(fireEvent.paste(input)).toBe(false)
    expect(fireEvent.drop(input)).toBe(false)
  })

  it('focuses itself on request and shows the phrase to screen readers', () => {
    render(<Harness autoFocus />)
    expect(screen.getByRole('textbox')).toHaveFocus()
    expect(screen.getByText('Phrase: reset it')).toBeInTheDocument()
  })
})
