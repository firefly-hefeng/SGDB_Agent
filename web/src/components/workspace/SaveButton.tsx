/**
 * Star button + popover for adding an item to a workspace.
 *
 * The button itself is just a star. Clicking opens a popover that
 * lets the user pick an existing workspace or quick-create a new
 * one. Once added, the star fills and the popover disappears.
 *
 * State is kept per (item_type, item_id) in module scope so the
 * "saved" indicator survives re-renders (the result table is
 * remounted on filter changes).
 */

import { useEffect, useRef, useState } from 'react';
import { Star, Plus, Loader2, Check } from 'lucide-react';
import { workspaceAddItems } from '../../services/api';
import { useWorkspaces } from '../../hooks/useWorkspaces';
import { Modal } from '../ui/Modal';
import { toast } from '../../lib/toastApi';

interface SaveTarget {
  item_type: 'sample' | 'series' | 'project';
  item_id: string;
  item_pk?: number;
  source_database?: string | null;
  title?: string | null;
}

interface Props {
  target: SaveTarget;
  size?: number;
}

// Track which (type, id) pairs have been saved, and to which workspace,
// so the star renders filled across re-renders.
const _savedTo = new Map<string, Set<number>>();
const _listeners = new Set<() => void>();

function key(t: SaveTarget) { return `${t.item_type}::${t.item_id}`; }

function markSaved(t: SaveTarget, wsId: number) {
  const k = key(t);
  const cur = _savedTo.get(k) || new Set<number>();
  cur.add(wsId);
  _savedTo.set(k, cur);
  _listeners.forEach((cb) => cb());
}

export function SaveButton({ target, size = 14 }: Props) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [, force] = useState(0);
  const ref = useRef<HTMLDivElement>(null);
  const { workspaces, loading, createOne, refresh } = useWorkspaces();

  const saved = _savedTo.has(key(target));

  // Subscribe so other star instances update when one is saved
  useEffect(() => {
    const cb = () => force((x) => x + 1);
    _listeners.add(cb);
    return () => { _listeners.delete(cb); };
  }, []);

  // Click-outside close
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open]);

  const onSaveTo = async (wsId: number) => {
    setBusy(true);
    setError(null);
    try {
      await workspaceAddItems(wsId, [{
        item_type: target.item_type,
        item_id: target.item_id,
        item_pk: target.item_pk ?? null,
        source_database: target.source_database ?? null,
        title: target.title ?? null,
        metadata: null,
        note: null,
      }]);
      markSaved(target, wsId);
      setOpen(false);
      // Phase 27 (W2): refresh the cached list so item_counts shown in this
      // and other star popovers / the workspace sidebar update immediately
      // instead of staying stale until a manual reload.
      refresh().catch(() => {});
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const [createOpen, setCreateOpen] = useState(false);
  const [createName, setCreateName] = useState('');

  const onQuickCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    const name = createName.trim();
    if (!name) return;
    setBusy(true);
    setError(null);
    try {
      const ws = await createOne(name);
      setCreateOpen(false);
      setCreateName('');
      await onSaveTo(ws.id);
      toast(`Saved to "${name}"`);
    } catch (err) {
      setError(String(err));
      setBusy(false);
    }
  };

  return (
    <div ref={ref} className="relative inline-block">
      <button
        type="button"
        onClick={(e) => { e.stopPropagation(); e.preventDefault(); setOpen(!open); }}
        title={saved ? 'In a workspace · click to add to another' : 'Save to workspace'}
        className={`p-1 rounded transition-colors ${
          saved ? 'text-yellow-500 hover:text-yellow-600' : 'text-ink-subtle hover:text-ink'
        }`}
        disabled={busy}
      >
        {busy ? (
          <Loader2 size={size} className="animate-spin" />
        ) : (
          <Star size={size} fill={saved ? 'currentColor' : 'none'} />
        )}
      </button>

      {open && (
        <div
          className="absolute right-0 top-full mt-1 z-30 w-56 rounded-md border border-line bg-white shadow-lg"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="px-3 py-2 border-b border-line">
            <p className="text-2xs uppercase tracking-wide text-ink-muted">
              Add {target.item_type} to…
            </p>
          </div>

          {loading ? (
            <div className="px-3 py-3 text-center"><Loader2 size={14} className="animate-spin inline" /></div>
          ) : workspaces && workspaces.length === 0 ? (
            <div className="px-3 py-3 text-xs text-ink-muted">
              No workspaces yet.
            </div>
          ) : (
            <ul className="max-h-48 overflow-y-auto py-1">
              {workspaces?.map((ws) => {
                const inThis = _savedTo.get(key(target))?.has(ws.id) ?? false;
                return (
                  <li key={ws.id}>
                    <button
                      onClick={() => !inThis && onSaveTo(ws.id)}
                      disabled={inThis || busy}
                      className={`flex items-center justify-between w-full px-3 py-1.5 text-xs text-left ${
                        inThis ? 'text-ink-subtle' : 'hover:bg-canvas-subtle text-ink'
                      }`}
                    >
                      <span className="truncate">{ws.name}</span>
                      {inThis ? (
                        <Check size={12} className="text-ink-subtle shrink-0 ml-2" />
                      ) : (
                        <span className="text-2xs text-ink-subtle tabular-nums shrink-0 ml-2">{ws.item_count}</span>
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}

          <button
            type="button"
            onClick={() => { setOpen(false); setCreateOpen(true); }}
            disabled={busy}
            className="flex items-center gap-1.5 w-full px-3 py-2 text-xs text-accent hover:bg-canvas-subtle border-t border-line"
          >
            <Plus size={12} /> New workspace…
          </button>

          {error && (
            <p className="px-3 py-2 text-2xs text-red-600 border-t border-line">{error}</p>
          )}
        </div>
      )}

      <Modal
        open={createOpen}
        onClose={() => !busy && setCreateOpen(false)}
        title="New workspace"
        footer={
          <>
            <button
              type="button"
              onClick={() => setCreateOpen(false)}
              disabled={busy}
              className="btn btn-secondary text-sm"
            >
              Cancel
            </button>
            <button
              type="submit"
              form="ws-save-create-form"
              disabled={busy || !createName.trim()}
              className="btn btn-accent text-sm"
            >
              {busy ? <Loader2 size={13} className="animate-spin" /> : null}
              Create &amp; save
            </button>
          </>
        }
      >
        <form id="ws-save-create-form" onSubmit={onQuickCreate}>
          <label className="block">
            <span className="block text-xs text-ink-muted mb-1">Name</span>
            <input
              autoFocus
              type="text"
              value={createName}
              onChange={(e) => setCreateName(e.target.value)}
              className="input"
              maxLength={120}
              required
            />
          </label>
        </form>
      </Modal>
    </div>
  );
}
