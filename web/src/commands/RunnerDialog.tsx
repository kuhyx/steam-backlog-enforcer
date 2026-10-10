import { useMutation, useQuery } from '@tanstack/react-query'
import { Link, useRouter } from '@tanstack/react-router'
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiFailure, startJob } from '../api/client'
import type { CommandName, CommandSpec } from '../api/contract'
import type { PendingAction } from '../api/jobContract'
import { q, queryClient } from '../api/queries'
import { JobProgress } from '../jobs/JobProgress'
import { Dialog } from '../ui/Dialog'
import { CommandLine, ErrorNotice, Loading, Notice } from '../ui/Notice'
import { commandLabel, fillPhrase, findCommand, phraseMatches } from './catalog'
import { enforcePreset } from './enforcePreset'
import { PendingCountdown } from './PendingCountdown'
import { ParamsForm } from './ParamsForm'
import { initialValues, paramError, toParams } from './params'
import { PhraseField } from './PhraseField'
import { useGameLookup } from './useGameLookup'

type Phase = { k: 'form' } | { k: 'pending'; pending: PendingAction } | { k: 'job'; id: string }

/** Recovery commands the UI offers when the root daemon is down. */
const FALLBACK: Partial<Record<CommandName, string>> = {
  'gaming-unblock': 'sudo ./run.sh gaming-unblock',
}

interface Props {
  name: CommandName
  preset?: Record<string, number | string>
  onClose: () => void
}

export function RunnerDialog({ name, preset, onClose }: Props) {
  const router = useRouter()
  const { data: commands, error: loadError } = useQuery(q.commands)
  const spec = findCommand(commands, name)
  // An armed countdown dies with the dialog: close, Escape and any
  // navigation all drop it server-side.
  const armed = useRef<string | null>(null)
  const close = useCallback(() => {
    if (armed.current) void api.dropPending(armed.current).catch(() => {})
    armed.current = null
    onClose()
  }, [onClose])
  useEffect(() => router.subscribe('onBeforeNavigate', close), [router, close])

  return (
    <Dialog open title={commandLabel(name)} onClose={close} wide>
      {spec ? (
        <Runner {...enforcePreset(spec, preset)} preset={preset} onClose={close} onArmed={(id) => (armed.current = id)} />
      ) : loadError ? (
        <ErrorNotice error={loadError} />
      ) : commands ? (
        <Notice tone="danger" title="Not in the server catalog">The server does not offer "{name}".</Notice>
      ) : (
        <Loading what="commands" />
      )}
    </Dialog>
  )
}

interface RunnerProps {
  spec: CommandSpec
  /** Params sent as-is, outside the form (see enforcePreset). */
  fixed: Record<string, number | string>
  preset?: Record<string, number | string>
  onClose: () => void
  onArmed: (pendingId: string | null) => void
}

function Runner({ spec, fixed, preset, onClose, onArmed }: RunnerProps) {
  const { games, ctx } = useGameLookup()
  const [values, setValues] = useState(() => initialValues(spec.params, preset))
  const [typed, setTyped] = useState('')
  const [showErrors, setShowErrors] = useState(false)
  const [phase, setPhase] = useState<Phase>({ k: 'form' })

  const start = useMutation({
    mutationFn: startJob,
    onSuccess: (out) => {
      void queryClient.invalidateQueries({ queryKey: ['jobs'] })
      onArmed(out.kind === 'pending' ? out.pending.id : null)
      setPhase(out.kind === 'job' ? { k: 'job', id: out.job.id } : { k: 'pending', pending: out.pending })
    },
  })

  const params = { ...fixed, ...toParams(spec.params, values) }
  const errors = spec.params.map((p) => paramError(p, values[p.name] ?? '', games)).filter(Boolean)
  const phrase = spec.friction ? fillPhrase(spec.friction.phrase_template, params, ctx) : null
  const countdown = spec.friction?.countdown_seconds
  const locked = spec.locked_reason !== null
  const canSubmit =
    !locked && errors.length === 0 && (!phrase || (phrase.missing.length === 0 && phraseMatches(phrase.text, typed)))

  const submit = () => {
    setShowErrors(true)
    if (!canSubmit) return
    // Every friction command sends its phrase here; a countdown one
    // (gaming-reset) needs it to arm and is asked again at commit.
    start.mutate({ command: spec.name, params, ...(phrase ? { confirm_phrase: typed } : {}) })
  }

  if (phase.k === 'job') {
    return (
      <div className="stack">
        <JobProgress jobId={phase.id} />
        <div className="actions">
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Close (job keeps running)
          </button>
          <Link to="/jobs/$jobId" params={{ jobId: phase.id }} className="btn btn-ghost">
            Open in Jobs
          </Link>
        </div>
      </div>
    )
  }

  if (phase.k === 'pending') {
    return (
      <PendingCountdown
        pending={phase.pending}
        onCommitted={(job) => {
          onArmed(null)
          setPhase({ k: 'job', id: job.id })
        }}
        onCancel={() => {
          onArmed(null)
          onClose()
        }}
        onRearm={() => {
          onArmed(null)
          setTyped('')
          setPhase({ k: 'form' })
        }}
      />
    )
  }

  const failure = start.error instanceof ApiFailure ? start.error : null
  return (
    <form
      className="stack"
      noValidate
      onSubmit={(e) => {
        e.preventDefault()
        submit()
      }}
    >
      <p className="m0">{spec.description}</p>
      <div className="tags">
        {spec.privileged && <span className="pill pill-neutral">Runs as root via the daemon</span>}
        {spec.mutating ? <span className="pill pill-neutral">Changes state</span> : <span className="pill pill-neutral">Read-only</span>}
        {spec.cancellable && <span className="pill pill-neutral">Cancellable</span>}
        {countdown ? <span className="pill pill-warning">{Math.round(countdown / 60)} min countdown</span> : null}
      </div>
      {locked && <Notice tone="warning" title="Locked">{spec.locked_reason}</Notice>}
      <ParamsForm specs={spec.params} values={values} onChange={setValues} games={games} showErrors={showErrors} disabled={locked} />
      {phrase && phrase.missing.length > 0 && (
        <Notice tone="info">Fill in the fields above to see the exact phrase ({phrase.missing.join(', ')}).</Notice>
      )}
      {phrase && phrase.missing.length === 0 && !locked && (
        <PhraseField phrase={phrase.text} value={typed} onChange={setTyped} autoFocus={spec.params.length === 0} />
      )}
      {start.error && (
        <ErrorNotice error={start.error}>
          {failure?.code === 'daemon_unreachable' && FALLBACK[spec.name] && (
            <>
              <p className="m0">Run it from a terminal instead:</p>
              <CommandLine command={FALLBACK[spec.name]!} />
            </>
          )}
        </ErrorNotice>
      )}
      <div className="actions">
        <button type="submit" className={phrase ? 'btn btn-danger' : 'btn btn-primary'} disabled={!canSubmit || start.isPending} autoFocus={!phrase && spec.params.length === 0}>
          {start.isPending ? 'Starting…' : countdown ? 'Arm countdown' : `Run ${spec.name}`}
        </button>
        <button type="button" className="btn btn-ghost" onClick={onClose}>
          Cancel
        </button>
      </div>
    </form>
  )
}
