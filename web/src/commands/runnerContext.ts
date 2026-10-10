import { createContext, useContext } from 'react'
import type { CommandName } from '../api/contract'

export interface RunnerApi {
  /** Open the generic runner for a job command, optionally pre-filled. */
  run: (name: CommandName, preset?: Record<string, number | string>) => void
  openPalette: () => void
}

export const RunnerContext = createContext<RunnerApi>({ run: () => {}, openPalette: () => {} })

export function useRunner(): RunnerApi {
  return useContext(RunnerContext)
}
