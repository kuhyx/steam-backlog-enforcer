let next = 0

/** A document-unique id prefix (was React's useId). */
export function uid(prefix = 'sbe'): string {
  next += 1
  return `${prefix}-${next}`
}
