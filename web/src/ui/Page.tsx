import type { ReactNode } from 'react'

export function PageHead({ title, sub, children }: { title: string; sub?: ReactNode; children?: ReactNode }) {
  return (
    <header className="page-head">
      <div>
        <h1>{title}</h1>
        {sub && <p className="sub">{sub}</p>}
      </div>
      {children && <div className="page-actions">{children}</div>}
    </header>
  )
}

export function Card({ title, children, className = '', aside }: { title?: string; children: ReactNode; className?: string; aside?: ReactNode }) {
  return (
    <section className={`box ${className}`} aria-label={title}>
      {(title || aside) && (
        <div className="box-head">
          {title && <h2>{title}</h2>}
          {aside}
        </div>
      )}
      {children}
    </section>
  )
}

/** Label/value rows; values are right-aligned so they line up across cards. */
export function Facts({ rows }: { rows: [ReactNode, ReactNode][] }) {
  return (
    <dl className="facts">
      {rows.map(([k, v], i) => (
        <div key={i} className="fact">
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  )
}

/** Grid of CommandCards. */
export function Actions({ title = 'Actions', children }: { title?: string; children: ReactNode }) {
  return (
    <section className="actions-block" aria-label={title}>
      <h2>{title}</h2>
      <div className="cmd-grid">{children}</div>
    </section>
  )
}
