import { beforeEach, describe, expect, it } from 'vitest'
import { installEventSource } from '../test/harness'
import { mountJob } from '../test/jobHelpers'
import { resultMarks } from './resultMarks'

beforeEach(installEventSource)

describe('resultMarks', () => {
  it('marks a dry run and a fast install skipped for a running game', () => {
    expect(resultMarks({ app_id: 3, dry_run: true, fast_install_skipped: null })).toEqual(['result.dry-run'])
    expect(resultMarks({ app_id: 3, dry_run: false, fast_install_skipped: 'game_running' })).toEqual(['result.game-running'])
  })
  it('ignores anything that is not install data', () => {
    expect(resultMarks(undefined)).toEqual([])
    expect(resultMarks(null)).toEqual([])
    expect(resultMarks('x')).toEqual([])
    expect(resultMarks({ dry_run: 'yes', fast_install_skipped: 'other' })).toEqual([])
  })
})

describe('<job-progress> result marks', () => {
  it('paints the game-running mark beside the result', () => {
    const { el, send } = mountJob()
    send('result', { ok: true, summary: 'x', data: { app_id: 3, dry_run: false, fast_install_skipped: 'game_running' } })
    const mark = el.querySelector('[data-icon="result.game-running"]')
    expect(mark).not.toBeNull()
    expect(mark).toHaveAttribute('title')
    expect(el.querySelector('[data-icon="result.dry-run"]')).toBeNull()
  })
})
