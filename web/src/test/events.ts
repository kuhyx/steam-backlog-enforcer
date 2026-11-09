// Small DOM-event helpers for element tests. Lives under src/test/, excluded
// from the app build and from coverage.

/** Set an input's value and fire the `input` event, as typing does. */
export function setValue(input: HTMLInputElement, value: string): void {
  input.value = value
  input.dispatchEvent(new Event('input', { bubbles: true }))
}

/** The button inside `root` whose text is exactly `text`. */
export function button(root: ParentNode, text: string): HTMLButtonElement {
  const found = [...root.querySelectorAll('button')].find((b) => b.textContent === text)
  if (!found) throw new Error(`no button "${text}"`)
  return found
}

/** Submit the form that contains `el`. */
export function submit(el: Element): void {
  el.closest('form')?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
}

/** `value`, or a failed test when it is missing (the lint config forbids `!`). */
export function must<T>(value: T | null | undefined, what = 'value'): T {
  if (value === null || value === undefined) throw new Error(`missing ${what}`)
  return value
}
