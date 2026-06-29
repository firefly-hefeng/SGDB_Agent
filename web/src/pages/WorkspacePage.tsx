import { useEffect, useState } from 'react';
import { Link, useParams, useNavigate } from 'react-router-dom';
import { Loader2, Plus, Folder, Trash2, RotateCcw, Download, ExternalLink, ArrowRight } from 'lucide-react';
import {
  workspaceList, workspaceCreate, workspaceGet, workspaceDelete,
  workspaceRecover, workspaceRemoveItem, workspaceExport, downloadBlob,
} from '../services/api';
import type { WorkspaceMeta, WorkspaceWithItems } from '../types/api';
import { Modal } from '../components/ui/Modal';
import { HowToUse } from '../components/ui/HowToUse';
import { manifestAdd } from '../lib/manifest';
import { toast } from '../lib/toastApi';
import { invalidateWorkspaceCache } from '../hooks/useWorkspaces';
import { useT } from '../lib/i18n';

export default function WorkspacePage() {
  const { t } = useT();
  const { id } = useParams<{ id?: string }>();
  const navigate = useNavigate();
  const numericId = id ? parseInt(id, 10) : null;

  const [workspaces, setWorkspaces] = useState<WorkspaceMeta[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [includeDeleted, setIncludeDeleted] = useState(false);
  const [detail, setDetail] = useState<WorkspaceWithItems | null>(null);

  // Modal state
  const [createOpen, setCreateOpen] = useState(false);
  const [createName, setCreateName] = useState('');
  const [createDescription, setCreateDescription] = useState('');
  const [createBusy, setCreateBusy] = useState(false);

  const [deleteWid, setDeleteWid] = useState<number | null>(null);

  useEffect(() => {
    setLoading(true);
    workspaceList(includeDeleted)
      .then((r) => setWorkspaces(r.workspaces))
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [includeDeleted]);

  useEffect(() => {
    if (numericId == null) {
      setDetail(null);
      return;
    }
    workspaceGet(numericId).then(setDetail).catch((e) => setError(String(e)));
  }, [numericId]);

  const refresh = async () => {
    // Keep the shared module cache (read by every SaveButton popover across
    // the app) in lock-step with mutations made here, so a workspace created
    // or deleted on this page is immediately reflected elsewhere. Without this
    // the star popovers showed a stale list until a full page reload.
    invalidateWorkspaceCache();
    const r = await workspaceList(includeDeleted);
    setWorkspaces(r.workspaces);
    if (numericId != null) {
      try { setDetail(await workspaceGet(numericId)); } catch {}
    }
  };

  const submitCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!createName.trim()) return;
    setCreateBusy(true);
    try {
      await workspaceCreate(createName.trim(), createDescription.trim());
      setCreateOpen(false);
      setCreateName('');
      setCreateDescription('');
      await refresh();
      toast(`Created workspace "${createName.trim()}"`);
    } catch (e) {
      setError(String(e));
      toast('Failed to create workspace', 'error');
    } finally {
      setCreateBusy(false);
    }
  };

  const confirmDelete = async () => {
    if (deleteWid == null) return;
    try {
      await workspaceDelete(deleteWid);
      await refresh();
      toast('Workspace moved to trash. View it via the deleted filter.', 'info');
    } catch (e) {
      toast(`Delete failed: ${e}`, 'error');
    } finally {
      setDeleteWid(null);
    }
  };

  const onRecover = async (wid: number) => {
    await workspaceRecover(wid);
    await refresh();
    toast('Workspace recovered');
  };

  const onExport = async (wid: number, fmt: 'csv' | 'json') => {
    const blob = await workspaceExport(wid, fmt);
    downloadBlob(blob, `workspace_${wid}.${fmt}`);
  };

  const onRemoveItem = async (wid: number, itemPk: number) => {
    await workspaceRemoveItem(wid, itemPk);
    await refresh();
    toast('Item removed from workspace', 'info');
  };

  // Phase 33: bridge a workspace into the download manifest, closing the
  // workspace↔downloads split flagged in the Round-1 audit (§3.3). Carries any
  // download_url stored in item.metadata so external datasets resolve too.
  const onSendToDownloads = () => {
    if (!detail || detail.items.length === 0) return;
    const rows = detail.items.map((it) => {
      const m = (it.metadata || {}) as Record<string, unknown>;
      return {
        id: it.item_id,
        source_db: it.source_database || '',
        source_url: (m.source_url as string) || undefined,
        download_url: (m.download_url as string) || null,
        file_type: (m.file_type as string) || null,
        size_estimate: null,
        title: it.title || null,
      };
    });
    const added = manifestAdd(rows);
    toast(`Added ${added} item${added === 1 ? '' : 's'} to the download manifest`);
    navigate('/downloads');
  };

  return (
    <div className="flex flex-1 min-h-0">
      <aside className="w-[280px] shrink-0 border-r border-line bg-canvas p-4 overflow-y-auto">
        <div className="flex items-center justify-between mb-3">
          <h1 className="text-2xl font-semibold text-ink">My workspaces</h1>
          <button
            onClick={() => {
              setCreateName('');
              setCreateDescription('');
              setCreateOpen(true);
            }}
            aria-label="Create new workspace"
            className="btn-ghost p-1 hover:bg-canvas-muted"
          >
            <Plus size={14} />
          </button>
        </div>
        <label className="flex items-center gap-2 mb-3 text-xs text-ink-muted">
          <input
            type="checkbox" checked={includeDeleted}
            onChange={(e) => setIncludeDeleted(e.target.checked)}
            className="rounded"
          />
          Show deleted
        </label>

        {loading ? (
          <div className="text-center py-6"><Loader2 size={16} className="animate-spin inline" /></div>
        ) : workspaces.length === 0 ? (
          <div className="text-center py-6 text-xs text-ink-muted">
            {includeDeleted ? 'No deleted workspaces.' : 'No workspaces yet.'}
            <br />
            <button onClick={() => setCreateOpen(true)} className="text-accent underline mt-2 text-xs">
              Create one
            </button>
          </div>
        ) : (
          <ul className="space-y-1">
            {workspaces.map((w) => (
              <li key={w.id}>
                <Link
                  to={`/workspace/${w.id}`}
                  className={`block px-2 py-1.5 rounded text-xs hover:bg-canvas-muted ${
                    numericId === w.id ? 'bg-canvas-muted font-medium' : ''
                  } ${w.deleted_at ? 'opacity-50' : ''}`}
                >
                  <div className="flex items-center gap-2">
                    <Folder size={12} className="text-ink-subtle" />
                    <span className="flex-1 truncate">{w.name}</span>
                    <span className="text-2xs text-ink-subtle">{w.item_count}</span>
                  </div>
                  {w.deleted_at && (
                    <span className="text-2xs text-ink-subtle block ml-4">
                      deleted {w.deleted_at.slice(0, 10)}
                    </span>
                  )}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </aside>

      <div className="flex-1 flex flex-col min-w-0 overflow-hidden bg-white">
        {error && (
          <div className="flex items-start gap-2 mx-5 mt-3 text-sm text-[var(--danger)] bg-red-50 border border-red-100 rounded-md px-3 py-2">
            <span>{error}</span>
          </div>
        )}

        {numericId == null ? (
          <div className="flex-1 flex flex-col items-center justify-center text-ink-muted px-6">
            <div className="text-center max-w-[440px]">
              <Folder size={32} className="mx-auto mb-2 text-ink-subtle" />
              <p className="text-sm">Select a workspace from the sidebar.</p>
              <p className="text-xs text-ink-subtle mt-1">
                Or create a new one with the <Plus size={10} className="inline" /> button.
              </p>
              <HowToUse
                className="mt-5 text-left"
                defaultOpen
                body={t('intro.workspace.body',
                  'Save samples, projects and series into named workspaces to revisit, annotate and export later. Use the bookmark button anywhere in the catalog to add items; deleted workspaces are recoverable.')}
                examples={[
                  { label: 'Browse the catalog', to: '/explore', hint: 'then click the bookmark on any row' },
                ]}
              />
            </div>
          </div>
        ) : detail == null ? (
          <div className="flex-1 flex items-center justify-center">
            <Loader2 size={20} className="animate-spin text-accent" />
          </div>
        ) : (
          <>
            <header className="page-header-band bg-canvas px-5 py-3 flex items-start justify-between gap-3">
              <div className="min-w-0">
                <h2 className="text-lg font-semibold text-ink truncate">{detail.workspace.name}</h2>
                {detail.workspace.description && (
                  <p className="text-xs text-ink-muted mt-0.5">{detail.workspace.description}</p>
                )}
                <p className="text-2xs text-ink-subtle mt-1">
                  {detail.items.length} items · created {detail.workspace.created_at.slice(0, 10)}
                  {detail.workspace.deleted_at && ` · deleted ${detail.workspace.deleted_at.slice(0, 10)}`}
                </p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {detail.items.length > 0 && (
                  <button
                    onClick={onSendToDownloads}
                    aria-label="Send workspace items to downloads"
                    className="btn-ghost text-xs inline-flex items-center gap-1 px-2 py-1 text-accent"
                    title="Add every item in this workspace to the download manifest"
                  >
                    <ArrowRight size={12} /> Downloads
                  </button>
                )}
                <button
                  onClick={() => onExport(numericId, 'csv')}
                  aria-label="Export workspace as CSV"
                  className="btn-ghost text-xs inline-flex items-center gap-1 px-2 py-1"
                >
                  <Download size={12} /> CSV
                </button>
                <button
                  onClick={() => onExport(numericId, 'json')}
                  aria-label="Export workspace as JSON"
                  className="btn-ghost text-xs inline-flex items-center gap-1 px-2 py-1"
                >
                  <Download size={12} /> JSON
                </button>
                {detail.workspace.deleted_at ? (
                  <button onClick={() => onRecover(numericId)}
                    className="btn-ghost text-xs inline-flex items-center gap-1 px-2 py-1 text-accent">
                    <RotateCcw size={12} /> Recover
                  </button>
                ) : (
                  <button onClick={() => setDeleteWid(numericId)}
                    className="btn-danger-ghost text-xs inline-flex items-center gap-1">
                    <Trash2 size={12} /> Delete
                  </button>
                )}
              </div>
            </header>

            <div className="flex-1 overflow-y-auto px-5 py-2">
              {detail.items.length === 0 ? (
                <div className="text-center py-12 text-ink-muted" role="status">
                  <p className="text-sm font-medium mb-1">This workspace is empty</p>
                  <p className="text-xs text-ink-subtle mb-4 max-w-[420px] mx-auto">
                    Click the ★ button on any sample, project, or series row to save it here.
                    You can also import items from your local manifest from the right-side panel.
                  </p>
                  <div className="flex items-center justify-center gap-2">
                    <Link
                      to="/explore"
                      className="btn btn-accent text-xs inline-flex items-center gap-1 px-3 py-1.5"
                    >
                      Browse the catalogue
                    </Link>
                    <Link
                      to="/search"
                      className="btn-ghost text-xs inline-flex items-center gap-1 px-2.5 py-1.5"
                    >
                      Advanced search
                    </Link>
                  </div>
                </div>
              ) : (
                <table className="w-full">
                  <thead className="sticky top-0 bg-white border-b border-line">
                    <tr className="text-2xs text-ink-muted uppercase tracking-wide">
                      <th className="text-left py-2 font-medium">Type</th>
                      <th className="text-left py-2 font-medium">ID</th>
                      <th className="text-left py-2 font-medium">Source</th>
                      <th className="text-left py-2 font-medium">Title</th>
                      <th className="text-left py-2 font-medium">Note</th>
                      <th className="text-left py-2 font-medium">Added</th>
                      <th className="w-8"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.items.map((it) => (
                      <tr key={it.id} className="border-b border-line hover:bg-canvas-subtle/30 text-xs">
                        <td className="py-2">
                          <span className="px-1.5 py-0.5 rounded bg-canvas-muted text-2xs uppercase">{it.item_type}</span>
                        </td>
                        <td className="py-2">
                          <Link to={`/explore/${encodeURIComponent(it.item_id)}`}
                            className="text-accent hover:underline font-mono inline-flex items-center gap-0.5">
                            {it.item_id}<ExternalLink size={10} />
                          </Link>
                        </td>
                        <td className="py-2 text-ink-muted">{it.source_database || '—'}</td>
                        <td className="py-2 text-ink max-w-[300px] truncate" title={it.title || ''}>
                          {it.title || '—'}
                        </td>
                        <td className="py-2 text-ink-muted truncate max-w-[200px]" title={it.note || ''}>
                          {it.note || '—'}
                        </td>
                        <td className="py-2 text-ink-subtle tabular-nums">{it.added_at.slice(0, 10)}</td>
                        <td className="py-2">
                          <button onClick={() => onRemoveItem(numericId, it.id)}
                            aria-label={`Remove ${it.item_id} from workspace`}
                            className="text-ink-subtle hover:text-[var(--danger)] transition-colors">
                            <Trash2 size={12} />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </>
        )}
      </div>

      <Modal
        open={createOpen}
        onClose={() => !createBusy && setCreateOpen(false)}
        title="New workspace"
        description="Group samples, projects, and series under a single name."
        footer={
          <>
            <button
              type="button"
              onClick={() => setCreateOpen(false)}
              disabled={createBusy}
              className="btn btn-secondary text-sm"
            >
              Cancel
            </button>
            <button
              type="submit"
              form="ws-create-form"
              disabled={createBusy || !createName.trim()}
              className="btn btn-accent text-sm"
            >
              {createBusy ? <Loader2 size={13} className="animate-spin" /> : null}
              Create
            </button>
          </>
        }
      >
        <form id="ws-create-form" onSubmit={submitCreate} className="space-y-3">
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
          <label className="block">
            <span className="block text-xs text-ink-muted mb-1">
              Description (optional)
            </span>
            <textarea
              value={createDescription}
              onChange={(e) => setCreateDescription(e.target.value)}
              className="input min-h-[60px]"
              maxLength={500}
            />
          </label>
        </form>
      </Modal>

      <Modal
        open={deleteWid != null}
        onClose={() => setDeleteWid(null)}
        title="Move workspace to trash?"
        description="Items are preserved. Recover from the deleted filter at any time."
        footer={
          <>
            <button
              type="button"
              onClick={() => setDeleteWid(null)}
              className="btn btn-secondary text-sm"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={confirmDelete}
              className="btn btn-danger text-sm"
            >
              <Trash2 size={13} /> Delete
            </button>
          </>
        }
      >
        <p className="text-sm text-ink-muted">
          This workspace will be hidden from the active list. Toggle "Show deleted" in the sidebar
          to view or recover it.
        </p>
      </Modal>
    </div>
  );
}
