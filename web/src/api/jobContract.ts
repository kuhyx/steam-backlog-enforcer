// Job, prompt, pending-action and error shapes of the web control API.
// Split from contract.ts (file-length cap); same frozen contract, same
// prose spec: DOCS-web-control-api.md. Change both together.

import type { CommandName } from './contract'

export type JobState =
  | 'queued'
  | 'running'
  | 'waiting_input'
  | 'succeeded'
  | 'failed'
  | 'cancelled'

export interface JobProgress {
  step: number
  total: number | null
  label: string
  item?: string
  eta_seconds?: number
}

export interface Job {
  id: string
  command: CommandName
  params: Record<string, number | string>
  state: JobState
  created_at: string
  started_at: string | null
  ended_at: string | null
  exit_code: number | null
  progress: JobProgress | null
  summary: string | null
}

export interface JobRequest {
  command: CommandName
  params: Record<string, number | string>
  /**
   * Required up front for every friction command. Countdown commands
   * (gaming-reset) need it here to arm AND again at commit.
   */
  confirm_phrase?: string
}

/** `game`: pick from the library browser; answer an app id, or '' to go back. */
export type PromptKind = 'choice' | 'confirm' | 'phrase' | 'text' | 'game'

export interface PromptOption {
  value: string
  label: string
  detail?: string
}

interface JobEventBase {
  seq: number
  ts: string
}

export type JobEvent =
  | (JobEventBase & { type: 'state'; state: JobState })
  | (JobEventBase & { type: 'log'; level: 'info' | 'warning' | 'error'; message: string })
  | (JobEventBase & { type: 'progress' } & JobProgress)
  | (JobEventBase & {
      type: 'prompt'
      prompt_id: string
      kind: PromptKind
      message: string
      options?: PromptOption[]
      phrase?: string
      default?: string
      /** `game` prompts: the only app ids the job will accept. */
      app_ids?: number[]
    })
  | (JobEventBase & { type: 'result'; ok: boolean; summary: string; data?: unknown })

export interface PromptAnswer {
  prompt_id: string
  value: string
}

export interface PendingAction {
  id: string
  command: CommandName
  phrase: string
  armed_at: string
  ready_at: string
  /** Send a heartbeat at least this often or the action lapses. */
  heartbeat_interval_seconds: number
}

export type ApiErrorCode =
  | 'bad_token'
  | 'bad_origin'
  | 'bad_host'
  | 'unknown_command'
  | 'invalid_params'
  /** Unknown job, backup or endpoint (404). */
  | 'not_found'
  | 'wrong_phrase'
  | 'locked'
  | 'busy'
  | 'countdown_running'
  | 'pending_lapsed'
  | 'daemon_unreachable'
  | 'rate_limited'
  | 'not_cancellable'
  /** Daemon op raised, or a job process could not be started (502). */
  | 'op_failed'
  /** The server runs outdated code and is restarting itself (503). */
  | 'server_stale'
  /** Daemon cannot do this here, e.g. restart while unsupervised. */
  | 'unsupported'

export interface ApiError {
  error: ApiErrorCode
  message: string
}

/** Every endpoint, so client and mock server share one list. */
