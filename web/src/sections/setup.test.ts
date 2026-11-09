import { screen, waitFor } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { q } from '../api/queries'
import { apiError, bodiesOf, mount, stubApi } from '../test/harness'
import { idError, keyError } from './setup'

const KEY = '0123456789abcdef0123456789ABCDEF'
const ID = '76561198000000000'
const status = (over = {}) => ({ configured: true, has_api_key: true, steam_id: ID, ...over })
const keyBox = () => screen.getByLabelText<HTMLInputElement>('Steam Web API key')
const idBox = () => screen.getByLabelText<HTMLInputElement>('SteamID64')
const saveButton = () => screen.getByRole('button', { name: 'Save and verify' })
const show = () => mount('<setup-form></setup-form>')

describe('validators', () => {
  it('accept trimmed well-formed values only', () => {
    expect(keyError(` ${KEY} `)).toBeNull()
    expect(keyError('nothex')).toMatch(/32 hexadecimal/)
    expect(idError(` ${ID} `)).toBeNull()
    expect(idError('123')).toMatch(/17 digits/)
  })
})

describe('setup-form', () => {
  it('prefills the id, never the key, and says a key is stored', async () => {
    stubApi({ 'GET /api/setup': status() })
    show()
    expect(keyBox()).toHaveValue('')
    expect(keyBox()).toHaveFocus()
    await waitFor(() => {
      expect(keyBox()).toHaveAttribute('placeholder', expect.stringContaining('A key is stored'))
    })
    expect(idBox()).toHaveValue(ID)
    expect(screen.queryByText('Not configured yet')).toBeNull()
    expect(screen.getByRole('link', { name: 'steamcommunity.com/dev/apikey' })).toBeInTheDocument()
  })

  it('warns on a first run, with a hint for the empty form', async () => {
    stubApi({ 'GET /api/setup': status({ configured: false, has_api_key: false, steam_id: null }) })
    show()
    expect(await screen.findByText('Not configured yet')).toBeInTheDocument()
    expect(keyBox()).toHaveAttribute('placeholder', '32 hex characters')
    expect(idBox()).toHaveValue('')
  })

  it('shows loading', async () => {
    stubApi({ 'GET /api/setup': () => new Promise(() => undefined) })
    show()
    expect(await screen.findByText(/Loading setup/)).toBeInTheDocument()
  })

  it('explains a failed load', async () => {
    stubApi({ 'GET /api/setup': apiError(500, 'op_failed', 'setup broke') })
    show()
    expect(await screen.findByText('setup broke')).toBeInTheDocument()
    expect(screen.queryByText(/Loading setup/)).toBeNull()
  })

  it('rejects malformed values, showing both reasons, then clears them as they are fixed', async () => {
    const mock = stubApi({ 'GET /api/setup': status({ steam_id: null }) })
    show()
    await userEvent.type(keyBox(), 'nothex')
    await userEvent.type(idBox(), '123')
    expect(screen.queryByText('The key is 32 hexadecimal characters.')).toBeNull()
    await userEvent.click(saveButton())
    expect(screen.getByText('The key is 32 hexadecimal characters.')).toBeInTheDocument()
    expect(screen.getByText('A SteamID64 is 17 digits and starts with 7656.')).toBeInTheDocument()
    expect(keyBox()).toHaveAttribute('aria-invalid', 'true')
    expect(keyBox()).toHaveClass('input-bad')
    expect(bodiesOf(mock, 'POST /api/setup')).toEqual([])
    await userEvent.clear(keyBox())
    await userEvent.type(keyBox(), KEY)
    expect(screen.queryByText('The key is 32 hexadecimal characters.')).toBeNull()
    expect(keyBox()).toHaveAttribute('aria-invalid', 'false')
    expect(screen.getByText(/never shown again/)).toBeInTheDocument()
  })

  it('accepts a fine key with a bad id, and a fine id with a bad key', async () => {
    stubApi({ 'GET /api/setup': status() })
    show()
    await waitFor(() => {
      expect(idBox()).toHaveValue(ID)
    })
    await userEvent.type(keyBox(), KEY)
    await userEvent.clear(idBox())
    await userEvent.click(saveButton())
    expect(screen.queryByText('The key is 32 hexadecimal characters.')).toBeNull()
    expect(screen.getByText(/17 digits/)).toBeInTheDocument()
  })

  it('saves trimmed values, clears the key and reports success', async () => {
    let stored = status({ has_api_key: false, steam_id: null, configured: false })
    const mock = stubApi({
      'GET /api/setup': () => stored,
      'POST /api/setup': () => (stored = status()),
    })
    show()
    expect(await screen.findByText('Not configured yet')).toBeInTheDocument()
    await userEvent.type(keyBox(), `  ${KEY}  `)
    await userEvent.type(idBox(), ` ${ID} `)
    await userEvent.click(saveButton())
    expect(await screen.findByText('Saved')).toBeInTheDocument()
    expect(bodiesOf(mock, 'POST /api/setup')).toEqual([{ steam_api_key: KEY, steam_id: ID }])
    expect(keyBox()).toHaveValue('')
    expect(screen.getByRole('link', { name: 'Go to the dashboard' })).toHaveAttribute('href', '/')
    expect(q.setup.state.data).toEqual(status())
    expect(screen.queryByText('Not configured yet')).toBeNull()
  })

  it('keeps the stored id when only the key changes', async () => {
    const mock = stubApi({ 'GET /api/setup': status(), 'POST /api/setup': status() })
    show()
    await waitFor(() => {
      expect(idBox()).toHaveValue(ID)
    })
    await userEvent.type(keyBox(), KEY)
    await userEvent.click(saveButton())
    await screen.findByText('Saved')
    expect(bodiesOf(mock, 'POST /api/setup')).toEqual([{ steam_api_key: KEY, steam_id: ID }])
  })

  it('never overwrites an id being typed when setup reloads', async () => {
    stubApi({ 'GET /api/setup': status({ steam_id: null }) })
    show()
    const box = idBox()
    await userEvent.type(box, '7656')
    q.setup.set(status())
    expect(idBox()).toBe(box)
    expect(box).toHaveValue('7656')
  })

  it('shows Steam’s refusal, and Checking… meanwhile', async () => {
    let answer: (v: unknown) => void = () => undefined
    stubApi({ 'GET /api/setup': status(), 'POST /api/setup': () => new Promise((r) => (answer = r)) })
    show()
    await waitFor(() => {
      expect(idBox()).toHaveValue(ID)
    })
    await userEvent.type(keyBox(), KEY)
    await userEvent.click(saveButton())
    expect(await screen.findByRole('button', { name: 'Checking with Steam…' })).toBeDisabled()
    answer(apiError(400, 'invalid_params', 'Steam rejected the key'))
    expect(await screen.findByText('Steam rejected the key')).toBeInTheDocument()
    expect(screen.queryByText('Saved')).toBeNull()
  })
})
