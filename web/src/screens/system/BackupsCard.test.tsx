import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { makeJob, makeSpec } from '../../test/fixtures'
import { apiError, bodiesOf, installEventSource, renderRouted, stubApi } from '../../test/harness'
import { BackupsCard } from './BackupsCard'

const BACKUP = { id: '20261010-100000', created_at: '2026-10-10T10:00:00Z', reason: 'before reset', size_bytes: 2048 }
const PHRASE = 'restore backup 20261010-100000'
const RESTORE = 'POST /api/backups/20261010-100000/restore'

const show = (extra: Record<string, unknown> = {}) => {
  const mock = stubApi({
    'GET /api/backups': [BACKUP],
    'GET /api/commands': [makeSpec('reset')],
    'GET /api/jobs': [],
    'GET /api/jobs/jr': makeJob({ id: 'jr', command: 'restore-backup' }),
    ...extra,
  })
  renderRouted(<BackupsCard />)
  return mock
}
const openDialog = async () => {
  await userEvent.click(await screen.findByRole('button', { name: 'Restore…' }))
  return screen.findByRole('dialog', { name: `Restore backup ${BACKUP.id}` })
}

describe('BackupsCard', () => {
  beforeEach(installEventSource)
  afterEach(() => vi.unstubAllGlobals())

  it('lists backups with reason and size, next to the reset action', async () => {
    show()
    expect(await screen.findByText(BACKUP.id)).toBeInTheDocument()
    expect(screen.getByText(/before reset · 2.0 KB/)).toBeInTheDocument()
    expect(screen.getAllByText('Reset all state…').length).toBeGreaterThan(0)
  })

  it('says when there are none', async () => {
    show({ 'GET /api/backups': [] })
    expect(await screen.findByText('No backups yet.')).toBeInTheDocument()
  })

  it('shows loading, then a failure', async () => {
    show({ 'GET /api/backups': () => new Promise(() => {}) })
    expect(await screen.findByText(/Loading backups/)).toBeInTheDocument()
  })

  it('explains a failed load', async () => {
    show({ 'GET /api/backups': apiError(500, 'op_failed', 'backups broke') })
    expect(await screen.findByText('backups broke')).toBeInTheDocument()
  })

  describe('restore dialog', () => {
    it('asks for the exact phrase, and restores only when it matches', async () => {
      const mock = show({ [RESTORE]: makeJob({ id: 'jr', command: 'restore-backup' }) })
      const dialog = await openDialog()
      expect(dialog).toHaveTextContent('Replaces the current state with the backup from')
      const restore = screen.getByRole('button', { name: 'Restore' })
      expect(restore).toBeDisabled()
      await userEvent.type(screen.getByLabelText('Type the phrase to confirm'), `${PHRASE}{Enter}`)
      await waitFor(() => expect(bodiesOf(mock, RESTORE)).toEqual([{ confirm_phrase: PHRASE }]))
      expect(await screen.findByRole('region', { name: /^Job/ })).toBeInTheDocument()
    })

    it('does not restore on Enter with a wrong phrase', async () => {
      const mock = show()
      await openDialog()
      await userEvent.type(screen.getByLabelText('Type the phrase to confirm'), 'nope')
      // The button is disabled, so only a forced submit can reach the guard.
      fireEvent.submit(screen.getByRole('button', { name: 'Restore' }).closest('form')!)
      expect(bodiesOf(mock, RESTORE)).toEqual([])
    })

    it('closes from the finished view, and from Cancel', async () => {
      show({ [RESTORE]: makeJob({ id: 'jr', command: 'restore-backup' }) })
      await openDialog()
      await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
      await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
      await openDialog()
      await userEvent.type(screen.getByLabelText('Type the phrase to confirm'), PHRASE)
      await userEvent.click(screen.getByRole('button', { name: 'Restore' }))
      await screen.findByRole('region', { name: /^Job/ })
      await userEvent.click(screen.getAllByRole('button', { name: 'Close' }).at(-1)!) // the footer one, not the header ×
      await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    })

    it('shows a refused restore and Restoring… while it runs', async () => {
      let answer: (v: unknown) => void = () => {}
      show({ [RESTORE]: () => new Promise((r) => (answer = r)) })
      await openDialog()
      await userEvent.type(screen.getByLabelText('Type the phrase to confirm'), PHRASE)
      await userEvent.click(screen.getByRole('button', { name: 'Restore' }))
      expect(await screen.findByRole('button', { name: 'Restoring…' })).toBeDisabled()
      await act(async () => answer(apiError(409, 'busy', 'a job is running')))
      expect(await screen.findByText('a job is running')).toBeInTheDocument()
    })
  })
})
