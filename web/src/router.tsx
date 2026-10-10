// Code-based TanStack Router tree: one route per section, plus job detail.
// No file-based generator, so there is no generated file to keep in sync.

import { createRootRoute, createRoute, createRouter } from '@tanstack/react-router'
import { Backlog } from './screens/Backlog'
import { Dashboard } from './screens/Dashboard'
import { Gaming } from './screens/Gaming'
import { JobDetail, Jobs } from './screens/Jobs'
import { Library } from './screens/Library'
import { NotFound } from './screens/NotFound'
import { Picks } from './screens/Picks'
import { Setup } from './screens/Setup'
import { Store } from './screens/Store'
import { System } from './screens/System'
import { AppShell } from './shell/AppShell'

const root = createRootRoute({ component: AppShell, notFoundComponent: NotFound })

const page = <TPath extends string>(path: TPath, component: () => React.ReactNode) =>
  createRoute({ getParentRoute: () => root, path, component })

const gaming = createRoute({
  getParentRoute: () => root,
  path: '/gaming',
  validateSearch: (s: Record<string, unknown>): { demo?: boolean } =>
    s.demo === true || s.demo === '1' || s.demo === 1 ? { demo: true } : {},
  component: function GamingRoute() {
    return <Gaming demo={gaming.useSearch().demo === true} />
  },
})

const jobDetail = createRoute({
  getParentRoute: () => root,
  path: '/jobs/$jobId',
  component: function JobRoute() {
    return <JobDetail jobId={jobDetail.useParams().jobId} />
  },
})

const routeTree = root.addChildren([
  page('/', Dashboard),
  page('/backlog', Backlog),
  page('/picks', Picks),
  gaming,
  page('/library', Library),
  page('/store', Store),
  page('/jobs', Jobs),
  jobDetail,
  page('/system', System),
  page('/setup', Setup),
])

export const router = createRouter({ routeTree, defaultPreload: 'intent', scrollRestoration: true })

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
