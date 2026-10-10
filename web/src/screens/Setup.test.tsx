import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { queryClient } from '../api/queries'
import { apiError, bodiesOf, renderRouted, stubApi } from '../test/harness'
import { Setup } from './Setup'

const KEY = '0123456789abcdef0123456789ABCDEF'
const ID = '76561198000000000'
const status = (over = {}) => ({ configured: true, has_api_key: true, steam_id: ID, ...over })
const keyBox = () => screen.findByLabelText('Steam Web API key')
const idBox = () => screen.getByLabelText('SteamID64')

describe('Setup', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('prefills the id, never the key, and says a key is stored', async () => {
    stubApi({ 'GET /api/setup': status() })
    renderRouted(<Setup />)
    const key = await keyBox()
    expect(key).toHaveValue('')
    expect(key).toHaveFocus()
    await waitFor(() => expect(key).toHaveAttribute('placeholder', expect.stringContaining('A key is stored')))
    await waitFor(() => expect(idBox()).toHaveValue(ID))
    expect(screen.queryByText('Not configured yet')).toBeNull()
  })

  it('warns on a first run, with a hint for the empty form', async () => {
    stubApi({ 'GET /api/setup': status({ configured: false, has_api_key: false, steam_id: null }) })
    renderRouted(<Setup />)
    expect(await screen.findByText('Not configured yet')).toBeInTheDocument()
    expect(await keyBox()).toHaveAttribute('placeholder', '32 hex characters')
    expect(idBox()).toHaveValue('')
  })

  it('shows loading, then a failure', async () => {
    stubApi({ 'GET /api/setup': () => new Promise(() => {}) })
    renderRouted(<Setup />)
    expect(await screen.findByText(/Loading setup/)).toBeInTheDocument()
  })

  it('explains a failed load', async () => {
    stubApi({ 'GET /api/setup': apiError(500, 'op_failed', 'setup broke') })
    renderRouted(<Setup />)
    expect(await screen.findByText('setup broke')).toBeInTheDocument()
    expect(screen.queryByText(/Loading setup/)).toBeNull()
  })

  it('rejects malformed values, showing both reasons', async () => {
    const mock = stubApi({ 'GET /api/setup': status({ steam_id: null }) })
    renderRouted(<Setup />)
    await userEvent.type(await keyBox(), 'nothex')
    await userEvent.type(idBox(), '123')
    await userEvent.click(screen.getByRole('button', { name: 'Save and verify' }))
    expect(screen.getByText('The key is 32 hexadecimal characters.')).toBeInTheDocument()
    expect(screen.getByText('A SteamID64 is 17 digits and starts with 7656.')).toBeInTheDocument()
    expect(screen.getByLabelText('Steam Web API key')).toHaveAttribute('aria-invalid', 'true')
    expect(bodiesOf(mock, 'POST /api/setup')).toEqual([])
  })

  it('accepts a fine key with a bad id, and a fine id with a bad key', async () => {
    stubApi({ 'GET /api/setup': status() })
    renderRouted(<Setup />)
    await userEvent.type(await keyBox(), KEY)
    await userEvent.clear(idBox())
    await userEvent.click(screen.getByRole('button', { name: 'Save and verify' }))
    expect(screen.queryByText('The key is 32 hexadecimal characters.')).toBeNull()
    expect(screen.getByText(/17 digits/)).toBeInTheDocument()
  })

  it('saves trimmed values, clears the key and reports success', async () => {
    let stored = status({ has_api_key: false, steam_id: null, configured: false })
    const mock = stubApi({
      'GET /api/setup': () => stored,
      'POST /api/setup': () => (stored = status()),
    })
    renderRouted(<Setup />)
    await userEvent.type(await keyBox(), `  ${KEY}  `)
    await userEvent.type(idBox(), ` ${ID} `)
    await userEvent.click(screen.getByRole('button', { name: 'Save and verify' }))
    expect(await screen.findByText('Saved')).toBeInTheDocument()
    expect(bodiesOf(mock, 'POST /api/setup')).toEqual([{ steam_api_key: KEY, steam_id: ID }])
    expect(screen.getByLabelText('Steam Web API key')).toHaveValue('')
    expect(screen.getByRole('link', { name: 'Go to the dashboard' })).toHaveAttribute('href', '/')
    expect(queryClient.getQueryData(['setup'])).toEqual(status())
  })

  it('keeps the stored id when only the key changes', async () => {
    const mock = stubApi({ 'GET /api/setup': status(), 'POST /api/setup': status() })
    renderRouted(<Setup />)
    await userEvent.type(await keyBox(), KEY)
    await waitFor(() => expect(idBox()).toHaveValue(ID))
    await userEvent.click(screen.getByRole('button', { name: 'Save and verify' }))
    await screen.findByText('Saved')
    expect(bodiesOf(mock, 'POST /api/setup')).toEqual([{ steam_api_key: KEY, steam_id: ID }])
  })

  it('shows Steam’s refusal, and Checking… meanwhile', async () => {
    let answer: (v: unknown) => void = () => {}
    stubApi({ 'GET /api/setup': status(), 'POST /api/setup': () => new Promise((r) => (answer = r)) })
    renderRouted(<Setup />)
    await userEvent.type(await keyBox(), KEY)
    await waitFor(() => expect(idBox()).toHaveValue(ID))
    await userEvent.click(screen.getByRole('button', { name: 'Save and verify' }))
    expect(await screen.findByRole('button', { name: 'Checking with Steam…' })).toBeDisabled()
    answer(apiError(400, 'invalid_params', 'Steam rejected the key'))
    expect(await screen.findByText('Steam rejected the key')).toBeInTheDocument()
    expect(screen.queryByText('Saved')).toBeNull()
  })
})
