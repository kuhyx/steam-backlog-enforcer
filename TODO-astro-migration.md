# Migrate steam-backlog-enforcer/web to Astro (no React)

## what
Rebuild the loopback dashboard (`web/`) as Astro 7 static pages, one per
section. Scripts fetch and render in vanilla TS, and stateful widgets become
custom elements. TanStack Router and React Query go away.
`steam_backlog_enforcer._web_server` keeps serving `web/dist` on
127.0.0.1:8000, with its per-launch token.

**Order: this repo migrates LAST, after every other repo.**

## steps
1. Do `~/src/utils/web_ui/TODO-astro-port.md` first. Then add `@kuhyx/web-ui`
   at the new tag, for `tokens.css` only.
2. Pages. The router routes become `src/pages/`:
   - `index` (dashboard), `backlog`, `picks`, `library`, `store`, `gaming`,
     `jobs`, `system`, `setup`, and `404.astro`.
   - `/jobs/$jobId` becomes `jobs/?id=<id>`, because static output cannot
     prerender unknown ids.
   - `shell/AppShell.tsx` becomes `layouts/Shell.astro`, with nav, health and
     the job indicator.
3. Server (`_web_server.py`):
   - Serve `<path>/index.html` before the SPA fallback.
   - Inject the token into EVERY served `.html`, not only the root
     `index.html`, and mark each one no-cache.
   - Add tests to `tests/test_web_server_static.py`.
4. `_web_build.py` calls `npm run build`. Change it to `pnpm build`, and update
   its "npm missing" message. Delete `web/package-lock.json`, so pnpm is the
   only lockfile.
5. Rewrite the 45 React files:
   - `screens/*` (10, plus `system/*` 3) become `.astro` pages and sections.
   - `components/*` (10): `GameTable` and `FilterPanel` become a
     `<game-table>` custom element. The budget cards are `.astro` plus a
     poller. `TimelineChart` and `BudgetHistoryChart` become SVG builders in
     `src/lib/charts/`.
   - `commands/*` (7): `<command-palette>` and `<runner-dialog>` custom
     elements on `<dialog>`. `RunnerProvider` becomes a module-level store.
   - `jobs/*` (4): `<job-progress>` subscribes to the SSE `EventSource`.
     `library/*` (3) becomes `<game-browser>`.
   - `ui/*` (3) and `shell/*` (3) become `.astro`. Delete `router.tsx` and `App.tsx`.
   - Hooks (`useBudgetPoll.ts`, `api/queries.ts` and the other React-only `.ts`
     files) become plain fetch, poll and cache helpers in `src/lib/`.
6. Mock mode. `web/mock/plugin.ts` stays a Vite plugin, added through
   `vite.plugins` in `astro.config.mjs` when `MODE=mock`. `dev:mock` becomes
   `astro dev --mode mock`.
7. Dependencies, from `web/`, exact pins via pnpm:
   - Add `astro@7.4.4`, `@astrojs/check@0.9.12`, `eslint-plugin-astro@3.2.1`
     and `@testing-library/dom`.
   - Remove `react`, `react-dom`, `@tanstack/react-query`, `@tanstack/react-router`,
     `@vitejs/plugin-react`, `babel-plugin-react-compiler`, `@babel/core`,
     `@rolldown/plugin-babel` and `@testing-library/react`.
   - Drop direct `vite`. Replace or delete the Vite template `web/README.md`.
8. Tests. Use vitest 5.0.5 with `getViteConfig()`:
   - Elements and helpers are tested in jsdom against the `mock/` world.
   - The Container API renders each page.
   - Coverage is scoped to `src/**/*.ts`.
9. There is no `[agent_ready]` table. It is a loopback app, so skip AgentReady.

## done
Run from `web/`:
`pnpm install --frozen-lockfile && pnpm exec astro check && pnpm coverage && pnpm build`
Then:
`! grep -q '"react"' package.json && ! grep -qE '"(react-dom|@vitejs/plugin-react|@tanstack/react-[a-z]+)"' package.json && ! find src -name '*.tsx' | grep -q . && test ! -f package-lock.json`
Both exit 0. Also run the repo root's
`python -m pytest -q steam_backlog_enforcer/tests/test_web_server_static.py`.

## verify
Start the live server the way the repo does (`_serve_startup.py`) on
127.0.0.1:8000. Use a headless chromium on `/`, `/library/` and
`/jobs/?id=<real id>`:
- Every page carries the token and the API calls return 200.
- The command palette runs a dry command.
- There are no console errors.

## read first
- `~/src/utils/web_ui/TODO-astro-port.md` (do it first)
- `web/src/router.tsx`, `web/src/api/queries.ts`, `web/mock/plugin.ts`, `web/vite.config.ts`
- `steam_backlog_enforcer/_web_server.py`, `_web_auth.py`, `_web_build.py`

REMOVE ME AFTER FINISH
