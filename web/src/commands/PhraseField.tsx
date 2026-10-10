import { useId } from 'react'
import { phraseMatches } from './catalog'

interface Props {
  phrase: string
  value: string
  onChange: (v: string) => void
  autoFocus?: boolean
  label?: string
}

/**
 * Typed-phrase friction. Shows the exact sentence, then live per-character
 * feedback on the typed text. Paste is blocked: retyping is the friction.
 * The server re-checks — this field only helps the user get it right.
 */
export function PhraseField({ phrase, value, onChange, autoFocus = false, label = 'Type the phrase to confirm' }: Props) {
  const id = useId()
  const typed = value.trim()
  const ok = phraseMatches(phrase, value)
  const prefixOk = phrase.startsWith(typed)
  const status = ok ? 'Matches.' : prefixOk ? `${typed.length} of ${phrase.length} characters` : 'Does not match — check case and spacing.'

  return (
    <div className="phrase">
      <label htmlFor={id} className="field-label">
        {label}
      </label>
      <p className="phrase-target" aria-hidden="true">
        {[...phrase].map((ch, i) => {
          const cls = i < typed.length ? (typed[i] === ch ? 'ok' : 'bad') : ''
          return (
            <span key={i} className={cls}>
              {ch}
            </span>
          )
        })}
      </p>
      <input
        id={id}
        className={`input mono ${ok ? 'input-ok' : prefixOk ? '' : 'input-bad'}`}
        value={value}
        autoFocus={autoFocus}
        autoComplete="off"
        spellCheck={false}
        aria-describedby={`${id}-status`}
        aria-invalid={!prefixOk}
        onPaste={(e) => e.preventDefault()}
        onDrop={(e) => e.preventDefault()}
        onChange={(e) => onChange(e.target.value)}
      />
      <p className="sr-only">Phrase: {phrase}</p>
      <p id={`${id}-status`} className={`field-help ${ok ? 'text-success' : prefixOk ? '' : 'text-danger'}`} aria-live="polite">
        {status}
      </p>
    </div>
  )
}
