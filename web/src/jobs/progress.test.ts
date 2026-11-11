import { describe, expect, it } from 'vitest'
import type { JobState } from '../api/jobContract'
import { progressBar, stateBadge } from './progress'

describe('stateBadge', () => {
  it.each<[JobState, string]>([
    ['queued', 'neutral'],
    ['running', 'accent'],
    ['waiting_input', 'warning'],
    ['succeeded', 'success'],
    ['failed', 'danger'],
    ['cancelled', 'neutral'],
  ])('labels %s', (state, tone) => {
    const el = stateBadge(state)
    expect(el.getAttribute('aria-label')).toBe(state)
    expect(el.className).toBe(`pill pill-${tone}`)
    expect(el.querySelector('.pill-icon')).not.toBeNull()
  })
})

describe('progressBar', () => {
  it('is a determinate progressbar with a rounded percentage', () => {
    const el = progressBar(0.456, 'Scan')
    expect(el).toHaveAttribute('role', 'progressbar')
    expect(el).toHaveAttribute('aria-valuenow', '46')
    expect(el).toHaveAttribute('aria-valuemin', '0')
    expect(el).toHaveAttribute('aria-valuemax', '100')
    expect(el).toHaveAttribute('aria-valuetext', 'Scan: 46%')
    expect(el).toHaveAttribute('aria-label', 'Scan')
    expect(el.className).toBe('bar bar-accent')
    expect((el.firstElementChild as HTMLElement).style.width).toBe('46%')
  })

  it('is an indeterminate sweep without a fraction', () => {
    const el = progressBar(null, 'Scan')
    expect(el).toHaveClass('bar-indeterminate')
    expect(el).not.toHaveAttribute('aria-valuenow')
    expect(el).toHaveAttribute('aria-valuetext', 'Scan: working')
    expect((el.firstElementChild as HTMLElement).style.width).toBe('')
  })

  it('clamps out-of-range fractions', () => {
    expect(progressBar(2, 'x')).toHaveAttribute('aria-valuenow', '100')
    expect(progressBar(-1, 'x')).toHaveAttribute('aria-valuenow', '0')
  })

  it('takes a tone and a small size', () => {
    const el = progressBar(0.5, 'x', 'danger', true)
    expect(el.className).toBe('bar bar-danger bar-small')
  })
})
