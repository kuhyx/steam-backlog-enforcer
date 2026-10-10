import { useId, useState, type KeyboardEvent } from 'react'
import type { LibraryGame } from '../api/contract'
import { metaLine } from './view'

/**
 * Library search: an ARIA combobox. Typing filters the grid behind it and
 * lists the top suggestions; ↑/↓ move through them, Enter chooses the
 * highlighted one (or the first), Escape closes the list, then clears.
 */
export function SearchBox({
  value,
  onChange,
  suggestions,
  reason,
  onChoose,
}: {
  value: string
  onChange: (v: string) => void
  suggestions: LibraryGame[]
  /** Why a game cannot be picked here (pick mode differs from the library). */
  reason: (g: LibraryGame) => string | null
  onChoose: (g: LibraryGame) => void
}) {
  const listId = useId()
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)
  const shown = open && value.trim() !== '' && suggestions.length > 0

  const choose = (g: LibraryGame) => {
    setOpen(false)
    setActive(-1)
    onChoose(g)
  }

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    const n = suggestions.length
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      if (n === 0) return
      e.preventDefault()
      setOpen(true)
      const step = e.key === 'ArrowDown' ? 1 : -1
      setActive((i) => (i < 0 && step < 0 ? n - 1 : (i + step + n) % n))
    } else if (e.key === 'Enter') {
      if (!shown) return
      e.preventDefault()
      choose(suggestions[active >= 0 && active < n ? active : 0])
    } else if (e.key === 'Escape') {
      if (shown) {
        e.preventDefault()
        e.stopPropagation()
        setOpen(false)
      } else if (value) {
        e.preventDefault()
        e.stopPropagation()
        onChange('')
      }
    }
  }

  return (
    <div className="lib-search">
      <input
        className="input"
        type="search"
        role="combobox"
        aria-label="Search your games"
        aria-expanded={shown}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={shown && active >= 0 ? `${listId}-${active}` : undefined}
        placeholder="Search your games (typos are fine)…"
        value={value}
        onChange={(e) => {
          onChange(e.target.value)
          setOpen(true)
          setActive(-1)
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={onKeyDown}
      />
      <ul id={listId} role="listbox" className="lib-suggest" hidden={!shown} aria-label="Suggestions">
        {shown &&
          suggestions.map((g, i) => (
            <li
              key={g.app_id}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === active}
              className={i === active ? 'lib-suggest-item active' : 'lib-suggest-item'}
              // mousedown, not click: the input's blur would close the list first.
              onMouseDown={(e) => {
                e.preventDefault()
                choose(g)
              }}
            >
              <span className="lib-suggest-name">{g.name}</span>
              <span className="lib-suggest-meta">{reason(g) ?? metaLine(g)}</span>
            </li>
          ))}
      </ul>
    </div>
  )
}
