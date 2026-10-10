import { useMutation } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api } from '../api/client'
import { phraseMatches } from '../commands/catalog'
import { PhraseField } from '../commands/PhraseField'
import { ErrorNotice } from '../ui/Notice'
import { GamePrompt } from './GamePrompt'
import { hub, type PromptEvent } from './hub'

/**
 * Answer a job's prompt. Every kind is a real form: Enter submits, the first
 * control is focused, and choices are radio buttons (arrow keys move).
 */
export function PromptForm({ jobId, prompt }: { jobId: string; prompt: PromptEvent }) {
  if (prompt.kind === 'game') return <GamePrompt key={prompt.prompt_id} jobId={jobId} prompt={prompt} />
  return <AnswerForm jobId={jobId} prompt={prompt} />
}

function AnswerForm({ jobId, prompt }: { jobId: string; prompt: PromptEvent }) {
  const [value, setValue] = useState(prompt.default ?? '')
  const send = useMutation({
    mutationFn: (v: string) => api.answer(jobId, { prompt_id: prompt.prompt_id, value: v }),
    onSuccess: () => hub.answered(jobId, prompt.prompt_id),
  })

  const submit = (e: FormEvent, v: string = value) => {
    e.preventDefault()
    send.mutate(v)
  }

  const phraseOk = prompt.kind !== 'phrase' || phraseMatches(prompt.phrase ?? '', value)
  const ready = prompt.kind === 'text' || (prompt.kind === 'choice' ? value !== '' : phraseOk)

  return (
    <form className="prompt" onSubmit={submit} aria-label="Job question">
      <p className="prompt-msg">{prompt.message}</p>
      {prompt.kind === 'choice' && (
        <fieldset className="choices">
          <legend className="sr-only">{prompt.message}</legend>
          {prompt.options?.map((o, i) => (
            <label key={o.value} className={value === o.value ? 'choice selected' : 'choice'}>
              <input
                type="radio"
                name={`prompt-${prompt.prompt_id}`}
                value={o.value}
                checked={value === o.value}
                autoFocus={i === 0}
                onChange={() => setValue(o.value)}
              />
              <span className="choice-label">{o.label}</span>
              {o.detail && <span className="choice-detail">{o.detail}</span>}
            </label>
          ))}
        </fieldset>
      )}
      {prompt.kind === 'text' && (
        <input
          className="input"
          aria-label={prompt.message}
          value={value}
          autoFocus
          onChange={(e) => setValue(e.target.value)}
        />
      )}
      {prompt.kind === 'phrase' && (
        <PhraseField phrase={prompt.phrase ?? ''} value={value} onChange={setValue} autoFocus />
      )}
      {send.error && <ErrorNotice error={send.error} />}
      <div className="actions">
        {prompt.kind === 'confirm' ? (
          <>
            <button type="button" className="btn btn-primary" autoFocus={prompt.default !== 'no'} disabled={send.isPending} onClick={(e) => submit(e, 'yes')}>
              Yes
            </button>
            <button type="button" className="btn btn-ghost" autoFocus={prompt.default === 'no'} disabled={send.isPending} onClick={(e) => submit(e, 'no')}>
              No
            </button>
          </>
        ) : (
          <button type="submit" className="btn btn-primary" disabled={!ready || send.isPending}>
            {send.isPending ? 'Sending…' : 'Answer'}
          </button>
        )}
      </div>
    </form>
  )
}
