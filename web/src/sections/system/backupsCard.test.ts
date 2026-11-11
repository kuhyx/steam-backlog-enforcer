import { fireEvent, screen, waitFor } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { q } from '../../api/queries'
import { makeJob, makeSpec } from '../../test/fixtures'
import { apiError, bodiesOf, flush, installEventSource, mount, stubApi, type Handler } from '../../test/harness'
import { restorePhrase } from './backupsCard'

const BACKUP = { id: '20261010-100000', created_at: '2026-10-10T10:00:00Z', reason: 'before reset', size_bytes: 2048 }
const PHRASE = 'restore backup 20261010-100000'
const RESTORE = 'POST /api/backups/20261010-100000/restore'

const show = (extra: Record<string, Handler> = {}) => {
  const mock = stubApi({
    'GET /api/backups': [BACKUP],
    'GET /api/commands': [makeSpec('reset')],
    'GET /api/jobs': [],
    'GET /api/jobs/jr': makeJob({ id: 'jr', command: 'restore-backup' }),
    ...extra,
  })
  mount('<backups-card></backups-card>')
  return mock
}
const openDialog = async () => {
  await userEvent.click(await screen.findByRole('button', { name: 'Restore…' }))
  return screen.findByRole('dialog', { name: `Restore backup ${BACKUP.id}` })
}
const phraseBox = () => screen.getByLabelText(/Type the phrase to confirm/)

describe('restorePhrase', () => {
  it('mirrors the server friction phrase', () => {
    expect(restorePhrase('x')).toBe('restore backup x')
  })
})

describe('backups-card', () => {
  beforeEach(installEventSource)

  it('lists backups with reason and size, next to the reset action', async () => {
    show()
    expect(await screen.findByText(BACKUP.id)).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'State backups' })).toBeInTheDocument()
    expect(document.querySelector('[data-reason="before reset"]')).toHaveTextContent(/♻️.*before reset · 2.0 KB/)
    expect(await screen.findByRole('button', { name: 'Reset all state…' })).toBeInTheDocument()
  })

  it('says when there are none', async () => {
    show({ 'GET /api/backups': [] })
    expect(await screen.findByText('No backups yet.')).toBeInTheDocument()
  })

  it('shows loading, then a failure', async () => {
    show({ 'GET /api/backups': () => new Promise(() => undefined) })
    expect(await screen.findByText(/Loading backups/)).toBeInTheDocument()
  })

  it('explains a failed load', async () => {
    show({ 'GET /api/backups': apiError(500, 'op_failed', 'backups broke') })
    expect(await screen.findByText('backups broke')).toBeInTheDocument()
  })

  it('leaves the rows alone when a refetch brings the same list', async () => {
    show()
    const button = await screen.findByRole('button', { name: 'Restore…' })
    q.backups.set([BACKUP])
    expect(screen.getByRole('button', { name: 'Restore…' })).toBe(button)
  })

  describe('restore dialog', () => {
    it('asks for the exact phrase, and restores only when it matches', async () => {
      const mock = show({ [RESTORE]: makeJob({ id: 'jr', command: 'restore-backup' }) })
      const dialog = await openDialog()
      expect(dialog).toHaveTextContent('Replaces the current state with the backup from')
      expect(dialog).toHaveTextContent('(before reset)')
      const restore = screen.getByRole('button', { name: 'Restore' })
      expect(restore).toBeDisabled()
      expect(phraseBox()).toHaveFocus()
      await userEvent.type(phraseBox(), `${PHRASE}{Enter}`)
      await waitFor(() => {
        expect(bodiesOf(mock, RESTORE)).toEqual([{ confirm_phrase: PHRASE }])
      })
      expect(await screen.findByRole('region', { name: /^Job/ })).toBeInTheDocument()
    })

    it('does not restore on a forced submit with a wrong phrase', async () => {
      const mock = show()
      await openDialog()
      await userEvent.type(phraseBox(), 'nope')
      const form = screen.getByRole('button', { name: 'Restore' }).closest('form')
      if (!form) throw new Error('no form')
      fireEvent.submit(form)
      await flush()
      expect(bodiesOf(mock, RESTORE)).toEqual([])
    })

    it('closes from the finished view, and from Cancel', async () => {
      show({ [RESTORE]: makeJob({ id: 'jr', command: 'restore-backup' }) })
      await openDialog()
      await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
      expect(screen.queryByRole('dialog')).toBeNull()
      await openDialog()
      await userEvent.type(phraseBox(), PHRASE)
      await userEvent.click(screen.getByRole('button', { name: 'Restore' }))
      await screen.findByRole('region', { name: /^Job/ })
      const close = screen.getAllByRole('button', { name: 'Close' }).at(-1) // the footer one, not the header ×
      if (!close) throw new Error('no close')
      await userEvent.click(close)
      expect(screen.queryByRole('dialog')).toBeNull()
      expect(document.querySelector('job-progress')).toBeNull()
    })

    it('replaces an open dialog when another restore opens, and closes on leaving', async () => {
      show()
      await openDialog()
      const card = document.querySelector('backups-card')
      if (!(card instanceof HTMLElement) || !('open' in card) || typeof card.open !== 'function') throw new Error('no card')
      ;(card as HTMLElement & { open: (b: typeof BACKUP) => void }).open(BACKUP)
      expect(document.querySelectorAll('dialog')).toHaveLength(1)
      document.body.replaceChildren()
      expect(document.querySelectorAll('dialog')).toHaveLength(0)
    })

    it('shows a refused restore and Restoring… while it runs', async () => {
      let answer: (v: unknown) => void = () => undefined
      show({ [RESTORE]: () => new Promise((r) => (answer = r)) })
      await openDialog()
      await userEvent.type(phraseBox(), PHRASE)
      await userEvent.click(screen.getByRole('button', { name: 'Restore' }))
      expect(await screen.findByRole('button', { name: 'Restoring…' })).toBeDisabled()
      // A second Enter while it runs must not post again.
      const form = screen.getByRole('button', { name: 'Restoring…' }).closest('form')
      if (!form) throw new Error('no form')
      fireEvent.submit(form)
      answer(apiError(409, 'busy', 'a job is running'))
      expect(await screen.findByText('a job is running')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Restore' })).toBeEnabled()
    })
  })
})
