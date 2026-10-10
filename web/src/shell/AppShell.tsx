import { useQuery } from '@tanstack/react-query'
import { Link, Navigate, Outlet, useLocation, useNavigate } from '@tanstack/react-router'
import { useEffect } from 'react'
import { q } from '../api/queries'
import { RunnerProvider } from '../commands/RunnerProvider'
import { useRunner } from '../commands/runnerContext'
import { HealthBadges, StaleBanner } from './Health'
import { JobIndicator } from './JobIndicator'
import { NAV } from './nav'

function PaletteButton() {
  const { openPalette } = useRunner()
  return (
    <button type="button" className="btn btn-ghost palette-btn" onClick={openPalette} aria-keyshortcuts="Control+K">
      Commands <kbd>Ctrl K</kbd>
    </button>
  )
}

/** Alt+1…8 jumps between sections without walking the sidebar. */
function useSectionKeys() {
  const navigate = useNavigate()
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!e.altKey || e.ctrlKey || e.metaKey) return
      const item = NAV.find((n) => n.key === e.key)
      if (!item || document.querySelector('dialog[open]')) return
      e.preventDefault()
      void navigate({ to: item.to })
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [navigate])
}

export function AppShell() {
  useSectionKeys()
  const { pathname } = useLocation()
  const setup = useQuery(q.setup)
  if (setup.data && !setup.data.configured && pathname !== '/setup') return <Navigate to="/setup" />

  return (
    <RunnerProvider>
      <a href="#main" className="skip">
        Skip to content
      </a>
      <div className="shell">
        <aside className="sidebar">
          <div className="brand">
            <span className="brand-mark" aria-hidden="true" />
            <span>
              Backlog
              <br />
              Enforcer
            </span>
          </div>
          <nav aria-label="Sections">
            <ul className="nav">
              {NAV.map((n) => (
                <li key={n.to}>
                  <Link to={n.to} className="nav-link" activeProps={{ className: 'nav-link active', 'aria-current': 'page' }} activeOptions={{ exact: n.to === '/' }}>
                    <span>{n.label}</span>
                    <kbd aria-hidden="true">Alt {n.key}</kbd>
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
        </aside>
        <div className="main-col">
          <header className="topbar">
            <PaletteButton />
            <JobIndicator />
            <span className="grow" />
            <HealthBadges />
          </header>
          <StaleBanner />
          <main id="main" className="main" tabIndex={-1}>
            <Outlet />
          </main>
        </div>
      </div>
    </RunnerProvider>
  )
}
