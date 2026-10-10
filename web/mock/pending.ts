// Two-phase countdown actions (gaming-reset): arm → heartbeats → commit.
// Lapses when a heartbeat is missed by more than 15 s, like the daemon does.

import { randomUUID } from 'node:crypto'
import type { CommandName } from '../src/api/contract.ts'
import type { PendingAction } from '../src/api/jobContract.ts'
import { HttpError } from './http.ts'

const HEARTBEAT_SECONDS = 10
const GRACE_MS = 15_000

interface Armed {
  action: PendingAction
  lastBeat: number
}

const pending = new Map<string, Armed>()

export function arm(command: CommandName, phrase: string, countdownSeconds: number): PendingAction {
  for (const p of pending.values()) {
    if (p.action.command === command) throw new HttpError(409, 'countdown_running', 'A countdown for this command is already armed.')
  }
  const now = Date.now()
  const action: PendingAction = {
    id: randomUUID().slice(0, 8),
    command,
    phrase,
    armed_at: new Date(now).toISOString(),
    ready_at: new Date(now + countdownSeconds * 1000).toISOString(),
    heartbeat_interval_seconds: HEARTBEAT_SECONDS,
  }
  pending.set(action.id, { action, lastBeat: now })
  return action
}

function live(id: string): Armed {
  const p = pending.get(id)
  if (!p) throw new HttpError(410, 'pending_lapsed', 'This countdown is gone (lapsed or cancelled). Arm it again.')
  if (Date.now() - p.lastBeat > HEARTBEAT_SECONDS * 1000 + GRACE_MS) {
    pending.delete(id)
    throw new HttpError(410, 'pending_lapsed', 'A heartbeat was missed, so the countdown lapsed. Arm it again.')
  }
  return p
}

export function heartbeat(id: string): PendingAction {
  const p = live(id)
  p.lastBeat = Date.now()
  return p.action
}

export function take(id: string): PendingAction {
  const p = live(id)
  if (Date.now() < Date.parse(p.action.ready_at)) {
    throw new HttpError(409, 'countdown_running', 'The countdown has not finished yet.')
  }
  return p.action
}

export function drop(id: string): void {
  pending.delete(id)
}
