// Shared helpers for the runner-dialog tests. Lives under src/test/,
// excluded from the app build and from coverage.

import { vi } from 'vitest'
import type { CommandName, CommandSpec } from '../api/contract'
import '../commands/runnerDialog'
import { runner, type Preset } from '../lib/runner'
import { routes } from './dialogRoutes'
import { button, must } from './events'
import { stubApi } from './harness'

/** Mount `<runner-dialog>` against the routed stub and ask it to run `name`. */
export function openRunner(
  specs: CommandSpec[],
  name: CommandName,
  { preset, extra = {} }: { preset?: Preset; extra?: Record<string, unknown> } = {},
) {
  const mock = stubApi(routes(specs, extra))
  const el = document.createElement('runner-dialog')
  document.body.append(el)
  runner.run(name, preset)
  return { mock, el }
}

/** Wait for a button with this exact text, then return it. */
export async function found(text: string): Promise<HTMLButtonElement> {
  return vi.waitFor(() => button(document.body, text))
}

/** The input whose spoken label (its .sr-only text, else its text) starts with `label`. */
export function field(label: string | RegExp): HTMLInputElement {
  const spoken = (x: Element) => x.querySelector('.sr-only')?.textContent ?? x.textContent
  const l = [...document.querySelectorAll('label')].find((x) => (typeof label === 'string' ? spoken(x).startsWith(label) : label.test(spoken(x))))
  return document.getElementById(l?.getAttribute('for') ?? '') as HTMLInputElement
}

export const phraseInput = (): HTMLInputElement => must(document.querySelector<HTMLInputElement>('.phrase input'))
export const text = (): string => document.body.textContent
