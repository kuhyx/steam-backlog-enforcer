// Guard test (textgate-rework R6): the user's own icon words are the one
// visible text allowed outside the /words picker, and only exactly as the
// ledger draws them. Anything else in an `.icon-word` still counts.

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { makeBudget } from './factories'
import { makeJob, makeSpec, makeStatus } from './fixtures'
import { installEventSource, mount, stubApi } from './harness'
import { useIcons } from './iconLedger'
import { visibleWords } from './visibleWords'
import { notice } from '../ui/build'
import '../sections/dashboard'
import '../shell/jobIndicator'

beforeEach(installEventSource)

describe('textgate guard: icon words', () => {
  it('the dashboard paints the ledger words and nothing else', async () => {
    useIcons({
      'cmd.scan': { word: 'scan it' },
      'cmd.check': { word: 'look' },
      'job.state.running': { word: 'busy' },
    })
    stubApi({
      'GET /api/status': makeStatus(),
      'GET /api/budget': makeBudget(),
      'GET /api/jobs': [makeJob({ id: 'a', command: 'scan', state: 'running', summary: 'Scanned 12' })],
      'GET /api/commands': [makeSpec('check'), makeSpec('scan')],
    })
    const el = mount('<main><job-indicator></job-indicator><recent-jobs></recent-jobs></main>')
    await vi.waitFor(() => {
      expect(el.querySelectorAll('.icon-word').length).toBeGreaterThan(1)
    }, { timeout: 3000 })
    const painted = [...el.querySelectorAll('.icon-word')].map((w) => w.textContent)
    expect(painted).toEqual(expect.arrayContaining(['Scan it', 'Busy']))
    expect(visibleWords(el, ['Scanned 12'])).toEqual([])
  })

  it('a word the ledger does not hold still counts', () => {
    useIcons({ 'notice.info': { word: 'note' } })
    const el = notice('info', null)
    expect(visibleWords(el)).toEqual([])
    const word = el.querySelector('.icon-word')
    if (word) word.textContent = 'Smuggled'
    expect(visibleWords(el)).toEqual(['Smuggled'])
  })

  it('hidden words leave nothing to allow', () => {
    const el = notice('info', null)
    expect(el.querySelector('.icon-word')).toBeNull()
    expect(visibleWords(el)).toEqual([])
  })
})
