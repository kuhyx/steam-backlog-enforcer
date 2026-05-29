import { useEffect, useMemo, useState } from 'react'
import { fetchDataset } from './api'
import { FilterPanel } from './components/FilterPanel'
import { GameTable } from './components/GameTable'
import { SummaryCards } from './components/SummaryCards'
import { TimelineChart } from './components/TimelineChart'
import { applyFilters } from './estimate'
import type { Filters, WebDataset, WebDefaults } from './types'

function defaultFilters(d: WebDefaults): Filters {
  return {
    minCountComp: d.min_count_comp,
    minComp100: d.min_comp_100_polls,
    minConfidenceSum: d.min_confidence_sum,
    protonMode: 'playable',
    protonMinTier: d.min_playable_tier,
    protonTreatMissingAsPass: true,
    dailyHours: 4,
    basis: 'leisure',
    maxHoursPerGame: 0,
    playtimeMode: 'all',
    includeNoData: false,
    fallbackHours: 20,
    excluded: new Set<number>(),
    search: '',
    targetDate: '',
  }
}

function App() {
  const [dataset, setDataset] = useState<WebDataset | null>(null)
  const [filters, setFilters] = useState<Filters | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchDataset()
      .then((d) => {
        setDataset(d)
        setFilters(defaultFilters(d.defaults))
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
  }, [])

  const result = useMemo(
    () => (dataset && filters ? applyFilters(dataset, filters) : null),
    [dataset, filters],
  )

  if (error) {
    return (
      <div className="status">
        <h1>Steam Backlog Enforcer</h1>
        <p className="error">Could not load data: {error}</p>
        <p className="hint">
          Is the backend running? Start it with <code>./run.sh serve</code>.
        </p>
      </div>
    )
  }

  if (!dataset || !filters || !result) {
    return (
      <div className="status">
        <h1>Steam Backlog Enforcer</h1>
        <p className="hint">Loading your backlog…</p>
      </div>
    )
  }

  const update = (patch: Partial<Filters>) => setFilters({ ...filters, ...patch })

  const toggleExclude = (appId: number) => {
    const next = new Set(filters.excluded)
    if (next.has(appId)) next.delete(appId)
    else next.add(appId)
    setFilters({ ...filters, excluded: next })
  }

  const tableRows = result.rows.filter((r) => r.passesFilters)

  return (
    <div className="app">
      <header className="app-head">
        <div>
          <h1>Backlog Completion Planner</h1>
          <p className="sub">
            {dataset.state.current_game_name && (
              <>
                Currently playing <strong>{dataset.state.current_game_name}</strong>{' '}
                ·{' '}
              </>
            )}
            {dataset.state.games_done} games finished since{' '}
            {dataset.state.enforcement_started_at.slice(0, 10) || '—'} ·{' '}
            {dataset.games.length} candidates
          </p>
        </div>
      </header>

      <div className="layout">
        <FilterPanel
          filters={filters}
          defaults={dataset.defaults}
          update={update}
          onReset={() => setFilters(defaultFilters(dataset.defaults))}
        />

        <main className="content">
          <SummaryCards
            result={result}
            filters={filters}
            state={dataset.state}
            presets={dataset.defaults.hours_per_day_presets}
            defaultQualifying={dataset.default_summary.qualifying}
          />
          <TimelineChart result={result} filters={filters} state={dataset.state} />
          <GameTable
            rows={tableRows}
            search={filters.search}
            onSearch={(s) => update({ search: s })}
            onToggleExclude={toggleExclude}
          />
        </main>
      </div>
    </div>
  )
}

export default App
