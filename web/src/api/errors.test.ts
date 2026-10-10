import { describe, expect, it } from 'vitest'
import { ApiFailure } from './client'
import { explain } from './errors'

describe('explain', () => {
  it('uses the table entry and the server message for an ApiFailure', () => {
    expect(explain(new ApiFailure('busy', 'job 3 is running', 409))).toMatchObject({
      code: 'busy',
      title: 'Another job is running',
      detail: 'job 3 is running',
    })
  })

  it('treats any other Error as an unexpected server error', () => {
    expect(explain(new Error('boom'))).toMatchObject({ code: 'http', title: 'Unexpected server error', detail: 'boom' })
  })

  it('stringifies a non-Error', () => {
    expect(explain('plain').detail).toBe('plain')
  })
})
