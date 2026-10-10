import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'
import { queryClient } from '../api/queries'

// The app shares one query client; tests must not see each other's cache,
// and a failing query must fail fast instead of retrying.
queryClient.setDefaultOptions({
  queries: { retry: false, staleTime: 0, refetchOnWindowFocus: false },
})

// jsdom has no modal <dialog>: model the open state, which is all the app
// and its tests observe (the browser supplies focus trap and Escape).
HTMLDialogElement.prototype.showModal = function showModal() {
  this.setAttribute('open', '')
}
HTMLDialogElement.prototype.close = function close() {
  this.removeAttribute('open')
}

// jsdom does no layout, so it has no scrollIntoView either.
Element.prototype.scrollIntoView = () => {}
window.scrollTo = () => {}

// React Testing Library does not auto-clean when Vitest globals are disabled.
afterEach(() => {
  cleanup()
  queryClient.clear()
})
