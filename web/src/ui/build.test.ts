import { describe, expect, it, vi } from 'vitest'
import { ApiFailure } from '../api/client'
import { h } from '../lib/dom'
import { card, commandLine, copyButton, empty, errorNotice, facts, link, loading, notice, pill } from './build'

describe('notice', () => {
  it('is an alert for danger and a status otherwise', () => {
    expect(notice('danger', 'T').getAttribute('role')).toBe('alert')
    expect(notice('info', 'T').getAttribute('role')).toBe('status')
  })

  it('renders title and text only when given', () => {
    const full = notice('warning', 'Title', 'body')
    expect(full.className).toBe('notice notice-warning')
    expect(full.querySelector('.notice-title')?.textContent).toBe('Title')
    expect(full.querySelector('.notice-text')?.textContent).toBe('body')
    const bare = notice('success', null)
    expect(bare.children).toHaveLength(0)
  })
})

describe('errorNotice', () => {
  it('explains an ApiFailure with detail, hint and extras', () => {
    const el = errorNotice(new ApiFailure('busy', 'Job j1 runs', 409), h('em', {}, 'extra'))
    expect(el).toHaveTextContent('Another job is running')
    expect(el).toHaveTextContent('Job j1 runs')
    expect(el).toHaveTextContent('Only one state-changing job')
    expect(el.querySelector('em')).not.toBeNull()
  })

  it('omits the detail line when the message is empty', () => {
    const el = errorNotice(new ApiFailure('busy', '', 409))
    expect(el.querySelectorAll('p')).toHaveLength(1)
  })
})

describe('copyButton and commandLine', () => {
  it('copies, shows Copied, then restores the label', async () => {
    vi.useFakeTimers()
    const writeText = vi.fn(() => Promise.resolve())
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    const btn = copyButton('sudo x')
    btn.click()
    await vi.advanceTimersByTimeAsync(0)
    expect(writeText).toHaveBeenCalledWith('sudo x')
    expect(btn.textContent).toBe('Copied')
    await vi.advanceTimersByTimeAsync(2000)
    expect(btn.textContent).toBe('Copy')
  })

  it('uses a custom label', () => {
    expect(copyButton('x', 'Grab').textContent).toBe('Grab')
  })

  it('commandLine shows the command beside its copy button', () => {
    const el = commandLine('./run.sh serve')
    expect(el.querySelector('code')?.textContent).toBe('./run.sh serve')
    expect(el.querySelector('button')).not.toBeNull()
  })
})

describe('small builders', () => {
  it('loading names what is loading', () => {
    const el = loading('jobs')
    expect(el).toHaveTextContent('Loading jobs…')
    expect(el.getAttribute('role')).toBe('status')
  })

  it('empty, pill and link', () => {
    expect(empty('Nothing').className).toBe('empty')
    expect(pill('danger', 'x').className).toBe('pill pill-danger')
    const a = link('/library/', 'Open')
    expect(a.getAttribute('href')).toBe('/library/')
    expect(a.className).toBe('btn btn-ghost btn-small')
    expect(link('/x/', 'Y', 'custom').className).toBe('custom')
  })

  it('facts lays out label/value rows', () => {
    const el = facts([['A', '1'], ['B', h('b', {}, '2')]])
    expect(el.querySelectorAll('.fact')).toHaveLength(2)
    expect(el.querySelector('dt')?.textContent).toBe('A')
    expect(el.querySelectorAll('dd')[1].textContent).toBe('2')
  })
})

describe('card', () => {
  it('has a titled head with an aside and a class', () => {
    const el = card('Title', 'body', { aside: h('i', {}, 'x'), className: 'wide' })
    expect(el.className).toBe('box wide')
    expect(el.getAttribute('aria-label')).toBe('Title')
    expect(el.querySelector('.box-head h2')?.textContent).toBe('Title')
    expect(el.querySelector('.box-head i')).not.toBeNull()
  })

  it('has a head with only an aside, or none at all', () => {
    const asideOnly = card(null, 'b', { aside: 'right' })
    expect(asideOnly.querySelector('h2')).toBeNull()
    expect(asideOnly.querySelector('.box-head')).toHaveTextContent('right')
    expect(asideOnly.hasAttribute('aria-label')).toBe(false)
    const titleOnly = card('T', 'b')
    expect(titleOnly.className).toBe('box')
    expect(titleOnly.querySelector('.box-head')?.children).toHaveLength(1)
    const none = card(null, 'b')
    expect(none.querySelector('.box-head')).toBeNull()
    expect(none).toHaveTextContent('b')
  })
})
