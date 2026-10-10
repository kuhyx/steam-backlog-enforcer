import { describe, expect, it } from 'vitest'
import { makeInstalled, makeSpec } from '../test/fixtures'
import { commandLabel, fillPhrase, findCommand, phraseMatches } from './catalog'

const ctx = (installed = [makeInstalled()]) => ({
  gameName: (id: number) => (id === 7 ? 'Seven' : null),
  installed,
})

describe('catalog', () => {
  it('labels a command in title case', () => {
    expect(commandLabel('pick-manual')).toBe('Pick manual')
    expect(commandLabel('scan')).toBe('Scan')
  })

  it('forgives only surrounding whitespace', () => {
    expect(phraseMatches('delete it', '  delete it ')).toBe(true)
    expect(phraseMatches('delete it', 'Delete it')).toBe(false)
    expect(phraseMatches('delete it', 'delete  it')).toBe(false)
  })

  it('finds a command in the catalog', () => {
    const list = [makeSpec('scan'), makeSpec('done')]
    expect(findCommand(list, 'done')?.name).toBe('done')
    expect(findCommand(list, 'check')).toBeUndefined()
    expect(findCommand(undefined, 'check')).toBeUndefined()
  })
})

describe('fillPhrase', () => {
  it('fills from params', () => {
    expect(fillPhrase('abandon {app_id}', { app_id: 7 }, ctx())).toEqual({ text: 'abandon 7', missing: [] })
  })

  it('resolves {game_name} from the app id', () => {
    expect(fillPhrase('drop {game_name}', { app_id: 7 }, ctx()).text).toBe('drop Seven')
  })

  it('reports an unknown game or a missing app id', () => {
    expect(fillPhrase('drop {game_name}', { app_id: 8 }, ctx())).toEqual({ text: 'drop {game_name}', missing: ['game_name'] })
    expect(fillPhrase('drop {game_name}', {}, ctx()).missing).toEqual(['game_name'])
  })

  it('counts removable installed games for {count}', () => {
    const installed = [
      makeInstalled({ app_id: 1 }),
      makeInstalled({ app_id: 2, assigned: true }),
      makeInstalled({ app_id: 3, protected: true }),
      makeInstalled({ app_id: 4 }),
    ]
    expect(fillPhrase('remove {count} games', {}, ctx(installed)).text).toBe('remove 2 games')
  })

  it('cannot count before the installed list is known', () => {
    const c = { gameName: () => null, installed: null }
    expect(fillPhrase('remove {count}', {}, c).missing).toEqual(['count'])
  })

  it('treats an empty param as missing and an unknown key as missing', () => {
    expect(fillPhrase('{app_id} {nope}', { app_id: '' }, ctx()).missing).toEqual(['app_id', 'nope'])
  })
})
