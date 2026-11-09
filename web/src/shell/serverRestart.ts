// Restart the web server (was useServerRestart.ts). Its token changes with
// the process, so once the new instance answers with a later `started_at`
// the page reloads to pick the new token up from the served HTML.

import { api } from '../api/client'
import { q } from '../api/queries'
import { Action } from '../lib/action'

export class ServerRestart {
  readonly action: Action<[], void>
  private waitingFor: string | null = null
  private unwatch: (() => void) | null = null

  constructor(onChange: () => void) {
    this.action = new Action(async () => {
      await api.restartServer()
      this.waitingFor = q.server.state.data?.started_at ?? ''
      this.unwatch ??= q.server.subscribe((s) => {
        const startedAt = s.data?.started_at
        if (this.waitingFor !== null && startedAt && startedAt !== this.waitingFor) window.location.reload()
      })
    }, onChange)
  }

  get restarting(): boolean {
    return this.waitingFor !== null
  }

  dispose(): void {
    this.unwatch?.()
    this.unwatch = null
  }
}
