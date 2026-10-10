import { QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from '@tanstack/react-router'
import { queryClient, refreshAfterJob } from './api/queries'
import { hub } from './jobs/hub'
import { router } from './router'

// A finished job can change anything (assignment, installed list, budget),
// so every cached view is refetched when one ends.
hub.onTerminal = refreshAfterJob

/** The control UI: every `run.sh` command, routed by section. */
function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  )
}

export default App
