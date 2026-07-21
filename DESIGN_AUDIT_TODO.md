# Design audit — steam-backlog-enforcer

Generated against safe-design-rules (anthonyhobday.com/sideprojects/saferules).
Report only — nothing in this repo was changed by the audit itself.

Scope: `web/` (Vite/TS, 22 files). Token entry point: `web/src/index.css`
`:root` (lines 1-18). Reviewed fully alongside `App.tsx`, `FilterPanel.tsx`,
`GameTable.tsx`, `SummaryCards.tsx`, `TimelineChart.tsx`, `index.html`.

## web/ (Vite/TS frontend)

### Violations

- **Rule 1 (near-black/near-white)** — `web/src/index.css:9` — `--heading: #ffffff` is pure white while every other neutral (`--bg:#0f1117`, `--panel:#161922`, `--border:#2a2f3a`) is deliberately muted → give `--heading` a near-white value with the same cool tint, e.g. `#eef2f6`.
- **Rule 2 (saturate neutrals)** — `web/src/index.css:9` — `--heading:#ffffff` has zero saturation, breaking the otherwise-consistent cool-tinted neutral family (`--bg`, `--panel`, `--panel-2`, `--card`, `--border`, `--muted` all carry a slight blue hue) → tint it to match (see Rule 1 fix).
- **Rule 4 (everything deliberate)** — `web/src/index.css:203` and `:489` — `.seg.active { color: #06121c }` and `.badge { color: #1a1205 }` are one-off hardcoded "ink" colors with no token, unrelated to any other value in the file → promote to `--on-accent`/`--on-warn` custom properties so the choice is traceable and reusable.
- **Rule 6 (letter-spacing/line-height by size)** — `web/src/index.css:37-44` — only `h1` (26px) gets a letter-spacing adjustment (`-0.4px`, line 39); none of the 13 smaller sizes in the file (10px badge line 487, 11px axis-label line 404, 12px `.seg`/`.ghost` lines 199/214, 13px `.hint`/table/`.field label` lines 83/127/440) get any compensating letter-spacing or line-height increase → add a small positive letter-spacing (~0.1-0.2px) to the ≤13px tier.
- **Rule 9 (distinct brightness values)** — `web/src/index.css:10,12` — using the HSB-brightness metric the rule's thresholds are defined in (max(R,G,B)/255, matching Rule 18), `--accent` (#66c0f4) is 95.7% and `--warn` (#f0a23b) is 94.1% — only 1.6 points apart; `--accent-2` (81.2%) and `--danger` (89.0%) are well clear of both, so this is narrowly an accent-vs-warn issue, not a whole-palette one → nudge `--warn` a few points darker (e.g. `#e8952e`, ≈89% brightness) so it doesn't sit this close to `--accent`. Low priority: the two colors aren't used adjacently in the current UI (accent = numeric totals, warn = the "slower than leisure" insight label and the "no data" badge).
- **Rule 11 (mathematically related measurements)** — `web/src/index.css` throughout — spacing/radius values are 24, 20, 18, 14, 12, 10, 9, 8, 7, 6, 5, 4, 2, 1px (e.g. panel padding 18px line 111, card padding 14px line 275, th padding 9px line 448, td padding 7px line 462, ghost padding 5px line 210) with no shared base unit; radii alone use four unrelated hardcoded values (4px line 56, 6px lines 168/196/211, 8px lines 188/256/274/321/435, plus the `--radius:10px` token line 14) → consolidate onto one scale (e.g. 4px base: 4/8/12/16/20/24) and derive radii from `--radius` and `--radius-sm`.
- **Rule 13 (12-column grid)** — `web/src/index.css:90` and `:263` — `.layout` uses a fixed `320px 1fr` split and `.cards` uses `repeat(4, 1fr)` / `repeat(2, 1fr)` (line 268), neither derived from a shared 12-column track → define one grid scale (e.g. a `--grid-12` template) both layouts pull from, for future 1/2/3/4-up flexibility.
- **Rule 20 (body text ≥16px)** — `web/src/index.css:28` — `body { font: 15px/1.5 var(--sans); }` is below the 16px floor, and most UI text sits well under that: `.hint`/`.field label`/table/`.parity` at 13px (lines 83, 127, 247, 440), `.seg`/`.ghost`/`.card-blurb` at 12px (lines 199, 214, 286), `.preset`/`.axis-label` at 11px (lines 310, 404), `.badge` at 10px (line 487) → raise body copy to 16px minimum; for the dense data-table cells where 13px is a deliberate density trade-off, note that explicitly rather than leaving it as the default scale.
- **Rule 22 (button padding: horizontal = 2× vertical)** — `web/src/index.css:195` — `.seg { padding: 6px 4px; }` has horizontal padding *less* than vertical (should be ~2× more, e.g. `6px 12px`) → `.ghost` at `web/src/index.css:210` (`padding: 5px 10px`) already gets this right and can be the reference.
- **Rule 24 (nest corners properly)** — `web/src/index.css:188-196` — `.segmented { border-radius: 8px; padding: 4px; }` containing `.seg { border-radius: 6px; }`; per the rule the nested radius should be outer − gap = 8 − 4 = 4px, not 6px → change `.seg` to `border-radius: 4px`.
- **Rule 26 (no shadows in dark interfaces)** — `web/src/index.css:17` declares `color-scheme: dark` (bg `#0f1117`); `web/src/index.css:279` — `.card.active { box-shadow: 0 0 0 1px var(--accent); }` is technically a shadow in a dark UI → replace with a non-shadow selection indicator, e.g. `outline: 1px solid var(--accent)` or a border-color swap, which reads identically without invoking box-shadow. (Low severity: this is a 0-blur selection ring, not an elevation shadow, but it's the literal case the rule flags.)

### Not applicable

- Rule 5 (optical alignment) — no icons or asymmetric shapes in the codebase whose bounding-box center would differ from its visual center.
- Rule 8 (everything aligns with something else) — no misalignment identifiable from CSS/JSX alone; needs a rendered pass to verify.
- Rule 12 (order by visual weight) — layout-level judgment call (sidebar vs. content ordering); no clear violation visible in source.
- Rule 14 (space between high-contrast points) — requires visual inspection of rendered edges, not determinable from source.
- Rule 16 (drop shadow blur ≈ 2× distance) — the only `box-shadow` in the file (line 279) has 0 offset/0 blur, so the ratio rule doesn't meaningfully apply.
- Rule 21 (line length ~70 chars) — no long-form paragraph content; all text is short UI labels/hints.
- Rule 28 (lower icon contrast paired with text) — no dedicated icon glyphs; the only icon-like characters are the sort arrows (`▲`/`▼` in `web/src/components/GameTable.tsx:115`), which inherit the same color as the adjacent header text rather than being a separate heavier element.

### Passing

- Rule 3 (high contrast for important elements) — `.seg.active` (`web/src/index.css:202-204`) pairs `background: var(--accent)` with `color: #06121c`, a very high-contrast combination for the primary interactive state.
- Rule 7 (border contrast with both surfaces) — in HSB brightness, `--border:#2a2f3a` (22.7%) sits clearly above `--bg` (9%) and `--panel` (13.3%) wherever it's used as a divider. Caveat: against `--card:#1b2838` (22.0%) the gap is only 0.7 points — e.g. `.card { border: 1px solid var(--border) }` at `web/src/index.css:273` — border is technically still lighter but not "clearly" so; if card borders read as blurry in practice, lighten `--border` or darken `--card` by a few points.
- Rule 10 (warm OR cool neutrals) — all neutrals (`--bg`, `--panel`, `--panel-2`, `--card`, `--border`, `--muted`) carry a consistent cool/blue tint.
- Rule 15 (closer elements lighter) — HSB brightness (max(R,G,B)/255) increases monotonically through the stack: `--bg`(9.0%) < `--panel`(13.3%) < `--panel-2`(18.8%) < `--card`(22.0%) < `--border`(22.7%) < `--muted`(63.1%) < `--text`(87.5%) < `--heading`(100%).
- Rule 17 (simple on complex / complex on simple) — every surface in `index.css` is a single flat color; no competing textures or gradients anywhere.
- Rule 18 (container brightness limits) — HSB brightness deltas between stacked containers (`--bg`9.0%→`--panel`13.3%→`--panel-2`18.8%→`--card`22.0%) are all under 6 points, well within the ~12% dark-mode ceiling.
- Rule 19 (outer padding ≥ inner padding) — `.panel` outer padding 18px (line 111) ≥ `.field` internal spacing 12px (line 122); `.summary`/`.table-wrap` outer padding 18px ≥ `.cards`/`.table-head` gaps of 12px (lines 264, 425).
- Rule 23 (two typefaces max) — exactly two font families defined, `--sans` and `--mono` (`web/src/index.css:15-16`), used consistently.
- Rule 25 (avoid adjacent hard divides) — no cases of two borders/background-transitions touching directly; dividers (`.field` border-top, `.presets` border-top) are always separated by padding from any other border.
- Rule 27 (don't mix depth techniques) — the app uses exactly one depth technique (flat 1px borders, plus the single Rule-26-flagged ring shadow) — no mixing of soft/hard/glow styles.

### Notes

- The whole surface has exactly one token file (`web/src/index.css` `:root`, lines 1-18) — good centralization, no per-component duplicate palettes found in `App.tsx`, `FilterPanel.tsx`, `GameTable.tsx`, `SummaryCards.tsx`, or `TimelineChart.tsx` (no inline `style=` usage in any `.tsx` file).
- `--accent-bg` is referenced with a fallback (`web/src/index.css:254`, `var(--accent-bg, rgba(102, 192, 244, 0.12))`) but never defined in `:root` — it always resolves to the fallback. Not one of the 28 rules, but worth fixing alongside Rule 11 token consolidation since it's effectively a phantom token.
- Several violations (Rule 11 spacing scale, Rule 24 corner nesting, Rule 22 button padding) share a root cause: values were chosen per-component rather than pulled from a shared scale. Fixing Rule 11 first (defining a spacing/radius scale) would make the Rule 22/24 fixes mechanical rather than case-by-case.
- `web/coverage/` and `web/dist/` contain generated/build CSS (`base.css`, `prettify.css`, `assets/index-*.css`) — excluded from this audit since they're build artifacts, not source.
