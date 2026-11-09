import { screen } from '@testing-library/dom'
import { describe, expect, it } from 'vitest'
import { mount, stubApi } from '../../test/harness'
import './setupCard'

const setup = (over = {}) => ({ configured: true, has_api_key: true, steam_id: '7656119800000000', ...over })

describe('setup-card', () => {
  it('summarises setup, linking to the setup page', async () => {
    stubApi({ 'GET /api/setup': setup() })
    mount('<setup-card></setup-card>')
    expect(await screen.findByText('Stored (never shown)')).toBeInTheDocument()
    expect(screen.getByText('Yes')).toBeInTheDocument()
    expect(screen.getByText('7656119800000000')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open setup' })).toHaveAttribute('href', '/setup/')
  })

  it('reports an unconfigured setup', async () => {
    stubApi({ 'GET /api/setup': setup({ configured: false, has_api_key: false, steam_id: null }) })
    mount('<setup-card></setup-card>')
    expect(await screen.findByText('Missing')).toBeInTheDocument()
    expect(screen.getByText('No')).toBeInTheDocument()
  })

  it('shows placeholders until setup loads', () => {
    stubApi({ 'GET /api/setup': () => new Promise(() => undefined) })
    mount('<setup-card></setup-card>')
    const region = screen.getByRole('region', { name: 'Setup' })
    expect(region.textContent.match(/…/g)).toHaveLength(2)
    expect(region).toHaveTextContent('—')
  })
})
