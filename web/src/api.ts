import type { WebDataset } from './types'

/** Fetch the projected dataset from the Python backend. */
export async function fetchDataset(): Promise<WebDataset> {
  const resp = await fetch('/api/dataset')
  if (!resp.ok) {
    throw new Error(`API returned ${resp.status} ${resp.statusText}`)
  }
  return (await resp.json()) as WebDataset
}
