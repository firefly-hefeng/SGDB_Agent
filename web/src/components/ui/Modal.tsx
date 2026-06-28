import { useEffect, useRef } from 'react';
import { X } from 'lucide-react';

interface Props {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
  width?: string; // CSS value; default `max-w-md`
}

/**
 * Accessible centered modal: portal-less since the app has no
 * `position: fixed` parent. Closes on Escape, on backdrop click, and on
 * the close button.
 */
export function Modal({ open, onClose, title, description, children, footer, width = 'max-w-md' }: Props) {
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    // Move focus to the close button so Esc / Tab works.
    closeRef.current?.focus();
    // Prevent background scroll.
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = prev;
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-[rgba(15,23,42,0.4)] backdrop-blur-sm animate-fade-in"
      role="dialog"
      aria-modal="true"
      aria-labelledby="modal-title"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className={`w-full ${width} bg-white rounded-lg shadow-lg border border-line animate-scale-in`}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-start justify-between px-5 py-4 border-b border-line-subtle">
          <div className="min-w-0">
            <h2 id="modal-title" className="text-base font-semibold text-ink">
              {title}
            </h2>
            {description && (
              <p className="text-xs text-ink-muted mt-0.5">{description}</p>
            )}
          </div>
          <button
            ref={closeRef}
            onClick={onClose}
            className="btn-ghost p-1 -mr-1"
            aria-label="Close dialog"
          >
            <X size={16} />
          </button>
        </header>
        <div className="px-5 py-4 text-sm text-ink">{children}</div>
        {footer && (
          <footer className="px-5 py-3 border-t border-line-subtle bg-canvas-subtle flex justify-end gap-2">
            {footer}
          </footer>
        )}
      </div>
    </div>
  );
}
