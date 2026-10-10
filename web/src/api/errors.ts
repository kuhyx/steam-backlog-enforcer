// Human explanations for every ApiErrorCode. The server's own message is
// shown underneath; this adds what the user should do about it.

import { ApiFailure, type FailureCode } from './client'

const EXPLAIN: Record<FailureCode, { title: string; hint: string }> = {
  bad_token: { title: 'Session expired', hint: 'The server restarted with a new token. The page reloads itself once; if this stays, reload it.' },
  bad_origin: { title: 'Blocked by origin check', hint: 'Open the UI from the address the server prints, not a copy.' },
  bad_host: { title: 'Blocked by host check', hint: 'Use http://127.0.0.1:8000 or http://localhost:8000.' },
  unknown_command: { title: 'Unknown command', hint: 'The UI and server versions differ. Restart the server from System.' },
  invalid_params: { title: 'Invalid input', hint: 'Fix the highlighted values and try again.' },
  not_found: { title: 'Not found', hint: 'It no longer exists (pruned from history or deleted). Refresh the list.' },
  wrong_phrase: { title: 'Phrase did not match', hint: 'Type the phrase exactly, including case and spacing.' },
  locked: { title: 'Locked', hint: 'A manual-pick or total-block lock forbids this right now.' },
  busy: { title: 'Another job is running', hint: 'Only one state-changing job runs at a time. Wait for it to finish.' },
  countdown_running: { title: 'Countdown still running', hint: 'Wait for the countdown to finish before committing.' },
  pending_lapsed: { title: 'Countdown lapsed', hint: 'A heartbeat was missed (tab asleep or offline). Arm it again.' },
  daemon_unreachable: { title: 'Root daemon unreachable', hint: 'Privileged actions need the enforcer daemon. Check System.' },
  rate_limited: { title: 'Rate limited', hint: 'This action was used recently. Try again later.' },
  not_cancellable: { title: 'Cannot cancel', hint: 'This command cannot be stopped once started.' },
  op_failed: { title: 'Action failed', hint: 'The daemon or the job process hit an error. See the job log or the daemon journal on System.' },
  server_stale: { title: 'Server is restarting', hint: 'It was running outdated code and restarts on the current code. Retry in a few seconds.' },
  unsupported: { title: 'Not supported here', hint: 'The enforcer daemon cannot do this in its current mode.' },
  network: { title: 'Server not reachable', hint: 'Is it running? Start it with ./run.sh serve.' },
  http: { title: 'Unexpected server error', hint: 'Check the server log.' },
}

export interface Explained {
  code: FailureCode
  title: string
  hint: string
  detail: string
}

export function explain(err: unknown): Explained {
  if (err instanceof ApiFailure) {
    return { code: err.code, ...EXPLAIN[err.code], detail: err.message }
  }
  const detail = err instanceof Error ? err.message : String(err)
  return { code: 'http', ...EXPLAIN.http, detail }
}
