import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../../api/client'
import type { StateBackup } from '../../api/contract'
import { q, queryClient } from '../../api/queries'
import { phraseMatches } from '../../commands/catalog'
import { CommandButton } from '../../commands/CommandCard'
import { PhraseField } from '../../commands/PhraseField'
import { JobProgress } from '../../jobs/JobProgress'
import { bytes, dateTime } from '../../ui/format'
import { Dialog } from '../../ui/Dialog'
import { Empty, ErrorNotice, Loading } from '../../ui/Notice'
import { Card } from '../../ui/Page'

// Not in any CommandSpec (restore is not a CLI command), so the UI has to
// know it. Mirrors FRICTION["restore-backup"] in _friction.py.
const RESTORE_PHRASE = (id: string) => `restore backup ${id}`

function RestoreDialog({ backup, onClose }: { backup: StateBackup; onClose: () => void }) {
  const [typed, setTyped] = useState('')
  const phrase = RESTORE_PHRASE(backup.id)
  const restore = useMutation({
    mutationFn: () => api.restoreBackup(backup.id, typed),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['jobs'] }),
  })
  return (
    <Dialog open title={`Restore backup ${backup.id}`} onClose={onClose} wide>
      {restore.data ? (
        <div className="stack">
          <JobProgress jobId={restore.data.id} />
          <div className="actions">
            <button type="button" className="btn btn-ghost" onClick={onClose}>Close</button>
          </div>
        </div>
      ) : (
        <form
          className="stack"
          onSubmit={(e) => {
            e.preventDefault()
            if (phraseMatches(phrase, typed)) restore.mutate()
          }}
        >
          <p className="m0">
            Replaces the current state with the backup from {dateTime(backup.created_at)} ({backup.reason}).
          </p>
          <PhraseField phrase={phrase} value={typed} onChange={setTyped} autoFocus />
          {restore.error && <ErrorNotice error={restore.error} />}
          <div className="actions">
            <button type="submit" className="btn btn-danger" disabled={!phraseMatches(phrase, typed) || restore.isPending}>
              {restore.isPending ? 'Restoring…' : 'Restore'}
            </button>
            <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
          </div>
        </form>
      )}
    </Dialog>
  )
}

export function BackupsCard() {
  const { data, error } = useQuery(q.backups)
  const [restoring, setRestoring] = useState<StateBackup | null>(null)
  return (
    <Card title="State backups" aside={<CommandButton name="reset" label="Reset all state…" />}>
      <p className="field-help m0">Reset takes a timestamped backup first, so it can be undone here.</p>
      {error && <ErrorNotice error={error} />}
      {!data && !error && <Loading what="backups" />}
      {data?.length === 0 && <Empty>No backups yet.</Empty>}
      <ul className="rows">
        {data?.map((b) => (
          <li key={b.id} className="row">
            <span className="mono">{b.id}</span>
            <span className="muted grow">{dateTime(b.created_at)} · {b.reason} · {bytes(b.size_bytes)}</span>
            <button type="button" className="btn btn-ghost btn-small" onClick={() => setRestoring(b)}>
              Restore…
            </button>
          </li>
        ))}
      </ul>
      {restoring && <RestoreDialog backup={restoring} onClose={() => setRestoring(null)} />}
    </Card>
  )
}
