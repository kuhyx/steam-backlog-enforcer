import { screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { renderClient, stubApi } from '../test/harness'
import { JobProgress } from './JobProgress'

// useLiveJob returns null only for a null id, which JobProgress never passes.
// JobProgress still guards the type, so pin that guard.
vi.mock('./useLiveJob', () => ({ useLiveJob: () => null }))

describe('JobProgress without a live stream handle', () => {
  it('renders nothing', () => {
    stubApi({ 'GET /api/jobs/x': {}, 'GET /api/commands': [] })
    renderClient(<JobProgress jobId="x" />)
    expect(screen.queryByRole('region')).toBeNull()
    expect(document.querySelector('section')).toBeNull()
  })
})
