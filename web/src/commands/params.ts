// Pure helpers behind ParamsForm: per-ParamSpec validation and conversion.

import type { ParamSpec } from '../api/contract'

export type ParamValues = Record<string, string>

export interface GameOption {
  app_id: number
  name: string
}

/** Error text for one field, or null when the value is acceptable. */
export function paramError(p: ParamSpec, raw: string, games: GameOption[]): string | null {
  const v = raw.trim()
  if (v === '') return p.required && p.default === undefined ? `${p.label} is required.` : null
  if (p.type === 'string') return null
  if (!/^-?\d+$/.test(v)) return `${p.label} must be a whole number.`
  const n = Number(v)
  if (p.type === 'app_id') {
    if (n <= 0) return 'Enter a Steam app id.'
    if (games.length > 0 && !games.some((g) => g.app_id === n)) return `App ${n} is not in your library snapshot.`
    return null
  }
  if (p.min !== undefined && n < p.min) return `At least ${p.min}.`
  if (p.max !== undefined && n > p.max) return `At most ${p.max}.`
  return null
}

/** Convert form strings to the typed params the server expects. */
export function toParams(specs: ParamSpec[], values: ParamValues): Record<string, number | string> {
  const out: Record<string, number | string> = {}
  for (const p of specs) {
    const raw = (values[p.name] ?? '').trim()
    if (raw === '') {
      if (p.default !== undefined) out[p.name] = p.default
      continue
    }
    out[p.name] = p.type === 'string' ? raw : Number(raw)
  }
  return out
}

export function initialValues(specs: ParamSpec[], preset: Record<string, number | string> = {}): ParamValues {
  return Object.fromEntries(specs.map((p) => [p.name, String(preset[p.name] ?? p.default ?? '')]))
}
