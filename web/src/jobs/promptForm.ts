// Answer a job's prompt (was PromptForm.tsx + GamePrompt.tsx). Every kind is
// a real form: Enter submits, the first control is focused, and choices are
// radio buttons (arrow keys move). Each form owns its state; the job view
// replaces it only when a new prompt arrives.

import { api } from '../api/client'
import { q } from '../api/queries'
import { phraseMatches } from '../commands/catalog'
import { PhraseField } from '../commands/phraseField'
import { Action } from '../lib/action'
import { h, hx } from '../lib/dom'
import type { GameBrowserElement } from '../library/pick'
import { errorNotice } from '../ui/build'
import { hub, type PromptEvent } from './hub'

function answerAction(jobId: string, prompt: PromptEvent, onChange: () => void): Action<[string], void> {
  return new Action(async (value: string) => {
    await api.answer(jobId, { prompt_id: prompt.prompt_id, value })
    hub.answered(jobId, prompt.prompt_id)
  }, onChange)
}

export function promptForm(jobId: string, prompt: PromptEvent): HTMLFormElement {
  return prompt.kind === 'game' ? gamePrompt(jobId, prompt) : answerForm(jobId, prompt)
}

function answerForm(jobId: string, prompt: PromptEvent): HTMLFormElement {
  let value = prompt.default ?? ''
  const errorSlot = h('div', { class: 'contents' })
  const actions = h('div', { class: 'actions' })
  const send = answerAction(jobId, prompt, () => {
    refresh()
  })
  const submit = (v: string = value) => {
    void send.run(v)
  }
  const form = h('form', { class: 'prompt', 'aria-label': 'Job question' }, h('p', { class: 'prompt-msg' }, prompt.message))
  form.addEventListener('submit', (e) => {
    e.preventDefault()
    if (ready()) submit()
  })

  const ready = () =>
    prompt.kind === 'text' || (prompt.kind === 'choice' ? value !== '' : phraseMatches(prompt.phrase ?? '', value))

  if (prompt.kind === 'choice') {
    const labels: HTMLLabelElement[] = []
    const set = h('fieldset', { class: 'choices' }, h('legend', { class: 'sr-only' }, prompt.message))
    ;(prompt.options ?? []).forEach((o, i) => {
      const radio = h('input', { type: 'radio', name: `prompt-${prompt.prompt_id}`, value: o.value, autofocus: i === 0 })
      radio.checked = value === o.value
      radio.addEventListener('change', () => {
        value = o.value
        refresh()
      })
      const label = h(
        'label',
        { class: 'choice' },
        radio,
        h('span', { class: 'choice-label' }, o.label),
        o.detail ? h('span', { class: 'choice-detail' }, o.detail) : null,
      )
      label.dataset.value = o.value
      labels.push(label)
      set.append(label)
    })
    form.append(set)
    const markSelected = () => {
      for (const l of labels) l.classList.toggle('selected', l.dataset.value === value)
    }
    form.addEventListener('change', markSelected)
    markSelected()
  } else if (prompt.kind === 'text') {
    const input = h('input', { class: 'input', 'aria-label': prompt.message, autofocus: true })
    input.value = value
    input.addEventListener('input', () => {
      value = input.value
    })
    form.append(input)
  } else if (prompt.kind === 'phrase') {
    const field = new PhraseField({
      phrase: prompt.phrase ?? '',
      value,
      autofocus: true,
      onChange: (v) => {
        value = v
        refresh()
      },
    })
    form.append(field.el)
  }
  form.append(errorSlot, actions)

  function refresh(): void {
    errorSlot.replaceChildren(...(send.error ? [errorNotice(send.error)] : []))
    if (prompt.kind === 'confirm') {
      actions.replaceChildren(
        h('button', { type: 'button', class: 'btn btn-primary', autofocus: prompt.default !== 'no', disabled: send.pending, onclick: () => { submit('yes') } }, 'Yes'),
        h('button', { type: 'button', class: 'btn btn-ghost', autofocus: prompt.default === 'no', disabled: send.pending, onclick: () => { submit('no') } }, 'No'),
      )
      return
    }
    const btn = actions.querySelector('button') ?? actions.appendChild(h('button', { type: 'submit', class: 'btn btn-primary' }))
    btn.disabled = !ready() || send.pending
    btn.textContent = send.pending ? 'Sending…' : 'Answer'
  }
  refresh()
  return form
}

/**
 * A `game` prompt: the library browser in pick mode. Only the ids the job
 * sent are selectable (the job re-checks the answer). "Back to the list"
 * answers empty, which returns the job to its previous question.
 */
function gamePrompt(jobId: string, prompt: PromptEvent): HTMLFormElement {
  const appIds = new Set(prompt.app_ids ?? [])
  let selected: number | null = null
  const send = answerAction(jobId, prompt, () => {
    refresh()
  })
  const browser = hx('game-browser') as GameBrowserElement
  const pick = (id: number) => {
    selected = id
    browser.pick = { appIds, selected, onSelect: pick }
    refresh()
  }
  browser.pick = { appIds, selected, onSelect: pick }
  const pickBtn = h('button', { type: 'submit', class: 'btn btn-primary' })
  const backBtn = h('button', { type: 'button', class: 'btn btn-ghost', onclick: () => void send.run('') }, 'Back to the list')
  const errorSlot = h('div', { class: 'contents' })
  const form = h(
    'form',
    { class: 'prompt prompt-game', 'aria-label': 'Job question' },
    h('p', { class: 'prompt-msg' }, prompt.message, ' ', h('span', { class: 'muted' }, `· ${appIds.size} games can be picked`)),
    browser,
    errorSlot,
    h('div', { class: 'actions prompt-game-bar' }, pickBtn, backBtn),
  )
  form.addEventListener('submit', (e) => {
    e.preventDefault()
    if (selected !== null) void send.run(String(selected))
  })

  function refresh(): void {
    const name = q.library.state.data?.games.find((g) => g.app_id === selected)?.name ?? String(selected)
    pickBtn.disabled = selected === null || send.pending
    pickBtn.textContent = send.pending ? 'Sending…' : selected === null ? 'Select a game' : `Pick ${name}`
    backBtn.disabled = send.pending
    errorSlot.replaceChildren(...(send.error ? [errorNotice(send.error)] : []))
  }
  refresh()
  return form
}
