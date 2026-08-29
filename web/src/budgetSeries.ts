/**
 * Colour assignment for the stacked budget chart.
 *
 * Kept out of the component because it is the one part with branches worth
 * testing directly, and because the rule it encodes is not local: `--cat-1..6`
 * come from the shared design system's categorical ramp, chosen under a
 * pairwise CIE dE >= 20 constraint including simulated colour-vision
 * deficiency. Six is the whole ramp -- a seventh distinguishable hue does not
 * exist in that band, which is why the backend folds the tail into `other`.
 */

/** Games with no attribution, and the folded tail, sit outside the ramp. */
export const UNATTRIBUTED_KEY = 'unattributed'
export const OTHER_KEY = 'other'

/** Size of the categorical ramp; the backend caps series to match. */
export const SERIES_COLORS = 6

/**
 * Return the CSS class for a legend entry at `index`.
 *
 * The two sentinels are deliberately neutral: they are absences of
 * information, and giving them a ramp hue would read as "another game".
 */
export function seriesClass(key: string, index: number): string {
  if (key === UNATTRIBUTED_KEY) return 'seg unattributed'
  if (key === OTHER_KEY) return 'seg other'
  return `seg cat-${(index % SERIES_COLORS) + 1}`
}
