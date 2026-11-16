// Pass 2 wiring for the dashboard, picks, store, setup and library pages:
// a ledger word shows right of its icon, a chosen alternative glyph replaces
// the default, and the spoken text is unchanged.

import { screen, waitFor } from '@testing-library/dom'
import { describe, expect, it } from 'vitest'
import { makeInstalled, makeLibGame, makeStatus } from '../test/fixtures'
import { mount, stubApi } from '../test/harness'
import { useIcons } from '../test/iconLedger'
import './dashboard'
import './library'
import './picks'
import './setup'
import './store'

const word = (el: Element | null | undefined) => el?.nextElementSibling?.textContent
const markOf = (root: ParentNode, id: string) => root.querySelector(`[data-icon="${id}"], [data-icon-word="${id}"]`)

describe('dashboard icons', () => {
  it('a fact row paints its icon word and chosen glyph, the label stays spoken', async () => {
    useIcons({ 'dash.finished': { word: 'trophies', glyph: '🥇' }, 'state.yes': { word: 'yes' } })
    stubApi({ 'GET /api/status': makeStatus(), 'GET /api/commands': [] })
    mount('<dashboard-status></dashboard-status>')
    const label = await screen.findByText('Games finished', { selector: 'dt .sr-only' })
    const icon = label.closest('dt')?.querySelector('[data-icon="dash.finished"]')
    expect(icon?.textContent).toBe('🥇')
    expect(word(icon)).toBe('Trophies')
    expect(label).toHaveClass('sr-only')
    const installed = screen.getByText('Installed', { selector: 'dt .sr-only' }).closest('dt')?.nextElementSibling
    expect(word(installed?.querySelector('[data-icon="state.yes"]'))).toBe('Yes')
  })

  it('the store row and the block countdown use their own icons', async () => {
    useIcons({ 'dash.store-blocked': { word: 'shut' }, 'dash.block-left': { word: 'left' } })
    stubApi({
      'GET /api/status': makeStatus({ total_block: { active: true, days_remaining: 2, until: null } }),
      'GET /api/commands': [],
    })
    const el = mount('<dashboard-status></dashboard-status>')
    await screen.findAllByText('Store', { selector: 'dt .sr-only' })
    expect(word(markOf(el, 'dash.store-blocked'))).toBe('Shut')
    expect(word(markOf(el, 'dash.block-left'))).toBe('Left')
  })
})

describe('store notice icon', () => {
  it('paints the store-lock icon, its word and glyph, the sentence stays spoken', async () => {
    useIcons({ 'store.blocked': { word: 'sealed', glyph: '🛑' } })
    stubApi({ 'GET /api/status': makeStatus({ store_blocked: true }) })
    mount('<store-notice></store-notice>')
    const notice = await screen.findByRole('status')
    const icon = markOf(notice, 'store.blocked')
    expect(icon?.textContent).toBe('🛑')
    expect(word(icon)).toBe('Sealed')
    expect(screen.getByText(/Store blocked\./)).toHaveClass('sr-only')
  })
})

describe('picks icons', () => {
  it('a pick row paints the age icon and the kept pin with their words', async () => {
    const pick = (app_id: number, name: string) => ({ app_id, name, age_days: 3 })
    useIcons({ 'picks.age': { word: 'picked' }, 'picks.kept': { word: 'kept', glyph: '💚' } })
    stubApi({
      'GET /api/status': makeStatus({ manual_picks: [pick(1, 'Celeste')], kept_picks: [pick(2, 'Hades')] }),
      'GET /api/commands': [],
    })
    const el = mount('<manual-picks></manual-picks>')
    await screen.findByText('Celeste')
    expect(word(markOf(el, 'picks.age'))).toBe('Picked')
    const kept = markOf(el, 'picks.kept')
    expect(kept?.textContent).toBe('💚')
    expect(word(kept)).toBe('Kept')
    expect(screen.getByText('· picked 3 d ago · 1')).toHaveClass('sr-only')
  })
})

describe('setup icons', () => {
  it('the field icons and the stored-key placeholder follow the ledger', async () => {
    useIcons({ 'setup.api-key': { word: 'key' }, 'setup.key-stored': { word: 'stored', glyph: '🔐' } })
    stubApi({ 'GET /api/setup': { configured: true, has_api_key: true, steam_id: '76561198000000000' } })
    const el = mount('<setup-form></setup-form>')
    expect(word(markOf(el, 'setup.api-key'))).toBe('Key')
    expect(screen.getByLabelText<HTMLInputElement>('Steam Web API key')).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByLabelText<HTMLInputElement>('Steam Web API key').placeholder).toBe(`🔐 Stored ${'•'.repeat(32)}`)
    })
  })
})

describe('library page icons', () => {
  it('the installed table headers and the view switch paint their words', async () => {
    useIcons({ 'libpage.size': { word: 'space', glyph: '📏' }, 'libpage.all': { word: 'covers' } })
    stubApi({
      'GET /api/library': { games: [makeLibGame({ app_id: 1, name: 'Hollow Knight' })] },
      'GET /api/installed': { games: [makeInstalled({ app_id: 5, name: 'Portal' })] },
      'GET /api/commands': [],
    })
    mount('<library-view></library-view>')
    const th = (await screen.findByText('Size', { selector: 'th .sr-only' })).closest('th')
    expect(th?.querySelector('[data-icon="libpage.size"]')?.textContent).toBe('📏')
    expect(word(th?.querySelector('[data-icon="libpage.size"]'))).toBe('Space')
    expect(screen.getByRole('button', { name: 'All games' })).toHaveTextContent('Covers')
  })
})
