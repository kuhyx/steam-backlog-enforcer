// Route table for the mock API. Behaviour follows DOCS-web-control-api.md:
// token on every non-GET, `busy`/`locked`/`wrong_phrase`/`daemon_unreachable`
// /`not_found`/`server_stale` errors, 201 Job vs 202 PendingAction (the
// phrase is checked at arm and again at commit), SSE with `after=<seq>` resume.

import type { IncomingMessage, ServerResponse } from 'node:http'
import type { CommandName } from '../src/api/contract.ts'
import type { JobRequest } from '../src/api/jobContract.ts'
import { budget } from './budget.ts'
import { catalog, findSpec } from './catalog.ts'
import { HttpError, fillPhrase, phraseMatches, readJson, send, validateParams } from './http.ts'
import { answer, cancel, jobs, listJobs, runningMutating, startJob } from './jobs.ts'
import { arm, drop, heartbeat, take } from './pending.ts'
import { SCRIPTS, gamingReset, restoreBackup } from './scripts.ts'
import { streamEvents } from './sse.ts'
import { daemonStatus, dataset, library, serverHealth, setupStatus, stats, status, world } from './world.ts'

type Ctx = { req: IncomingMessage; res: ServerResponse; url: URL; m: RegExpMatchArray }
type Handler = (ctx: Ctx) => unknown | Promise<unknown>
const routes: [string, RegExp, Handler][] = []
const on = (method: string, path: RegExp, h: Handler) => routes.push([method, path, h])

const RESTORE_PHRASE = 'restore backup {backup_id}'

on('GET', /^\/api\/dataset$/, () => dataset())
on('GET', /^\/api\/budget$/, ({ url }) => budget(url.searchParams.get('demo') === '1'))
on('GET', /^\/api\/status$/, () => status())
on('GET', /^\/api\/stats$/, () => stats())
on('GET', /^\/api\/installed$/, () => ({ games: world.installed }))
on('GET', /^\/api\/library$/, () => library())
// Offline: no covers, so every card shows its title tile.
on('GET', /^\/api\/art\/(\d+)$/, () => {
  throw new HttpError(404, 'not_found', 'No cover art in the mock.')
})
on('GET', /^\/api\/commands$/, () => catalog())
on('GET', /^\/api\/setup$/, () => setupStatus())
on('POST', /^\/api\/setup$/, async ({ req }) => {
  const body = await readJson(req)
  const key = String(body.steam_api_key ?? '')
  const id = String(body.steam_id ?? '')
  if (!/^[0-9A-F]{32}$/i.test(key)) throw new HttpError(400, 'invalid_params', 'Steam rejected the API key (expect 32 hex characters).')
  if (!/^7656\d{13}$/.test(id)) throw new HttpError(400, 'invalid_params', 'Steam ID must be the 17-digit SteamID64 (starts with 7656).')
  world.configured = true
  world.steamId = id
  return setupStatus()
})
on('GET', /^\/api\/daemon$/, () => daemonStatus())
on('GET', /^\/api\/server$/, () => serverHealth())
on('POST', /^\/api\/server\/restart$/, ({ res }) => {
  setTimeout(() => {
    world.serverStartedAt = Date.now()
    world.stale = false
  }, 2500)
  send(res, 202)
})
on('GET', /^\/api\/backups$/, () => world.backups)
on('POST', /^\/api\/backups\/([^/]+)\/restore$/, async ({ req, res, m }) => {
  const id = decodeURIComponent(m[1])
  if (!world.backups.some((b) => b.id === id)) throw new HttpError(404, 'not_found', `No backup ${id}.`)
  const body = await readJson(req)
  if (!phraseMatches(fillPhrase(RESTORE_PHRASE, {}, { backup_id: id }), body.confirm_phrase)) {
    throw new HttpError(400, 'wrong_phrase', 'The phrase does not match.')
  }
  guardBusy()
  send(res, 201, startJob('restore-backup', { backup_id: id }, restoreBackup(id), true))
})
on('GET', /^\/api\/jobs$/, () => listJobs())
on('POST', /^\/api\/jobs$/, async ({ req, res }) => {
  const body = (await readJson(req)) as Partial<JobRequest>
  const spec = findSpec(String(body.command))
  if (!spec || spec.kind !== 'job') throw new HttpError(400, 'unknown_command', `Unknown command "${body.command}".`)
  if (spec.locked_reason) throw new HttpError(409, 'locked', spec.locked_reason)
  const params = validateParams(spec, body.params)
  if (spec.privileged && world.daemon === 'unreachable') {
    throw new HttpError(503, 'daemon_unreachable', 'The root daemon is not answering on /run/steam-backlog-enforcer/ctl.sock.')
  }
  if (spec.name === 'enforce' && params.mode === 'restart' && world.restartAvailableAt && world.restartAvailableAt > Date.now()) {
    throw new HttpError(429, 'rate_limited', 'The daemon was restarted less than 10 minutes ago.')
  }
  if (spec.friction) {
    const expected = fillPhrase(spec.friction.phrase_template, params)
    if (!phraseMatches(expected, body.confirm_phrase)) throw new HttpError(400, 'wrong_phrase', 'The phrase does not match.')
    if (spec.friction.countdown_seconds) {
      send(res, 202, arm(spec.name, expected, spec.friction.countdown_seconds))
      return
    }
  }
  if (spec.mutating) guardBusy()
  const script = SCRIPTS[spec.name as CommandName]
  if (!script) throw new HttpError(400, 'unknown_command', `No runner for "${spec.name}".`)
  send(res, 201, startJob(spec.name, params, script, spec.mutating))
})
on('GET', /^\/api\/jobs\/([^/]+)$/, ({ m }) => job(m[1]).job)
on('GET', /^\/api\/jobs\/([^/]+)\/events$/, ({ req, res, url, m }) => {
  streamEvents(req, res, job(m[1]), Number(url.searchParams.get('after') ?? 0))
})
on('POST', /^\/api\/jobs\/([^/]+)\/answer$/, async ({ req, res, m }) => {
  const body = await readJson(req)
  if (!answer(job(m[1]).job.id, String(body.prompt_id), String(body.value ?? ''))) {
    throw new HttpError(400, 'invalid_params', 'That prompt is not waiting for an answer.')
  }
  send(res, 204)
})
on('POST', /^\/api\/jobs\/([^/]+)\/cancel$/, ({ res, m }) => {
  const mj = job(m[1])
  if (!findSpec(mj.job.command)?.cancellable) throw new HttpError(409, 'not_cancellable', 'This command cannot be cancelled once started.')
  cancel(mj.job.id)
  send(res, 204)
})
on('POST', /^\/api\/pending\/([^/]+)\/heartbeat$/, ({ m }) => heartbeat(m[1]))
on('POST', /^\/api\/pending\/([^/]+)\/commit$/, async ({ req, res, m }) => {
  const action = take(m[1])
  const body = await readJson(req)
  if (!phraseMatches(action.phrase, body.confirm_phrase)) throw new HttpError(400, 'wrong_phrase', 'The phrase does not match.')
  guardBusy()
  drop(action.id)
  send(res, 201, startJob(action.command, {}, gamingReset, true))
})
on('DELETE', /^\/api\/pending\/([^/]+)$/, ({ res, m }) => {
  drop(m[1])
  send(res, 204)
})
// Dev-only scenario switch for screenshots: lock modes, dead daemon, short countdown.
on('POST', /^\/__mock\/scenario$/, async ({ req }) => {
  const body = await readJson(req)
  Object.assign(world, body)
  return { ok: true }
})

function job(id: string) {
  const mj = jobs.get(id)
  if (!mj) throw new HttpError(404, 'not_found', `No job ${id}.`)
  return mj
}

function guardBusy(): void {
  const busy = runningMutating()
  if (busy) throw new HttpError(409, 'busy', `"${busy.job.command}" is still running; wait for it to finish.`)
}

export async function handle(req: IncomingMessage, res: ServerResponse, token: string): Promise<boolean> {
  const url = new URL(req.url ?? '/', 'http://mock')
  if (!url.pathname.startsWith('/api/') && !url.pathname.startsWith('/__mock/')) return false
  try {
    // Like the real server retiring on outdated code: every /api/* refuses
    // except the health route (and the mock's restart, which clears it).
    if (world.stale && url.pathname.startsWith('/api/') && !/^\/api\/server(\/restart)?$/.test(url.pathname)) {
      throw new HttpError(503, 'server_stale', 'This server is running outdated code and is restarting on current code.')
    }
    const isStream = url.pathname.endsWith('/events')
    const given = isStream ? url.searchParams.get('token') : req.headers['x-sbe-token']
    if ((req.method !== 'GET' || isStream) && given !== token) {
      throw new HttpError(403, 'bad_token', 'Missing or wrong session token.')
    }
    for (const [method, path, h] of routes) {
      const m = url.pathname.match(path)
      if (m && method === req.method) {
        const out = await h({ req, res, url, m })
        if (out !== undefined) send(res, 200, out)
        return true
      }
    }
    throw new HttpError(404, 'not_found', `No such endpoint: ${req.method} ${url.pathname}`)
  } catch (e) {
    if (e instanceof HttpError) send(res, e.status, { error: e.code, message: e.message })
    else send(res, 500, { error: 'invalid_params', message: String(e) })
    return true
  }
}
