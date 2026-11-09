# web

The loopback control UI: Astro static pages (one per section) with vanilla
TypeScript custom elements, served from `dist/` by `steam_backlog_enforcer._web_server`.

`pnpm dev` (proxies `/api` to `./run.sh serve`), `pnpm dev:mock` (in-memory API),
`pnpm test`, `pnpm coverage`, `pnpm lint`, `pnpm build`.
