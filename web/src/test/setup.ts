import { configure } from '@testing-library/dom'
import * as matchers from '@testing-library/jest-dom/matchers'
import { afterEach, expect, vi } from 'vitest'
import { resetAll } from '../lib/query'

// Registered by hand: jest-dom 7 still augments vitest's old Assertion<T>
// shape, so `@testing-library/jest-dom/vitest` does not attach under vitest 5
// (same as dufs-cloud). Types live in jest-dom.d.ts next to this file.
expect.extend(matchers)

// The suite runs under a 10 % CPU cap (capped.sh); findBy*/waitFor's default
// 1 s budget then measures the scheduler, not the code.
configure({ asyncUtilTimeout: 5000 })

// jsdom has no modal <dialog>: model the open state, which is all the app
// and its tests observe (the browser supplies focus trap and Escape).
HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
  this.setAttribute('open', '')
}
HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
  this.removeAttribute('open')
}

// jsdom does no layout, so it has no scrollIntoView either.
Element.prototype.scrollIntoView = () => undefined
window.scrollTo = () => undefined

// Queries are module-level singletons: no test may see another's cache.
afterEach(() => {
  document.body.replaceChildren()
  resetAll()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})
