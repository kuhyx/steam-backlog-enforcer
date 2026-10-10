import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Actions, Card, Facts, PageHead } from './Page'

describe('Page helpers', () => {
  it('PageHead renders the title and optional parts', () => {
    const { rerender } = render(<PageHead title="Jobs" />)
    expect(screen.getByRole('heading', { name: 'Jobs' })).toBeInTheDocument()
    expect(document.querySelector('.sub')).toBeNull()
    expect(document.querySelector('.page-actions')).toBeNull()
    rerender(
      <PageHead title="Jobs" sub="Sub text">
        <button type="button">Act</button>
      </PageHead>,
    )
    expect(screen.getByText('Sub text')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Act' })).toBeInTheDocument()
  })

  it('Card is a labelled region, with a head only when it has a title or aside', () => {
    const { rerender } = render(<Card title="Box">content</Card>)
    expect(screen.getByRole('region', { name: 'Box' })).toHaveTextContent('content')
    rerender(<Card aside={<span>aside</span>}>content</Card>)
    expect(screen.getByText('aside')).toBeInTheDocument()
    expect(screen.queryByRole('heading')).toBeNull()
    rerender(<Card className="x">bare</Card>)
    expect(document.querySelector('.box-head')).toBeNull()
    expect(document.querySelector('.box.x')).not.toBeNull()
  })

  it('Facts lists label/value pairs', () => {
    render(<Facts rows={[['A', 1], ['B', <b key="b">two</b>]]} />)
    expect(screen.getByText('A').tagName).toBe('DT')
    expect(screen.getByText('two').closest('dd')).not.toBeNull()
  })

  it('Actions titles its group', () => {
    render(<Actions><p>card</p></Actions>)
    expect(screen.getByRole('region', { name: 'Actions' })).toHaveTextContent('card')
    render(<Actions title="Custom"><p>c2</p></Actions>)
    expect(screen.getByRole('region', { name: 'Custom' })).toBeInTheDocument()
  })
})
