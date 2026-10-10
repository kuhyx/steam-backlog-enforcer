import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import babel from '@rolldown/plugin-babel'
import react, { reactCompilerPreset } from '@vitejs/plugin-react'
import type { Plugin, PluginOption } from 'vite'
import { defineConfig, type ViteUserConfig } from 'vitest/config'
import { TOKEN_META } from './src/api/contract.ts'

// The Python API (`./run.sh serve`) runs on 127.0.0.1:8000 (`SBE_PORT` to
// point dev at another one). In dev, Vite serves the UI and proxies `/api/*`
// to it, so there are no CORS concerns. The proxy presents itself as the
// API's own origin (Host + Origin) so the server's DNS-rebinding and origin
// checks pass, and `serverToken()` puts that server's per-launch token into
// index.html the way the server does for the built bundle. In production
// the Python server serves the built bundle from `web/dist`.
//
// `--mode mock` (npm run dev:mock) swaps the proxy for an in-memory mock of
// the whole contract (web/mock/). It is imported only in that mode and is a
// serve-only plugin, so none of it can reach `vite build` output.
//
// React Compiler runs through Babel: plugin-react 6's native (Oxc) compiler
// is experimental and its `oxc-transform-react` peer range trails the newest
// stable release.
const apiPort = process.env.SBE_PORT ?? '8000'
const apiOrigin = `http://127.0.0.1:${apiPort}`

/**
 * Dev only (`apply: 'serve'`): inject `<meta name="sbe-token">` from the
 * API server's token file, re-read on every page load so a restarted server's
 * new token is picked up by a reload. Never part of `vite build`.
 */
function serverToken(): Plugin {
  const runtime = process.env.XDG_RUNTIME_DIR ?? `/run/user/${process.getuid?.() ?? 0}`
  const file = join(runtime, 'steam-backlog-enforcer', `web-${apiPort}.token`)
  return {
    name: 'sbe-server-token',
    apply: 'serve',
    transformIndexHtml(html) {
      let token: string
      try {
        token = readFileSync(file, 'utf8').trim()
      } catch {
        console.warn(`[sbe] no token at ${file}: is ./run.sh serve running on port ${apiPort}? Mutating requests will fail.`)
        return html
      }
      return [{ tag: 'meta', attrs: { name: TOKEN_META, content: token }, injectTo: 'head-prepend' }]
    },
  }
}

export default defineConfig(async ({ mode }): Promise<ViteUserConfig> => {
  // Not under vitest: the Compiler's generated memo-cache branches (e.g. the
  // "cache hit" arm for a closure that is rebuilt every render) are counted by
  // v8 coverage but can never run, so 100 % branch coverage of the *source*
  // would be unreachable. The compiled output is still built and linted
  // (`eslint-plugin-react-hooks` carries the Compiler's rules).
  const plugins: PluginOption[] = [react()]
  if (mode !== 'test') plugins.push(babel({ presets: [reactCompilerPreset()] }))
  if (mode === 'mock') {
    const { mockApi } = await import('./mock/plugin.ts')
    plugins.push(mockApi())
  } else {
    plugins.push(serverToken())
  }
  return {
    plugins,
    server:
      mode === 'mock'
        ? {}
        : {
            proxy: {
              '/api': { target: apiOrigin, changeOrigin: true, headers: { Origin: apiOrigin } },
            },
          },
    test: {
      environment: 'jsdom',
      setupFiles: './src/test/setup.ts',
      coverage: {
        provider: 'v8',
        include: ['src/**/*.{ts,tsx}'],
        exclude: [
          'src/**/*.test.{ts,tsx}',
          'src/test/**',
          'src/main.tsx',
          'src/vite-env.d.ts',
        ],
        thresholds: {
          statements: 100,
          branches: 100,
          functions: 100,
          lines: 100,
        },
      },
    },
  }
})
