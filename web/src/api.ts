import type { BudgetSnapshot, WebDataset } from './types'

/** Fetch and decode a JSON document from the Python backend. */
async function getJson<T>(path: string): Promise<T> {
  const resp = await fetch(path)
  if (!resp.ok) {
    throw new Error(`API returned ${resp.status} ${resp.statusText}`)
  }
  return (await resp.json()) as T
}

/** Fetch the projected dataset from the Python backend. */
export function fetchDataset(): Promise<WebDataset> {
  return getJson<WebDataset>('/api/dataset')
}

/**
 * Fetch the current gaming-budget snapshot.
 *
 * `demo` reads the short-budget demo run instead of production, which is how
 * the cutoff can be watched in the browser without spending a real day.
 */
export function fetchBudget(demo: boolean): Promise<BudgetSnapshot> {
  return getJson<BudgetSnapshot>(`/api/budget${demo ? '?demo=1' : ''}`)
}
