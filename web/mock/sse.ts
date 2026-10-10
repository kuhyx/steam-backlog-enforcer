// Server-sent events for one job: replay everything after `after`, then
// follow live events, and close the stream once the job is terminal.

import type { IncomingMessage, ServerResponse } from 'node:http'
import type { JobEvent } from '../src/api/jobContract.ts'
import { isTerminal, type MockJob } from './jobs.ts'

const frame = (e: JobEvent) => `id: ${e.seq}\ndata: ${JSON.stringify(e)}\n\n`

export function streamEvents(req: IncomingMessage, res: ServerResponse, mj: MockJob, after: number): void {
  res.writeHead(200, {
    'Content-Type': 'text/event-stream',
    'Cache-Control': 'no-cache',
    Connection: 'keep-alive',
  })
  for (const e of mj.events) if (e.seq > after) res.write(frame(e))
  if (isTerminal(mj.job.state)) {
    res.end()
    return
  }
  const keepalive = setInterval(() => res.write(': keepalive\n\n'), 15_000)
  const listener = (e: JobEvent) => {
    res.write(frame(e))
    if (e.type === 'state' && isTerminal(e.state)) stop()
  }
  const stop = () => {
    clearInterval(keepalive)
    mj.listeners.delete(listener)
    res.end()
  }
  mj.listeners.add(listener)
  req.on('close', stop)
}
