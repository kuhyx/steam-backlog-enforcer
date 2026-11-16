// A done/check job is not cancellable as a command, but it announces a cancel
// window while it hides games in the Steam library: Cancel shows only then.

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { bodiesOf, installEventSource } from '../test/harness'
import { button } from '../test/events'
import { mountJob } from '../test/jobHelpers'

beforeEach(installEventSource)

const cancelButton = (el: Element) => el.querySelector('[aria-label="Cancel job"]')

describe('<job-progress> cancel window', () => {
  it('shows Cancel only while the job reports the window open', async () => {
    const { el, send } = mountJob({ cancellable: false })
    await vi.waitFor(() => { expect(el.querySelector('section')).not.toBeNull() })
    send('state', { state: 'running' })
    expect(cancelButton(el)).toBeNull()

    send('cancel_window', { open: true })
    expect(cancelButton(el)).not.toBeNull()

    send('cancel_window', { open: false })
    expect(cancelButton(el)).toBeNull()
  })

  it('cancels through the API from inside the window', async () => {
    const { el, send, routes, id, mock } = mountJob({ cancellable: false })
    routes[`POST /api/jobs/${id}/cancel`] = undefined
    send('state', { state: 'running' })
    send('cancel_window', { open: true })
    button(el, 'Cancel job').click()
    await vi.waitFor(() => {
      expect(bodiesOf(mock, `POST /api/jobs/${id}/cancel`)).toHaveLength(1)
    })
  })

  it('drops the button once the job has finished, window or not', () => {
    const { el, send } = mountJob({ cancellable: false })
    send('cancel_window', { open: true })
    send('state', { state: 'succeeded' })
    expect(cancelButton(el)).toBeNull()
  })
})
