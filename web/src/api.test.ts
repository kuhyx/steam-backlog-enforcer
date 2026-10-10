import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchBudget, fetchDataset } from './api'
import { makeBudget, makeDataset } from './test/factories'
import { Reply, stubApi } from './test/harness'

describe('legacy fetchers', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('fetchDataset returns the JSON document', async () => {
    const ds = makeDataset()
    stubApi({ 'GET /api/dataset': ds })
    await expect(fetchDataset()).resolves.toEqual(ds)
  })

  it('fetchBudget asks for the demo run only when told to', async () => {
    const mock = stubApi({ 'GET /api/budget': makeBudget() })
    await fetchBudget(false)
    await fetchBudget(true)
    expect(mock.mock.calls.map((c) => c[0])).toEqual(['/api/budget', '/api/budget?demo=1'])
  })

  it('throws with the status on an error response', async () => {
    stubApi({ 'GET /api/dataset': new Reply(500, undefined, '') })
    await expect(fetchDataset()).rejects.toThrow('API returned 500 Error')
  })
})
