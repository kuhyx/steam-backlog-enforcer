import { useId } from 'react'
import type { ParamSpec } from '../api/contract'
import { paramError, type GameOption, type ParamValues } from './params'

interface Props {
  specs: ParamSpec[]
  values: ParamValues
  onChange: (v: ParamValues) => void
  games: GameOption[]
  showErrors: boolean
  disabled: boolean
}

export function ParamsForm({ specs, values, onChange, games, showErrors, disabled }: Props) {
  const base = useId()
  return (
    <>
      {specs.map((p, i) => {
        const id = `${base}-${p.name}`
        const raw = values[p.name] ?? ''
        const err = paramError(p, raw, games)
        const game = p.type === 'app_id' ? games.find((g) => g.app_id === Number(raw)) : undefined
        return (
          <div className="form-field" key={p.name}>
            <label htmlFor={id} className="field-label">
              {p.label}
              {p.required && <span aria-hidden="true"> *</span>}
            </label>
            <input
              id={id}
              className={`input ${p.type === 'string' ? '' : 'input-num'}${showErrors && err ? ' input-bad' : ''}`}
              type={p.type === 'int' ? 'number' : 'text'}
              inputMode={p.type === 'string' ? undefined : 'numeric'}
              min={p.min}
              max={p.max}
              list={p.type === 'app_id' ? `${id}-games` : undefined}
              value={raw}
              required={p.required}
              disabled={disabled}
              autoFocus={i === 0}
              aria-invalid={showErrors && err !== null}
              aria-describedby={`${id}-help`}
              onChange={(e) => onChange({ ...values, [p.name]: e.target.value })}
            />
            {p.type === 'app_id' && (
              <datalist id={`${id}-games`}>
                {games.map((g) => (
                  <option key={g.app_id} value={g.app_id}>
                    {g.name}
                  </option>
                ))}
              </datalist>
            )}
            <p id={`${id}-help`} className={showErrors && err ? 'field-help text-danger' : 'field-help'}>
              {showErrors && err ? err : game ? game.name : (p.help ?? (p.type === 'app_id' ? 'Type an app id or pick a game from the list.' : ' '))}
            </p>
          </div>
        )
      })}
    </>
  )
}
