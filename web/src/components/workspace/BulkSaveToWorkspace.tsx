/**
 * Bulk "Save N to workspace" button + popover.
 *
 * The per-row SaveButton (star) files one item at a time; this files a whole
 * selection at once. Shares the module-scoped workspace cache (useWorkspaces)
 * so the list stays consistent with every other workspace surface in the app.
 */
import { useEffect, useRef, useState } from 'react';
import { FolderPlus, Loader2, Plus, Check } from 'lucide-react';
import { workspaceAddItems } from '../../services/api';
import { useWorkspaces } from '../../hooks/useWorkspaces';
import { toast } from '../../lib/toastApi';

export interface BulkItem {
  item_type: 'sample' | 'series' | 'project';
  item_id: string;
  item_pk?: number | null;
  source_database?: string | null;
  title?: string | null;
}

export function BulkSaveToWorkspace({ items }: { items: BulkItem[] }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState('');
  const ref = useRef<HTMLDivElement>(null);
  const { workspaces, loading, createOne, refresh } = useWorkspaces();

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open]);

  const toPayload = () =>
    items.map((it) => ({
      item_type: it.item_type,
      item_id: it.item_id,
      item_pk: it.item_pk ?? null,
      source_database: it.source_database ?? null,
      title: it.title ?? null,
      metadata: null,
      note: null,
    }));

  const saveTo = async (wsId: number, wsName: string) => {
    setBusy(true);
    try {
      const r = await workspaceAddItems(wsId, toPayload());
      await refresh();
      toast(
        `Added ${r.added} to "${wsName}"` + (r.skipped ? `, skipped ${r.skipped} duplicate(s)` : ''),
        'success',
      );
      setOpen(false);
    } catch (e) {
      toast(`Save to workspace failed: ${e}`, 'error');
    } finally {
      setBusy(false);
    }
  };

  const createAndSave = async (e: React.FormEvent) => {
    e.preventDefault();
    const name = newName.trim();
    if (!name) return;
    setBusy(true);
    try {
      const ws = await createOne(name);
      setNewName('');
      setCreating(false);
      await saveTo(ws.id, name);
    } catch (err) {
      toast(`Create-and-save failed: ${err}`, 'error');
      setBusy(false);
    }
  };

  return (
    <div ref={ref} className="relative inline-block">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={items.length === 0 || busy}
        className="btn-ghost text-xs inline-flex items-center gap-1 px-3 py-1 disabled:opacity-40"
      >
        {busy ? <Loader2 size={12} className="animate-spin" /> : <FolderPlus size={12} />}
        Save {items.length} to workspace
      </button>

      {open && (
        <div className="absolute bottom-full left-0 mb-1 z-30 w-60 rounded-md border border-line bg-white shadow-lg">
          <div className="px-3 py-2 border-b border-line">
            <p className="text-2xs uppercase tracking-wide text-ink-muted">
              Save {items.length} item{items.length === 1 ? '' : 's'} to…
            </p>
          </div>
          {loading ? (
            <div className="px-3 py-3 text-center"><Loader2 size={14} className="animate-spin inline" /></div>
          ) : workspaces && workspaces.length > 0 ? (
            <ul className="max-h-44 overflow-y-auto py-1">
              {workspaces.map((ws) => (
                <li key={ws.id}>
                  <button
                    onClick={() => saveTo(ws.id, ws.name)}
                    disabled={busy}
                    className="flex items-center justify-between w-full px-3 py-1.5 text-xs text-left hover:bg-canvas-subtle disabled:opacity-50"
                  >
                    <span className="truncate">{ws.name}</span>
                    <span className="text-2xs text-ink-subtle tabular-nums shrink-0 ml-2">{ws.item_count}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="px-3 py-2 text-2xs text-ink-subtle">No workspaces yet — create one below.</p>
          )}

          {creating ? (
            <form onSubmit={createAndSave} className="flex items-center gap-1 p-2 border-t border-line">
              <input
                autoFocus
                type="text"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="New workspace name"
                className="flex-1 text-xs border border-line rounded px-2 py-1"
                disabled={busy}
              />
              <button
                type="submit"
                disabled={busy || !newName.trim()}
                className="btn-accent text-xs px-2 py-1 inline-flex items-center gap-1 disabled:opacity-50"
              >
                {busy ? <Loader2 size={11} className="animate-spin" /> : <Check size={11} />}
              </button>
            </form>
          ) : (
            <button
              type="button"
              onClick={() => setCreating(true)}
              disabled={busy}
              className="flex items-center gap-1.5 w-full px-3 py-2 text-xs text-accent hover:bg-canvas-subtle border-t border-line"
            >
              <Plus size={12} /> New workspace…
            </button>
          )}
        </div>
      )}
    </div>
  );
}
