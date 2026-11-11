// Guard test (textgate-rework R6): the reworked web UI pieces paint no chrome
// words. Spoken-only text (aria-label, .sr-only, aria-hidden) and content the
// caller passes in (game names, server messages) are allowed.

import { beforeEach, describe, expect, it } from 'vitest'
import { installEventSource } from './harness'
import { mountJob } from './jobHelpers'
import { visibleWords } from './visibleWords'
import { ApiFailure } from '../api/client'
import { timelineChart } from '../lib/charts/timeline'
import { errorNotice, loading } from '../ui/build'
import type { EstimateResult } from '../estimate'
import type { Filters } from '../types'


beforeEach(installEventSource)

describe('textgate guard: no chrome words', () => {
  it('job progress: queued, waiting and finished states', () => {
    const { el, send } = mountJob()
    expect(visibleWords(el)).toEqual([])
    send('state', { state: 'waiting_input' })
    expect(visibleWords(el)).toEqual([])
    send('state', { state: 'failed' })
    expect(visibleWords(el)).toEqual([])
  })

  it('timeline chart with nothing in scope', () => {
    const result = { included: [], excluded: [] } as unknown as EstimateResult
    const filters = { basis: 'leisure' } as unknown as Filters
    const chart = timelineChart(result, filters, { pace_games_per_day: 0 } as never)
    document.body.append(chart)
    expect(visibleWords(chart)).toEqual([])
  })

  it('error notice shows only the icon and the server message', () => {
    const el = errorNotice(new ApiFailure('busy', 'boom', 409))
    expect(visibleWords(el, ['boom'])).toEqual([])
    expect(el.getAttribute('aria-label')).toMatch(/Another job is running/)
  })

  it('loading indicator', () => {
    expect(visibleWords(loading('games'))).toEqual([])
  })
})
