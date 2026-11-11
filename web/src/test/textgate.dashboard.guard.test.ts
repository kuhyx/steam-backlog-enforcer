// Guard test (textgate-rework R6): the dashboard and gaming panels paint
// glyphs, numbers and game names only; every label and sentence is spoken.

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { makeBudget } from './factories'
import { makeJob, makeSpec, makeStatus } from './fixtures'
import { installEventSource, mount, stubApi } from './harness'
import { visibleWords } from './visibleWords'
import '../sections/dashboard'
import '../sections/gaming/panel'
import '../shell/health'
import '../shell/jobIndicator'

const daemon = {
  state: 'running',
  started_at: null,
  pid: 1,
  journal_tail: [],
  restart_available_at: null,
  fast_installs: [{ app_id: 1, name: 'Celeste', phase: 'downloading depot 3/8', percent: 40, elapsed_seconds: 60 }],
}

beforeEach(installEventSource)

describe('textgate guard: dashboard + gaming', () => {
  it('paints no chrome words once everything has loaded', async () => {
    const budget = makeBudget()
    stubApi({
      'GET /api/status': makeStatus({ total_block: { active: true, days_remaining: 1, until: null } }),
      'GET /api/daemon': daemon,
      'GET /api/server': { stale: true, started_at: null, version: '1.2.3' },
      'GET /api/budget': budget,
      'GET /api/jobs': [makeJob({ id: 'a', command: 'scan', state: 'running', summary: 'Scanned 12' })],
      'GET /api/commands': [makeSpec('check'), makeSpec('scan')],
    })
    const el = mount(
      '<main><health-badges></health-badges><stale-banner></stale-banner><job-indicator></job-indicator>' +
        '<dashboard-status></dashboard-status><budget-glance></budget-glance><fast-installs></fast-installs>' +
        '<recent-jobs></recent-jobs><budget-panel></budget-panel></main>',
    )
    await vi.waitFor(() => {
      expect(el.querySelector('.budget-rules')).not.toBeNull()
      expect(el.querySelector('.hero-game')).not.toBeNull()
      expect(el.querySelector('.banner')).not.toBeNull()
    }, { timeout: 3000 })
    const content = [
      ...budget.legend.map((e) => e.label),
      ...(budget.today?.games.map((g) => g.label) ?? []),
      budget.session.game_name,
      budget.session.billing_label,
      budget.rules.masked_launchers.join(', '),
      makeStatus().current_game_name ?? '',
      'Celeste',
      // Chart bar tooltips are "<day> · <game>: <duration>": all content.
      ...[...el.querySelectorAll('svg title')].map((t) => t.textContent.trim()),
    ]
    expect(visibleWords(el, content)).toEqual([])
  })
})
