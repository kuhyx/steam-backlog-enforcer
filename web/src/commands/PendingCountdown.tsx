import { useMutation } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api, ApiFailure } from '../api/client'
import type { Job, PendingAction } from '../api/jobContract'
import { ProgressBar } from '../jobs/ProgressBar'
import { clock } from '../ui/format'
import { ErrorNotice, Notice } from '../ui/Notice'
import { useNow } from '../ui/useNow'
import { phraseMatches } from './catalog'
import { PhraseField } from './PhraseField'

interface Props {
  pending: PendingAction
  onCommitted: (job: Job) => void
  onCancel: () => void
  onRearm: () => void
}

/**
 * Armed countdown (gaming-reset): heartbeats at half the server's interval so
 * one slow request never lapses it, a countdown driven by the server's
 * `ready_at` (not a local timer), then the phrase is retyped to commit.
 * Closing the page drops the action with a keepalive DELETE.
 */
export function PendingCountdown({ pending: initial, onCommitted, onCancel, onRearm }: Props) {
  const [pending, setPending] = useState(initial)
  const [lastBeat, setLastBeat] = useState(() => Date.now())
  const [beatError, setBeatError] = useState<unknown>(null)
  const [phrase, setPhrase] = useState('')
  const now = useNow(250)

  useEffect(() => {
    const everyMs = Math.max(1000, (initial.heartbeat_interval_seconds * 1000) / 2)
    const id = setInterval(() => {
      api.heartbeat(initial.id).then(
        (p) => {
          setPending(p)
          setLastBeat(Date.now())
          setBeatError(null)
        },
        (e: unknown) => setBeatError(e),
      )
    }, everyMs)
    const drop = () => void api.dropPending(initial.id, true).catch(() => {})
    window.addEventListener('pagehide', drop)
    return () => {
      clearInterval(id)
      window.removeEventListener('pagehide', drop)
    }
  }, [initial.id, initial.heartbeat_interval_seconds])

  const commit = useMutation({ mutationFn: () => api.commit(pending.id, phrase), onSuccess: onCommitted })
  const cancel = useMutation({ mutationFn: () => api.dropPending(pending.id), onSettled: onCancel })

  const armed = Date.parse(pending.armed_at)
  const ready = Date.parse(pending.ready_at)
  const left = Math.max(0, (ready - now) / 1000)
  const isReady = left <= 0
  const lapsed = beatError instanceof ApiFailure && beatError.code === 'pending_lapsed'
  const sinceBeat = Math.round((now - lastBeat) / 1000)

  if (lapsed) {
    return (
      <div className="stack">
        <ErrorNotice error={beatError} />
        <div className="actions">
          <button type="button" className="btn btn-primary" onClick={onRearm} autoFocus>
            Arm again
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="stack countdown">
      <div className="countdown-clock" aria-live="off">
        <span className="countdown-num">{clock(left)}</span>
        <span className="muted">{isReady ? 'Ready to commit' : 'until commit unlocks'}</span>
      </div>
      <ProgressBar fraction={Math.min(1, (now - armed) / (ready - armed))} label="Countdown" tone={isReady ? 'success' : 'warning'} />
      <p className="field-help">
        Keep this window open. Heartbeat every {Math.round(pending.heartbeat_interval_seconds / 2)} s · last {sinceBeat} s ago
        {beatError !== null && <span className="text-danger"> · heartbeat failing, retrying</span>}
      </p>
      <p className="sr-only" aria-live="polite">
        {isReady ? 'Countdown finished. Retype the phrase to commit.' : ''}
      </p>
      {isReady ? (
        <form
          className="stack"
          onSubmit={(e) => {
            e.preventDefault()
            if (phraseMatches(pending.phrase, phrase)) commit.mutate()
          }}
        >
          <PhraseField phrase={pending.phrase} value={phrase} onChange={setPhrase} autoFocus label="Retype the phrase to commit" />
          {commit.error && <ErrorNotice error={commit.error} />}
          <div className="actions">
            <button type="submit" className="btn btn-danger" disabled={!phraseMatches(pending.phrase, phrase) || commit.isPending}>
              {commit.isPending ? 'Committing…' : 'Commit'}
            </button>
            <button type="button" className="btn btn-ghost" onClick={() => cancel.mutate()}>
              Cancel
            </button>
          </div>
        </form>
      ) : (
        <>
          <Notice tone="warning">Closing this dialog, navigating away or closing the tab cancels the countdown.</Notice>
          <div className="actions">
            <button type="button" className="btn btn-ghost" onClick={() => cancel.mutate()} autoFocus>
              {cancel.isPending ? 'Cancelling…' : 'Cancel countdown'}
            </button>
          </div>
        </>
      )}
    </div>
  )
}
