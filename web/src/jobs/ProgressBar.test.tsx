import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { JobState } from '../api/jobContract'
import { ProgressBar, StateBadge } from './ProgressBar'

describe('StateBadge', () => {
  it.each<[JobState, string, string]>([
    ['queued', 'Queued', 'neutral'],
    ['running', 'Running', 'accent'],
    ['waiting_input', 'Needs your input', 'warning'],
    ['succeeded', 'Succeeded', 'success'],
    ['failed', 'Failed', 'danger'],
    ['cancelled', 'Cancelled', 'neutral'],
  ])('%s reads %s in the %s tone', (state, text, tone) => {
    render(<StateBadge state={state} />)
    expect(screen.getByText(text)).toHaveClass(`pill-${tone}`)
  })
})

describe('ProgressBar', () => {
  it('is a determinate progressbar with a percentage', () => {
    render(<ProgressBar fraction={0.256} label="Scan" />)
    const bar = screen.getByRole('progressbar', { name: 'Scan' })
    expect(bar).toHaveAttribute('aria-valuenow', '26')
    expect(bar).toHaveAttribute('aria-valuetext', 'Scan: 26%')
    expect(bar).toHaveClass('bar-accent')
    expect(bar).not.toHaveClass('bar-indeterminate', 'bar-small')
    expect(bar.firstElementChild).toHaveStyle({ width: '26%' })
  })

  it('is indeterminate without a fraction', () => {
    render(<ProgressBar fraction={null} label="Scan" tone="warning" small />)
    const bar = screen.getByRole('progressbar')
    expect(bar).not.toHaveAttribute('aria-valuenow')
    expect(bar).toHaveAttribute('aria-valuetext', 'Scan: working')
    expect(bar).toHaveClass('bar-indeterminate', 'bar-small', 'bar-warning')
  })

  it('clamps out-of-range fractions', () => {
    const { rerender } = render(<ProgressBar fraction={4} label="x" />)
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '100')
    rerender(<ProgressBar fraction={-1} label="x" />)
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '0')
  })
})
