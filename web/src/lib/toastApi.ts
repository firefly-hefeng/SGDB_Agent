/** Toast publisher. Importing components subscribe via `_subscribe`;
 * the rest of the app calls `toast(text, kind?)`. Split from
 * `components/ui/Toast.tsx` so Vite Fast Refresh keeps working on
 * the component file (HMR refuses to refresh files that export a
 * mix of components and non-components). */

export type ToastKind = 'success' | 'error' | 'info';

export interface ToastEntry {
  id: number;
  kind: ToastKind;
  text: string;
}

const _listeners = new Set<(t: ToastEntry) => void>();
let _id = 0;

export function toast(text: string, kind: ToastKind = 'success'): void {
  _id += 1;
  const entry: ToastEntry = { id: _id, kind, text };
  for (const cb of _listeners) cb(entry);
}

export function _subscribe(cb: (t: ToastEntry) => void): () => void {
  _listeners.add(cb);
  return () => {
    _listeners.delete(cb);
  };
}
