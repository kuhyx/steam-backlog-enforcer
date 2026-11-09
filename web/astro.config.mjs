import { defineConfig } from 'astro/config'

// Static pages, one directory per section (`dist/library/index.html`), served
// by steam_backlog_enforcer._web_server, which injects the per-launch token
// into every page. In dev, `/api` is proxied to the Python server (SBE_PORT,
// default 8000) presenting itself as that server's own origin so its
// DNS-rebinding and origin checks pass; `--mode mock` (pnpm dev:mock) swaps
// the proxy for the in-memory contract mock in mock/. Both are dev-only:
// nothing here reaches `astro build` output.
const apiPort = process.env.SBE_PORT ?? '8000'
const apiOrigin = `http://127.0.0.1:${apiPort}`
const mode = process.argv.includes('--mode') ? process.argv[process.argv.indexOf('--mode') + 1] : ''

// The dev token meta comes from src/components/DevToken.astro (dev only).
async function devPlugins() {
  if (mode !== 'mock') return []
  const { mockApi } = await import('./mock/plugin.ts')
  return [mockApi()]
}

export default defineConfig({
  output: 'static',
  build: { format: 'directory', assets: 'assets' },
  trailingSlash: 'ignore',
  devToolbar: { enabled: false },
  vite: {
    plugins: process.argv.includes('dev') ? await devPlugins() : [],
    server:
      mode === 'mock'
        ? {}
        : { proxy: { '/api': { target: apiOrigin, changeOrigin: true, headers: { Origin: apiOrigin } } } },
  },
})
