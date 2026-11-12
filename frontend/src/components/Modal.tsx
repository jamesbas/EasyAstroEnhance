import { useEffect, useRef } from 'react';
import type { ReactNode } from 'react';
import { useToasts } from '../hooks/useToasts';

interface ModalProps {
  title: string;
  onClose: () => void;
  children: ReactNode;
  testId?: string;
  wide?: boolean;
  dismissible?: boolean;
  labelledBy?: string;
}

// Native <dialog>: focus is trapped, Escape closes, and the page behind is inert.
export function Modal({ title, onClose, children, testId, wide, dismissible = true }: ModalProps) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const d = ref.current;
    if (d && !d.open) d.showModal();
    return () => {
      if (d?.open) d.close();
    };
  }, []);

  return (
    <dialog
      ref={ref}
      className={wide ? 'modal wide' : 'modal'}
      data-testid={testId}
      aria-labelledby="modal-title"
      onCancel={(e) => {
        e.preventDefault();
        if (dismissible) onClose();
      }}
      onClick={(e) => {
        if (dismissible && e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal-inner">
        <header className="modal-head">
          <h2 id="modal-title">{title}</h2>
          {dismissible && (
            <button type="button" className="icon-btn" aria-label="Close dialog" onClick={onClose}>×</button>
          )}
        </header>
        <div className="modal-body">{children}</div>
      </div>
    </dialog>
  );
}

export function Toaster() {
  const { toasts, dismiss } = useToasts();
  return (
    <div className="toaster" role="region" aria-label="Notifications">
      {toasts.map((t) => (
        <div key={t.id} className={`toast ${t.kind}`} role={t.kind === 'error' ? 'alert' : 'status'} data-testid={`toast-${t.kind}`}>
          <span>{t.text}</span>
          <button type="button" className="icon-btn" aria-label="Dismiss message" onClick={() => dismiss(t.id)}>×</button>
        </div>
      ))}
    </div>
  );
}
