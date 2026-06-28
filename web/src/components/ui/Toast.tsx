import { useEffect, useRef, useState } from 'react';
import { CheckCircle2, AlertTriangle, X } from 'lucide-react';
import { _subscribe, type ToastEntry } from '../../lib/toastApi';

export function ToastHost() {
  const [items, setItems] = useState<ToastEntry[]>([]);
  // Track active timers so unmounts don't leak.
  const timers = useRef<Map<number, number>>(new Map());

  useEffect(() => {
    const unsubscribe = _subscribe((t) => {
      setItems((cur) => [...cur, t]);
      const tid = window.setTimeout(() => {
        setItems((cur) => cur.filter((x) => x.id !== t.id));
        timers.current.delete(t.id);
      }, 4000);
      timers.current.set(t.id, tid);
    });
    return () => {
      unsubscribe();
      // timers.current is a long-lived Map; clear *every* pending timer.
      // eslint-disable-next-line react-hooks/exhaustive-deps
      for (const tid of timers.current.values()) clearTimeout(tid);
    };
  }, []);

  const dismiss = (id: number) => {
    const tid = timers.current.get(id);
    if (tid) clearTimeout(tid);
    timers.current.delete(id);
    setItems((cur) => cur.filter((x) => x.id !== id));
  };

  if (!items.length) return null;
  return (
    <div className="fixed bottom-5 right-5 z-[200] flex flex-col gap-2 max-w-xs">
      {items.map((t) => {
        const Icon = t.kind === 'error' ? AlertTriangle : CheckCircle2;
        const color =
          t.kind === 'error'
            ? 'text-[var(--error)]'
            : t.kind === 'info'
              ? 'text-[var(--info)]'
              : 'text-[var(--success)]';
        // Errors must be announced assertively (WCAG 4.1.3); successes/info
        // stay polite so they don't interrupt the screen-reader user.
        const isError = t.kind === 'error';
        return (
          <div
            key={t.id}
            role={isError ? 'alert' : 'status'}
            aria-live={isError ? 'assertive' : 'polite'}
            className="flex items-start gap-2 bg-white border border-line rounded-md shadow-md px-3 py-2 animate-slide-up"
          >
            <Icon size={16} className={`shrink-0 mt-0.5 ${color}`} />
            <span className="text-xs text-ink flex-1">{t.text}</span>
            <button
              onClick={() => dismiss(t.id)}
              className="text-ink-subtle hover:text-ink-muted shrink-0"
              aria-label="Dismiss notification"
            >
              <X size={13} />
            </button>
          </div>
        );
      })}
    </div>
  );
}
