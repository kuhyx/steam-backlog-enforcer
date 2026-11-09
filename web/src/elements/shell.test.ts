import { describe, expect, it, vi } from 'vitest'

const boot = vi.hoisted(() => vi.fn())
vi.mock('../shell/boot', () => ({ boot }))

describe('shell entry', () => {
  it('registers the shell elements and boots the page', async () => {
    await import('./shell')
    for (const tag of ['command-button', 'command-card', 'command-palette', 'runner-dialog', 'job-progress', 'game-browser', 'health-badges', 'stale-banner', 'job-indicator']) {
      expect(customElements.get(tag), tag).toBeDefined()
    }
    expect(boot).toHaveBeenCalledOnce()
  })
})
