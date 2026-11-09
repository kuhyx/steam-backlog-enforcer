/**
 * `<game-browser>` in pick mode (a job's `game` prompt): only `appIds` are
 * selectable; the browser calls `onSelect` and the prompt owns `selected`.
 */
export interface PickMode {
  appIds: ReadonlySet<number>
  selected: number | null
  onSelect: (appId: number) => void
}

/** The element contract GamePrompt relies on (implemented in library/). */
export interface GameBrowserElement extends HTMLElement {
  pick: PickMode | null
}
