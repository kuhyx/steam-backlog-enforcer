import { describe, expect, it } from 'vitest'
import type { BudgetHistoryDay, BudgetLegendEntry } from '../../types'
import { budgetHistorySvg, esc, H } from './budgetHistory'

const LEGEND: BudgetLegendEntry[] = [
  { key: 'app:475150', label: 'Titan Quest' },
  { key: 'proc:osu-lazer', label: 'osu!lazer' },
  { key: 'unattributed', label: 'Unattributed' },
]

function day(over: Partial<BudgetHistoryDay> = {}): BudgetHistoryDay {
  return { day: '2026-08-28', seconds: 14400, segments: [{ key: 'app:475150', seconds: 14400 }], ...over }
}

/** Parse the markup the way the page does, into the document. */
function render(markup: string): SVGSVGElement {
  document.body.innerHTML = markup
  const svg = document.querySelector('svg')
  if (!svg) throw new Error('no <svg> in the markup')
  return svg
}

const num = (el: Element | undefined, attr: string) => Number(el?.getAttribute(attr))

describe('budgetHistorySvg', () => {
  it('draws a single day without filling the plot', () => {
    const svg = render(budgetHistorySvg([day()], LEGEND, 28800))
    expect(svg.namespaceURI).toBe('http://www.w3.org/2000/svg')
    const bars = svg.querySelectorAll('rect.seg')
    expect(bars).toHaveLength(1)
    // Scaled against the budget, half a budget is half the plot height.
    expect(num(bars[0], 'height')).toBeLessThan(Number(svg.getAttribute('viewBox')?.split(' ')[3]) / 2)
    expect(svg.querySelector('text.axis-label.mid')?.textContent).toBe('08-28')
    expect(svg.querySelector('line.budget-line')).not.toBeNull()
    expect(svg.querySelectorAll('line.grid')).toHaveLength(3)
  })

  it('stacks one band per game and colours it by legend position', () => {
    const svg = render(
      budgetHistorySvg(
        [day({ seconds: 21600, segments: [{ key: 'app:475150', seconds: 14400 }, { key: 'proc:osu-lazer', seconds: 7200 }] })],
        LEGEND,
        28800,
      ),
    )
    const [first, second] = svg.querySelectorAll('rect.seg')
    expect(svg.querySelectorAll('rect.seg')).toHaveLength(2)
    expect(svg.querySelector('rect.cat-1')).not.toBeNull()
    expect(svg.querySelector('rect.cat-2')).not.toBeNull()
    // Bands abut: the second starts exactly where the first ends.
    expect(num(second, 'y') + num(second, 'height')).toBeCloseTo(num(first, 'y'), 5)
  })

  it('renders an unattributed day in its own neutral band', () => {
    const svg = render(budgetHistorySvg([day({ day: '2026-08-24', seconds: 12000, segments: [{ key: 'unattributed', seconds: 12000 }] })], LEGEND, 28800))
    expect(svg.querySelectorAll('rect.seg.unattributed')).toHaveLength(1)
    // No ramp hue: an absence of information must not read as another game.
    expect(svg.querySelector('rect.cat-1')).toBeNull()
  })

  it('labels each band with its game in the tooltip, escaped', () => {
    const svg = render(budgetHistorySvg([day({ segments: [{ key: 'b', seconds: 3600 }] })], [{ key: 'b', label: `Baldur's <Gate> & "3"` }], 28800))
    expect(svg.querySelector('rect.seg title')?.textContent).toBe(`2026-08-28 · Baldur's <Gate> & "3": 1h 0m`)
  })

  it('falls back to the raw key and the first hue when the legend omits it', () => {
    const svg = render(budgetHistorySvg([day({ segments: [{ key: 'app:999', seconds: 3600 }] })], LEGEND, 28800))
    expect(svg.querySelector('rect.seg title')?.textContent).toContain('app:999')
    expect(svg.querySelector('rect.cat-1')).not.toBeNull()
  })

  it('scales to the tallest day once one passes the budget', () => {
    const svg = render(budgetHistorySvg([day({ seconds: 57600, segments: [{ key: 'app:475150', seconds: 57600 }] })], LEGEND, 28800))
    // The over-budget day sets the top tick; the budget is then the middle one.
    expect([...svg.querySelectorAll('text.axis-label.end')].map((t) => t.textContent)).toEqual(['0s', '8h 0m', '16h 0m'])
  })

  it('survives a zero budget and a day that billed nothing', () => {
    const svg = render(budgetHistorySvg([day({ seconds: 0, segments: [] })], [], 0))
    // A day with no billed time draws no bands, but the axes still render.
    expect(svg.querySelectorAll('rect.seg')).toHaveLength(0)
    expect(num(svg.querySelector('line.budget-line') ?? undefined, 'y1')).toBeLessThan(H)
    expect(svg.innerHTML).not.toContain('NaN')
  })
})

describe('esc', () => {
  it('escapes every markup-significant character', () => {
    expect(esc(`<a href="x">Tom & Jerry's</a>`)).toBe('&lt;a href=&quot;x&quot;&gt;Tom &amp; Jerry&#39;s&lt;/a&gt;')
  })
})
