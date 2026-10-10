import { useEffect, useRef, type ReactNode } from 'react'

interface Props {
  open: boolean
  title: string
  onClose: () => void
  children: ReactNode
  /** Wider layout for the job runner. */
  wide?: boolean
  labelledBy?: string
}

/**
 * Native `<dialog>` in modal mode: the browser supplies the focus trap, the
 * inert background and Escape (routed through `onClose` so React stays the
 * owner of `open`). Focus returns to the opener when it closes.
 */
export function Dialog({ open, title, onClose, children, wide = false }: Props) {
  const ref = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    // Effects run after commit, when the <dialog> below is always mounted.
    const el = ref.current as HTMLDialogElement
    if (open && !el.open) {
      el.showModal()
      // Children mounted while the dialog was still closed (display: none),
      // so React's autoFocus could not land. The browser then picks the
      // first focusable — the close button. Move focus to the first field,
      // else the first action, which is what every dialog here wants.
      el.querySelector<HTMLElement>(
        'input:not([disabled]):not([type=hidden]), textarea, select, .dialog-body button:not(.dialog-close):not([disabled])',
      )?.focus()
    }
    if (!open && el.open) el.close()
  }, [open])

  return (
    <dialog
      ref={ref}
      className={wide ? 'dialog dialog-wide' : 'dialog'}
      aria-label={title}
      onCancel={(e) => {
        e.preventDefault()
        onClose()
      }}
    >
      {open && (
        <div className="dialog-body">
          <header className="dialog-head">
            <h2>{title}</h2>
            <button type="button" className="btn btn-ghost btn-icon dialog-close" onClick={onClose} aria-label="Close">
              <span aria-hidden="true">×</span>
            </button>
          </header>
          {children}
        </div>
      )}
    </dialog>
  )
}
