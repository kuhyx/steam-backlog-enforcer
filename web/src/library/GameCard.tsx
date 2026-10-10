import { useState } from 'react'
import { ENDPOINTS, type LibraryGame } from '../api/contract'
import { metaLine } from './view'

/** Portrait cover, lazily loaded; a title tile when the server has none. */
function Cover({ game }: { game: LibraryGame }) {
  const [failed, setFailed] = useState(false)
  if (failed) {
    return (
      <div className="cover cover-tile" aria-hidden="true">
        <span>{game.name}</span>
      </div>
    )
  }
  return (
    <img
      className="cover"
      src={ENDPOINTS.art(game.app_id)}
      alt=""
      loading="lazy"
      decoding="async"
      onError={() => setFailed(true)}
    />
  )
}

/**
 * One tile of the grid. A button in both modes so it is a focus stop; in
 * browse mode it only takes focus, in pick mode it selects. `reason` greys
 * it out and says why it cannot be picked.
 */
export function GameCard({
  game,
  index,
  reason,
  selected,
  focusable,
  pickMode,
  onActivate,
}: {
  game: LibraryGame
  index: number
  reason: string | null
  selected: boolean
  focusable: boolean
  pickMode: boolean
  onActivate: () => void
}) {
  const cls = ['game-card', reason ? 'ineligible' : '', selected ? 'selected' : ''].filter(Boolean).join(' ')
  return (
    <button
      type="button"
      className={cls}
      data-index={index}
      data-app-id={game.app_id}
      tabIndex={focusable ? 0 : -1}
      aria-pressed={pickMode ? selected : undefined}
      aria-disabled={pickMode && reason ? true : undefined}
      onClick={onActivate}
    >
      <Cover game={game} />
      <span className="game-title">{game.name}</span>
      <span className="game-meta">{metaLine(game)}</span>
      {(game.assigned || game.installed) && (
        <span className="game-badges">
          {game.assigned && <span className="pill pill-accent">assigned</span>}
          {game.installed && <span className="pill pill-neutral">installed</span>}
        </span>
      )}
      {reason && <span className="game-reason">{reason}</span>}
    </button>
  )
}
