import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api/client'
import { q } from '../api/queries'
import { GameBrowser } from '../library/GameBrowser'
import { ErrorNotice } from '../ui/Notice'
import { hub, type PromptEvent } from './hub'

/**
 * A `game` prompt: the library browser in pick mode. Only the ids the job
 * sent are selectable (the job re-checks the answer). "Back to the list"
 * answers empty, which returns the job to its previous question.
 */
export function GamePrompt({ jobId, prompt }: { jobId: string; prompt: PromptEvent }) {
  const [appIds] = useState(() => new Set(prompt.app_ids ?? []))
  const [selected, setSelected] = useState<number | null>(null)
  const { data } = useQuery(q.library)
  const send = useMutation({
    mutationFn: (v: string) => api.answer(jobId, { prompt_id: prompt.prompt_id, value: v }),
    onSuccess: () => hub.answered(jobId, prompt.prompt_id),
  })
  const name = data?.games.find((g) => g.app_id === selected)?.name ?? String(selected)
  const submit = (id: number) => send.mutate(String(id))

  return (
    <form
      className="prompt prompt-game"
      aria-label="Job question"
      onSubmit={(e) => {
        e.preventDefault()
        if (selected !== null) submit(selected)
      }}
    >
      <p className="prompt-msg">
        {prompt.message} <span className="muted">· {appIds.size} games can be picked</span>
      </p>
      <GameBrowser pick={{ appIds, selected, onSelect: setSelected }} />
      {send.error && <ErrorNotice error={send.error} />}
      <div className="actions prompt-game-bar">
        <button type="submit" className="btn btn-primary" disabled={selected === null || send.isPending}>
          {send.isPending ? 'Sending…' : selected === null ? 'Select a game' : `Pick ${name}`}
        </button>
        <button type="button" className="btn btn-ghost" disabled={send.isPending} onClick={() => send.mutate('')}>
          Back to the list
        </button>
      </div>
    </form>
  )
}
