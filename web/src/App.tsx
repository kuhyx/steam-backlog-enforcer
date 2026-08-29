import { useState } from 'react'
import { BudgetPanel } from './components/BudgetPanel'
import { PlannerView } from './components/PlannerView'
import type { TabId } from './types'

/**
 * `?demo=1` points the budget tab at the short-budget demo run, which is the
 * only way to watch the cutoff engage without spending a real day's budget.
 */
function demoRequested(): boolean {
  return new URLSearchParams(window.location.search).get('demo') === '1'
}

const TABS: { id: TabId; label: string }[] = [
  { id: 'planner', label: 'Backlog planner' },
  { id: 'budget', label: 'Gaming budget' },
]

function App() {
  const [tab, setTab] = useState<TabId>('planner')

  return (
    <div className="app">
      <nav className="tabs" role="tablist">
        {TABS.map(({ id, label }) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            className={tab === id ? 'tab active' : 'tab'}
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </nav>
      {/* The budget panel only mounts on its own tab, so the planner never
          pays for its polling — and vice versa. */}
      {tab === 'budget' ? <BudgetPanel demo={demoRequested()} /> : <PlannerView />}
    </div>
  )
}

export default App
