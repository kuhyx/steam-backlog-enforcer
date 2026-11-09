// Dev-only Vite plugin that serves the whole web-control API contract from
// memory (`pnpm dev:mock`). `apply: 'serve'` plus the mode gate in
// astro.config.mjs keep it out of every production build.

import { randomBytes } from 'node:crypto'
import type { AstroUserConfig } from 'astro'
import { handle } from './routes.ts'

// Vite is Astro's, not a direct dependency: take its Plugin type from there.
type PluginOption = NonNullable<NonNullable<AstroUserConfig['vite']>['plugins']>[number]
type Plugin = Extract<PluginOption, { name: string }>

export function mockApi(): Plugin {
  // Per-launch token, like the real server's web-<port>.token.
  const token = randomBytes(32).toString('hex')
  return {
    name: 'sbe-mock-api',
    apply: 'serve',
    // src/components/DevToken.astro renders this into every page in dev.
    config() {
      process.env.SBE_DEV_TOKEN = token
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
