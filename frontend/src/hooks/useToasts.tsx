import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import type { Toast } from '../types/ui';

interface ToastApi {
  toasts: Toast[];
  notify: (kind: Toast['kind'], text: string) => void;
  error: (err: unknown, prefix?: string) => void;
  dismiss: (id: number) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

function errorText(err: unknown): string {
  if (err instanceof Error && err.message) return err.message;
  return 'Something went wrong. Please try again.';
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => setToasts((t) => t.filter((x) => x.id !== id)), []);

  const notify = useCallback(
    (kind: Toast['kind'], text: string) => {
      const id = nextId.current++;
      setToasts((t) => (t.some((x) => x.text === text) ? t : [...t.slice(-3), { id, kind, text }]));
      window.setTimeout(() => dismiss(id), kind === 'error' ? 12000 : 5000);
    },
    [dismiss],
  );

  const error = useCallback(
    (err: unknown, prefix?: string) => notify('error', prefix ? `${prefix} ${errorText(err)}` : errorText(err)),
    [notify],
  );

  const value = useMemo(() => ({ toasts, notify, error, dismiss }), [toasts, notify, error, dismiss]);
  return <ToastContext.Provider value={value}>{children}</ToastContext.Provider>;
}

export function useToasts(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToasts must be used inside ToastProvider');
  return ctx;
}
