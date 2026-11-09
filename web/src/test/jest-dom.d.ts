import type { TestingLibraryMatchers } from "@testing-library/jest-dom/matchers";
import "vitest";

// See setup.ts: vitest 5's Assertion takes <R, T>; jest-dom 7's own
// augmentation targets the vitest 4 shape and silently no-ops.
/* eslint-disable @typescript-eslint/no-empty-object-type -- declaration merging needs the empty extends */
declare module "vitest" {
  interface Assertion<R, T> extends TestingLibraryMatchers<R, T> {}
  interface AsymmetricMatchersContaining
    extends TestingLibraryMatchers<unknown, unknown> {}
}
