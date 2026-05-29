import { SELECTABLE_TIERS } from '../protondb'
import type {
  EstimateBasis,
  Filters,
  PlaytimeMode,
  WebDefaults,
} from '../types'

interface Props {
  filters: Filters
  defaults: WebDefaults
  update: (patch: Partial<Filters>) => void
  onReset: () => void
}

const BASES: { id: EstimateBasis; label: string }[] = [
  { id: 'rush', label: 'Rush' },
  { id: 'leisure', label: 'Leisure' },
  { id: 'worst', label: 'Worst' },
  { id: 'pace', label: 'Pace' },
]

const PLAYTIME: { id: PlaytimeMode; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'started', label: 'Started' },
  { id: 'untouched', label: 'Untouched' },
]

export function FilterPanel({ filters, defaults, update, onReset }: Props) {
  return (
    <aside className="panel">
      <div className="panel-head">
        <h2>Filters</h2>
        <button type="button" className="ghost" onClick={onReset}>
          Reset to CLI defaults
        </button>
      </div>

      <section className="field">
        <label>Estimate basis</label>
        <div className="segmented">
          {BASES.map((b) => (
            <button
              type="button"
              key={b.id}
              className={filters.basis === b.id ? 'seg active' : 'seg'}
              onClick={() => update({ basis: b.id })}
            >
              {b.label}
            </button>
          ))}
        </div>
      </section>

      <section className="field">
        <label>
          Daily play time <span className="val">{filters.dailyHours} h/day</span>
        </label>
        <input
          type="range"
          min={0.5}
          max={16}
          step={0.5}
          value={filters.dailyHours}
          onChange={(e) => update({ dailyHours: Number(e.target.value) })}
        />
      </section>

      <section className="field">
        <label>
          Min HLTB completions{' '}
          <span className="val">{filters.minCountComp}</span>
        </label>
        <input
          type="range"
          min={0}
          max={100}
          step={1}
          value={filters.minCountComp}
          onChange={(e) => update({ minCountComp: Number(e.target.value) })}
        />
        <p className="hint">
          Higher = more reliable HLTB times (CLI default {defaults.min_count_comp}).
        </p>
      </section>

      <details className="field">
        <summary>Advanced confidence</summary>
        <label>
          Min polled completionist times{' '}
          <span className="val">{filters.minComp100}</span>
        </label>
        <input
          type="range"
          min={0}
          max={50}
          step={1}
          value={filters.minComp100}
          onChange={(e) => update({ minComp100: Number(e.target.value) })}
        />
        <label>
          Min confidence sum <span className="val">{filters.minConfidenceSum}</span>
        </label>
        <input
          type="range"
          min={0}
          max={150}
          step={1}
          value={filters.minConfidenceSum}
          onChange={(e) => update({ minConfidenceSum: Number(e.target.value) })}
        />
      </details>

      <section className="field">
        <label>ProtonDB compatibility</label>
        <div className="segmented">
          <button
            type="button"
            className={filters.protonMode === 'playable' ? 'seg active' : 'seg'}
            onClick={() => update({ protonMode: 'playable' })}
          >
            Playable (CLI rule)
          </button>
          <button
            type="button"
            className={filters.protonMode === 'minTier' ? 'seg active' : 'seg'}
            onClick={() => update({ protonMode: 'minTier' })}
          >
            Min tier
          </button>
        </div>
        {filters.protonMode === 'minTier' && (
          <div className="subfield">
            <select
              value={filters.protonMinTier}
              onChange={(e) => update({ protonMinTier: e.target.value })}
            >
              {SELECTABLE_TIERS.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
            <label className="check">
              <input
                type="checkbox"
                checked={filters.protonTreatMissingAsPass}
                onChange={(e) =>
                  update({ protonTreatMissingAsPass: e.target.checked })
                }
              />
              Keep games with no ProtonDB data
            </label>
          </div>
        )}
      </section>

      <section className="field">
        <label>
          Max time per game{' '}
          <span className="val">
            {filters.maxHoursPerGame > 0 ? `${filters.maxHoursPerGame} h` : 'off'}
          </span>
        </label>
        <input
          type="range"
          min={0}
          max={200}
          step={5}
          value={filters.maxHoursPerGame}
          onChange={(e) => update({ maxHoursPerGame: Number(e.target.value) })}
        />
        <p className="hint">Hide games longer than this (0 = no cap).</p>
      </section>

      <section className="field">
        <label>Playtime</label>
        <div className="segmented">
          {PLAYTIME.map((p) => (
            <button
              type="button"
              key={p.id}
              className={filters.playtimeMode === p.id ? 'seg active' : 'seg'}
              onClick={() => update({ playtimeMode: p.id })}
            >
              {p.label}
            </button>
          ))}
        </div>
      </section>

      <section className="field">
        <label className="check">
          <input
            type="checkbox"
            checked={filters.includeNoData}
            onChange={(e) => update({ includeNoData: e.target.checked })}
          />
          Include games with no HLTB data
        </label>
        {filters.includeNoData && (
          <div className="subfield">
            <label>
              Fallback estimate{' '}
              <span className="val">{filters.fallbackHours} h</span>
            </label>
            <input
              type="range"
              min={1}
              max={100}
              step={1}
              value={filters.fallbackHours}
              onChange={(e) => update({ fallbackHours: Number(e.target.value) })}
            />
          </div>
        )}
      </section>

      <section className="field">
        <label>Target finish date</label>
        <div className="subfield row">
          <input
            type="date"
            value={filters.targetDate}
            onChange={(e) => update({ targetDate: e.target.value })}
          />
          {filters.targetDate && (
            <button
              type="button"
              className="ghost"
              onClick={() => update({ targetDate: '' })}
            >
              Clear
            </button>
          )}
        </div>
        <p className="hint">Pick a date to see the hours/day required.</p>
      </section>
    </aside>
  )
}
