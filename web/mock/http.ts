// Small HTTP helpers shared by the mock route handlers.

import type { IncomingMessage, ServerResponse } from 'node:http'
import type { CommandSpec, ParamSpec } from '../src/api/contract.ts'
import type { ApiErrorCode } from '../src/api/jobContract.ts'
import { nameOf } from './games.ts'
import { gameName, world } from './world.ts'

export class HttpError extends Error {
  readonly status: number
  readonly code: ApiErrorCode
  constructor(status: number, code: ApiErrorCode, message: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

export function send(res: ServerResponse, status: number, body?: unknown): void {
  res.statusCode = status
  if (body === undefined) {
    res.end()
    return
  }
  res.setHeader('Content-Type', 'application/json')
  res.end(JSON.stringify(body))
}

export async function readJson(req: IncomingMessage): Promise<Record<string, unknown>> {
  const chunks: Buffer[] = []
  for await (const chunk of req) chunks.push(chunk as Buffer)
  const text = Buffer.concat(chunks).toString('utf8')
  if (!text) return {}
  try {
    return JSON.parse(text) as Record<string, unknown>
  } catch {
    throw new HttpError(400, 'invalid_params', 'Body is not valid JSON.')
  }
}

/** Mirror of `_friction.phrase_matches`: only surrounding whitespace is forgiven. */
export function phraseMatches(expected: string, typed: unknown): boolean {
  return typeof typed === 'string' && typed.trim() === expected
}

export function fillPhrase(template: string, params: Record<string, number | string>, extra: Record<string, string> = {}): string {
  const fields: Record<string, string> = {
    count: String(world.installed.filter((g) => !g.assigned && !g.protected).length),
    ...Object.fromEntries(Object.entries(params).map(([k, v]) => [k, String(v)])),
    ...extra,
  }
  if (params.app_id !== undefined) fields.game_name = gameName(Number(params.app_id))
  return template.replace(/\{(\w+)\}/g, (_, key: string) => fields[key] ?? `{${key}}`)
}

function checkParam(p: ParamSpec, raw: unknown): number | string | undefined {
  if (raw === undefined || raw === '') {
    if (p.required && p.default === undefined) throw new HttpError(400, 'invalid_params', `${p.label} is required.`)
    return p.default
  }
  if (p.type === 'string') return String(raw)
  const n = Number(raw)
  if (!Number.isInteger(n)) throw new HttpError(400, 'invalid_params', `${p.label} must be a whole number.`)
  if (p.min !== undefined && n < p.min) throw new HttpError(400, 'invalid_params', `${p.label} must be at least ${p.min}.`)
  if (p.max !== undefined && n > p.max) throw new HttpError(400, 'invalid_params', `${p.label} must be at most ${p.max}.`)
  if (p.type === 'app_id' && nameOf(n) === null) {
    throw new HttpError(400, 'invalid_params', `App ${n} is not in your library.`)
  }
  return n
}

export function validateParams(spec: CommandSpec, raw: unknown): Record<string, number | string> {
  const input = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>
  const out: Record<string, number | string> = {}
  for (const p of spec.params) {
    const v = checkParam(p, input[p.name])
    if (v !== undefined) out[p.name] = v
  }
  if (spec.name === 'enforce' && out.mode !== 'restart' && out.mode !== 'demo') {
    throw new HttpError(400, 'invalid_params', 'Mode must be "restart" or "demo".')
  }
  return out
}
