import { describe, expect, it, vi } from 'vitest'
import { copyButton } from './build'

// Currently RED: build.ts copyButton() calls navigator.clipboard.writeText
// without the `?.` the legacy CopyButton had, so a page without the
// Clipboard API (insecure context) throws a TypeError from the click
// handler. Goes green once the call is `navigator.clipboard?.writeText(...)`.
describe('copyButton without a clipboard', () => {
  it('does nothing', () => {
    vi.stubGlobal('navigator', {})
    const errors = vi.fn()
    window.addEventListener('error', errors)
    const btn = copyButton('abc', 'Copy it')
    btn.click()
    window.removeEventListener('error', errors)
    expect(errors).not.toHaveBeenCalled()
    expect(btn.textContent).toBe('Copy it')
  })
})
