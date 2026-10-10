import { useState, type ReactNode } from 'react'
import { explain } from '../api/errors'

type Tone = 'info' | 'success' | 'warning' | 'danger'

export function Notice({ tone = 'info', title, children }: { tone?: Tone; title?: string; children?: ReactNode }) {
  return (
    <div className={`notice notice-${tone}`} role={tone === 'danger' ? 'alert' : 'status'}>
      {title && <strong className="notice-title">{title}</strong>}
      {children && <div className="notice-text">{children}</div>}
    </div>
  )
}

/** An ApiFailure (or anything thrown) as a titled, actionable message. */
export function ErrorNotice({ error, children }: { error: unknown; children?: ReactNode }) {
  const e = explain(error)
  return (
    <Notice tone="danger" title={e.title}>
      {e.detail && <p className="m0">{e.detail}</p>}
      <p className="m0 muted">{e.hint}</p>
      {children}
    </Notice>
  )
}

export function CopyButton({ text, label = 'Copy' }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      type="button"
      className="btn btn-ghost btn-small"
      onClick={() => {
        void navigator.clipboard?.writeText(text).then(() => {
          setCopied(true)
          setTimeout(() => setCopied(false), 2000)
        })
      }}
    >
      {copied ? 'Copied' : label}
    </button>
  )
}

/** A shell command with a copy button — the recovery path when the UI cannot act. */
export function CommandLine({ command }: { command: string }) {
  return (
    <div className="cmdline">
      <code>{command}</code>
      <CopyButton text={command} />
    </div>
  )
}

export function Loading({ what }: { what: string }) {
  return (
    <p className="loading" role="status">
      <span className="spinner" aria-hidden="true" /> Loading {what}…
    </p>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>
}
