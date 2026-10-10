// Typed HTTP client for the web-control API (DOCS-web-control-api.md).
// Every non-GET carries the per-launch token; failures become ApiFailure
// with the server's error code so screens can explain them precisely.

import {
  ENDPOINTS,
  TOKEN_HEADER,
  TOKEN_META,
  type CommandSpec,
  type DaemonStatus,
  type InstalledPayload,
  type LibraryPayload,
  type ServerHealth,
  type SetupRequest,
  type SetupStatus,
  type StateBackup,
  type StatsPayload,
  type StatusPayload,
} from './contract'
import type { ApiError, ApiErrorCode, Job, JobRequest, PendingAction, PromptAnswer } from './jobContract'

/** `network` = no response at all; `http` = a non-JSON error response. */
export type FailureCode = ApiErrorCode | 'network' | 'http'

export class ApiFailure extends Error {
  readonly code: FailureCode
  readonly status: number
  constructor(code: FailureCode, message: string, status: number) {
    super(message)
    this.name = 'ApiFailure'
    this.code = code
    this.status = status
  }
}

/** The token the server injected into index.html; empty when absent. */
export function sessionToken(): string {
  return document.querySelector<HTMLMetaElement>(`meta[name="${TOKEN_META}"]`)?.content ?? ''
}

const RELOAD_KEY = 'sbe-token-reload-at'
/** A second bad_token within this window means a reload did not help. */
const RELOAD_GUARD_MS = 30_000

/**
 * A restarted server mints a new token, so this page's copy is dead: reload
 * once to fetch index.html with the new one. The sessionStorage timestamp
 * stops a loop when the reload does not fix it (e.g. dev without a token file).
 */
function reloadForNewToken(): void {
  try {
    const last = Number(sessionStorage.getItem(RELOAD_KEY) ?? 0)
    if (Date.now() - last < RELOAD_GUARD_MS) return
    sessionStorage.setItem(RELOAD_KEY, String(Date.now()))
  } catch {
    return // No storage, no loop guard: never reload blind.
  }
  window.location.reload()
}

export async function request<T>(method: string, path: string, body?: unknown, keepalive = false): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (method !== 'GET') headers[TOKEN_HEADER] = sessionToken()
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  let resp: Response
  try {
    resp = await fetch(path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      keepalive,
    })
  } catch (e) {
    throw new ApiFailure('network', e instanceof Error ? e.message : String(e), 0)
  }
  const text = await resp.text()
  if (!resp.ok) {
    let parsed: Partial<ApiError> = {}
    try {
      parsed = JSON.parse(text) as Partial<ApiError>
    } catch {
      // Not JSON: a proxy error page or a crashed handler.
    }
    // keepalive requests come from a page that is already closing.
    if (parsed.error === 'bad_token' && !keepalive) reloadForNewToken()
    if (parsed.error) throw new ApiFailure(parsed.error, parsed.message ?? '', resp.status)
    throw new ApiFailure('http', `${resp.status} ${resp.statusText}`, resp.status)
  }
  return (text ? JSON.parse(text) : undefined) as T
}

const get = <T>(path: string) => request<T>('GET', path)

export type JobStart = { kind: 'job'; job: Job } | { kind: 'pending'; pending: PendingAction }

export const api = {
  status: () => get<StatusPayload>(ENDPOINTS.status),
  stats: () => get<StatsPayload>(ENDPOINTS.stats),
  installed: () => get<InstalledPayload>(ENDPOINTS.installed),
  library: () => get<LibraryPayload>(ENDPOINTS.library),
  commands: () => get<CommandSpec[]>(ENDPOINTS.commands),
  setup: () => get<SetupStatus>(ENDPOINTS.setup),
  saveSetup: (req: SetupRequest) => request<SetupStatus>('POST', ENDPOINTS.setup, req),
  daemon: () => get<DaemonStatus>(ENDPOINTS.daemon),
  server: () => get<ServerHealth>(ENDPOINTS.server),
  restartServer: () => request<void>('POST', ENDPOINTS.serverRestart),
  backups: () => get<StateBackup[]>(ENDPOINTS.backups),
  restoreBackup: (id: string, phrase: string) =>
    request<Job>('POST', ENDPOINTS.backupRestore(encodeURIComponent(id)), { confirm_phrase: phrase }),
  jobs: () => get<Job[]>(ENDPOINTS.jobs),
  job: (id: string) => get<Job>(ENDPOINTS.job(id)),
  answer: (id: string, answer: PromptAnswer) => request<void>('POST', ENDPOINTS.jobAnswer(id), answer),
  cancelJob: (id: string) => request<void>('POST', ENDPOINTS.jobCancel(id)),
  heartbeat: (id: string) => request<PendingAction>('POST', ENDPOINTS.pendingHeartbeat(id)),
  commit: (id: string, phrase: string) =>
    request<Job>('POST', ENDPOINTS.pendingCommit(id), { confirm_phrase: phrase }),
  /** `keepalive` lets the DELETE survive the page being closed. */
  dropPending: (id: string, keepalive = false) =>
    request<void>('DELETE', ENDPOINTS.pending(id), undefined, keepalive),
}

/** POST /api/jobs: 201 → Job, 202 → PendingAction (countdown commands). */
export async function startJob(req: JobRequest): Promise<JobStart> {
  const out = await request<Job | PendingAction>('POST', ENDPOINTS.jobs, req)
  return 'ready_at' in out ? { kind: 'pending', pending: out } : { kind: 'job', job: out }
}
