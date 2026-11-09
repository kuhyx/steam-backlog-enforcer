// Page state kept in the URL hash (`#q=wicher&sort=recent&view=installed`),
// so a reload or a shared link restores it. Writes use replaceState: typing
// must not push one history entry per keystroke, and replaceState fires no
// `hashchange`, so a page never re-applies its own writes.

/** The current hash as search params. */
export function readHash(): URLSearchParams {
  return new URLSearchParams(location.hash.slice(1))
}

/** Set (or, for null / empty, drop) `values`, leaving other keys alone. */
export function writeHash(values: Record<string, string | null>): void {
  const params = readHash()
  for (const [key, value] of Object.entries(values)) {
    if (value === null || value === '') params.delete(key)
    else params.set(key, value)
  }
  const hash = params.toString()
  history.replaceState(history.state, '', hash ? `#${hash}` : `${location.pathname}${location.search}`)
}
