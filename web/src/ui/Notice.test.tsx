import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiFailure } from '../api/client'
import { CommandLine, CopyButton, Empty, ErrorNotice, Loading, Notice } from './Notice'

describe('Notice', () => {
  it('is a polite status by default and an alert when it is danger', () => {
    const { rerender } = render(<Notice title="T">body</Notice>)
    expect(screen.getByRole('status')).toHaveTextContent('Tbody')
    rerender(<Notice tone="danger" />)
    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(document.querySelector('.notice-title')).toBeNull()
    expect(document.querySelector('.notice-text')).toBeNull()
  })

  it('ErrorNotice shows title, detail, hint and extras', () => {
    render(
      <ErrorNotice error={new ApiFailure('locked', 'pick lock', 423)}>
        <span>extra</span>
      </ErrorNotice>,
    )
    expect(screen.getByText('Locked')).toBeInTheDocument()
    expect(screen.getByText('pick lock')).toBeInTheDocument()
    expect(screen.getByText(/forbids this right now/)).toBeInTheDocument()
    expect(screen.getByText('extra')).toBeInTheDocument()
  })

  it('ErrorNotice omits an empty detail', () => {
    render(<ErrorNotice error={new ApiFailure('locked', '', 423)} />)
    expect(document.querySelectorAll('.notice-text p')).toHaveLength(1)
  })

  it('Loading and Empty render their text', () => {
    render(
      <>
        <Loading what="jobs" />
        <Empty>nothing</Empty>
      </>,
    )
    expect(screen.getByRole('status')).toHaveTextContent('Loading jobs…')
    expect(screen.getByText('nothing')).toBeInTheDocument()
  })
})

describe('CopyButton', () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('copies, says so, then reverts', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    render(<CopyButton text="abc" />)
    await userEvent.click(screen.getByRole('button', { name: 'Copy' }))
    expect(writeText).toHaveBeenCalledWith('abc')
    expect(await screen.findByRole('button', { name: 'Copied' })).toBeInTheDocument()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100)
    })
    expect(screen.getByRole('button', { name: 'Copy' })).toBeInTheDocument()
  })

  it('does nothing without a clipboard', async () => {
    vi.stubGlobal('navigator', {})
    render(<CopyButton text="abc" label="Copy it" />)
    await userEvent.click(screen.getByRole('button', { name: 'Copy it' }))
    expect(screen.getByRole('button', { name: 'Copy it' })).toBeInTheDocument()
  })

  it('CommandLine shows the command next to a copy button', () => {
    render(<CommandLine command="sudo ./run.sh x" />)
    expect(screen.getByText('sudo ./run.sh x')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Copy' })).toBeInTheDocument()
  })
})
