import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { q } from '../api/queries'
import { CommandCard } from '../commands/CommandCard'
import { GameBrowser } from '../library/GameBrowser'
import { bytes } from '../ui/format'
import { Empty, ErrorNotice, Loading } from '../ui/Notice'
import { Actions, Card, PageHead } from '../ui/Page'

const VIEWS = [
  ['all', 'All games'],
  ['installed', 'Installed'],
] as const

/** Every owned game as a cover grid, or `installed` as a table; actions above. */
export function Library() {
  const [view, setView] = useState<'all' | 'installed'>('all')
  return (
    <>
      <PageHead title="Library" sub="Every game you own, and what is installed." />
      <LibraryActions />
      <div className="seg" role="group" aria-label="Library view">
        {VIEWS.map(([key, label]) => (
          <button key={key} type="button" className="btn btn-ghost btn-small" aria-pressed={view === key} onClick={() => setView(key)}>
            {label}
          </button>
        ))}
      </div>
      {view === 'all' ? <GameBrowser /> : <InstalledTable />}
    </>
  )
}

function LibraryActions() {
  const { data } = useQuery(q.installed)
  const removable = (data?.games ?? []).filter((g) => !g.assigned && !g.protected)
  return (
    <Actions>
      <CommandCard name="install" label="Install assigned" />
      <CommandCard name="uninstall" label={`Uninstall ${removable.length}…`} />
      <CommandCard name="hide" label="Hide others" />
      <CommandCard name="unhide" label="Unhide all" />
    </Actions>
  )
}

/** `installed` as a table. */
function InstalledTable() {
  const { data, error } = useQuery(q.installed)
  const games = data?.games ?? []
  const total = games.reduce((a, g) => a + g.size_bytes, 0)
  return (
      <Card title="Installed" aside={data && <span className="muted">{games.length} games · {bytes(total)}</span>}>
        {error && <ErrorNotice error={error} />}
        {!data && !error && <Loading what="installed games" />}
        {data && games.length === 0 && <Empty>No games installed.</Empty>}
        {games.length > 0 && (
          <div className="tbl" tabIndex={0} role="region" aria-label="Installed games">
            <table>
              <thead>
                <tr>
                  <th scope="col">Game</th>
                  <th scope="col">App id</th>
                  <th scope="col" className="num">Size</th>
                  <th scope="col">Role</th>
                </tr>
              </thead>
              <tbody>
                {games.map((g) => (
                  <tr key={g.app_id}>
                    <td>{g.name}</td>
                    <td className="mono muted">{g.app_id}</td>
                    <td className="num">{bytes(g.size_bytes)}</td>
                    <td>
                      {g.assigned && <span className="pill pill-accent">assigned</span>}
                      {g.protected && <span className="pill pill-neutral">protected</span>}
                      {!g.assigned && !g.protected && <span className="muted">uninstall candidate</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
  )
}
