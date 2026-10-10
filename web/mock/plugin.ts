// Dev-only Vite plugin that serves the whole web-control API contract from
// memory (`npm run dev:mock`). `apply: 'serve'` plus the mode gate in
// vite.config.ts keep it out of every production build.

import { randomBytes } from 'node:crypto'
import type { Plugin } from 'vite'
import { TOKEN_META } from '../src/api/contract.ts'
import { handle } from './routes.ts'

export function mockApi(): Plugin {
  // Per-launch token, like the real server's web-<port>.token.
  const token = randomBytes(32).toString('hex')
  return {
    name: 'sbe-mock-api',
    apply: 'serve',
    transformIndexHtml() {
      return [{ tag: 'meta', attrs: { name: TOKEN_META, content: token }, injectTo: 'head' }]
    },
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        handle(req, res, token).then((handled) => {
          if (!handled) next()
        }, next)
      })
    },
  }
}
