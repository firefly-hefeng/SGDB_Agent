import { useEffect, useMemo, useState } from 'react';
import {
  X, Trash2, ExternalLink, Copy, Check, FolderPlus, Loader2,
  CheckSquare, Square,
} from 'lucide-react';
import { useManifest } from '../../hooks/useManifest';
import { manifestClear, manifestRemove } from '../../lib/manifest';
import { fmtBytes, sourceLabel } from '../../lib/format';
import { toast } from '../../lib/toastApi';
import {
  workspaceList, workspaceCreate, workspaceAddItems, workspaceGet,
} from '../../services/api';
import { invalidateWorkspaceCache } from '../../hooks/useWorkspaces';
import type { WorkspaceMeta } from '../../types/api';

interface Props {
  open: boolean;
  onClose: () => void;
}

type Tab = 'list' | 'curl' | 'python';

export function ManifestPanel({ open, onClose }: Props) {
  const { manifest, count } = useManifest();
  const [tab, setTab] = useState<Tab>('list');
  const [copied, setCopied] = useState<Tab | null>(null);

  // Phase 29.E — bridge the local-storage manifest into the server-side
  // workspace store. Until R29, biologists had to manually re-add every
  // manifest entry to a workspace; this picker does it in one click.
  const [wsPickerOpen, setWsPickerOpen] = useState(false);
  const [wsList, setWsList] = useState<WorkspaceMeta[] | null>(null);
  const [wsBusy, setWsBusy] = useState(false);
  const [wsNewName, setWsNewName] = useState('');
  // Phase 30.D — after a successful save, leave a sticky link in the
  // footer pointing to the target workspace so the user can navigate
  // without re-finding it in the manifest. Clears when the manifest
  // changes again.
  const [wsLastSaved, setWsLastSaved] = useState<{
    id: number; name: string; added: number;
  } | null>(null);
  // Phase 31.A — per-workspace "already-in-here" overlap counts.
  // Map of workspace_id -> count of manifest entries that are
  // already in that workspace. Computed on picker open.
  const [wsOverlap, setWsOverlap] = useState<Record<number, number>>({});

  // Phase 33 (B1) — per-entry multi-select. The manifest used to be
  // all-or-nothing (clear everything / save everything); biologists asked to
  // curate a subset (e.g. drop the SRA mirrors, keep only the GEO originals,
  // then file just those into a workspace). `selected` holds entry keys.
  const [selected, setSelected] = useState<Set<string>>(new Set());

  // Group entries by source for the list tab.
  const entries = manifest.entries;
  const grouped = useMemo(() => {
    const m = new Map<string, typeof entries>();
    for (const e of entries) {
      // Group header text: canonical source-brand casing (CellxGene, GEO …).
      const k = sourceLabel(e.source_db);
      if (!m.has(k)) m.set(k, []);
      m.get(k)!.push(e);
    }
    return m;
  }, [entries]);

  // Estimate total size if entries declare it.
  const totalSize = useMemo(
    () => manifest.entries.reduce((s, e) => s + (e.size_estimate || 0), 0),
    [manifest.entries],
  );

  const curlScript = useMemo(() => buildCurlScript(manifest.entries), [manifest.entries]);
  const pythonSnippet = useMemo(() => buildPythonSnippet(manifest.entries), [manifest.entries]);

  // Bulk actions operate on the selected subset, or — when nothing is
  // explicitly selected — on the whole manifest (the familiar default).
  const targetEntries = useMemo(
    () => (selected.size ? entries.filter((e) => selected.has(e.key)) : entries),
    [entries, selected],
  );
  const allSelected = entries.length > 0 && selected.size === entries.length;

  const toggleEntry = (key: string) =>
    setSelected((prev) => {
      const n = new Set(prev);
      if (n.has(key)) n.delete(key); else n.add(key);
      return n;
    });
  const toggleSelectAll = () =>
    setSelected((prev) => (prev.size === entries.length ? new Set() : new Set(entries.map((e) => e.key))));

  // Drop selection entries that no longer exist (removed from the manifest).
  useEffect(() => {
    setSelected((prev) => {
      if (prev.size === 0) return prev;
      const live = new Set(entries.map((e) => e.key));
      const next = new Set([...prev].filter((k) => live.has(k)));
      return next.size === prev.size ? prev : next;
    });
  }, [entries]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  const copy = async (text: string, which: Tab) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(which);
      toast(`Copied ${which} to clipboard`, 'success');
      setTimeout(() => setCopied(null), 1800);
    } catch {
      toast('Copy failed — try selecting manually', 'error');
    }
  };

  const clearAll = () => {
    if (!count) return;
    manifestClear();
    setSelected(new Set());
    toast(`Cleared ${count} manifest ${count === 1 ? 'entry' : 'entries'}`, 'info');
  };

  const removeSelected = () => {
    if (selected.size === 0) return;
    const victims = entries.filter((e) => selected.has(e.key));
    for (const e of victims) manifestRemove(e.source_db, e.id);
    setSelected(new Set());
    toast(`Removed ${victims.length} selected ${victims.length === 1 ? 'entry' : 'entries'}`, 'info');
  };

  const openWorkspacePicker = async () => {
    if (targetEntries.length === 0) return;
    setWsPickerOpen(true);
    setWsOverlap({});
    // Always refetch so a workspace created elsewhere (a row star, the
    // Workspace page) shows up here without a reload.
    let workspaces: WorkspaceMeta[];
    try {
      const r = await workspaceList(false);
      workspaces = r.workspaces || [];
      setWsList(workspaces);
    } catch (e) {
      toast(`Workspace list failed: ${e}`, 'error');
      setWsList([]);
      return;
    }

    // Phase 31.A — compute per-workspace duplicate counts in parallel
    // so the picker can show "3 already here" badges. Skip empty
    // workspaces; the API call is wasted if item_count == 0.
    // Failures per workspace are silently ignored — the badge just
    // doesn't render for that row.
    const candidates = workspaces.filter((w) => w.item_count > 0);
    if (candidates.length === 0) return;
    const manifestKeys = new Set(
      targetEntries.map((e) => `${(e.source_db || '').toLowerCase()}::${e.id}`),
    );
    const overlapEntries = await Promise.all(
      candidates.map(async (w) => {
        try {
          const detail = await workspaceGet(w.id);
          const hits = detail.items.filter((it) =>
            manifestKeys.has(
              `${(it.source_database || '').toLowerCase()}::${it.item_id}`,
            ),
          ).length;
          return [w.id, hits] as const;
        } catch {
          return [w.id, -1] as const; // sentinel: lookup failed
        }
      }),
    );
    const overlap: Record<number, number> = {};
    for (const [id, n] of overlapEntries) {
      if (n >= 0) overlap[id] = n;
    }
    setWsOverlap(overlap);
  };

  const manifestEntryToWorkspaceItem = (e: typeof manifest.entries[number]) => ({
    item_type: 'project' as const,
    item_pk: null,
    item_id: e.id,
    source_database: e.source_db || null,
    title: e.title || null,
    metadata: e.download_url
      ? { download_url: e.download_url, file_type: e.file_type, source_url: e.source_url }
      : null,
    note: null,
  });

  const saveToWorkspace = async (id: number) => {
    setWsBusy(true);
    try {
      const items = targetEntries.map(manifestEntryToWorkspaceItem);
      const r = await workspaceAddItems(id, items);
      // Other parts of the app (SaveButton popovers) read a shared cache;
      // adding items here changes item_count, so invalidate it.
      invalidateWorkspaceCache();
      toast(
        `Added ${r.added} to workspace`
        + (r.skipped ? `, skipped ${r.skipped} duplicate(s)` : ''),
        'success',
      );
      // Record the target workspace for the post-save affordance.
      const ws = (wsList || []).find((w) => w.id === id);
      setWsLastSaved({
        id,
        name: ws?.name || `Workspace ${id}`,
        added: r.added,
      });
      setWsPickerOpen(false);
    } catch (e) {
      toast(`Save to workspace failed: ${e}`, 'error');
    } finally {
      setWsBusy(false);
    }
  };

  const createAndSave = async () => {
    const name = wsNewName.trim();
    if (!name) return;
    setWsBusy(true);
    try {
      const ws = await workspaceCreate(name, `Created from manifest of ${targetEntries.length} entries`);
      invalidateWorkspaceCache();
      await saveToWorkspace(ws.id);
      setWsNewName('');
      const r = await workspaceList(false);
      setWsList(r.workspaces || []);
    } catch (e) {
      toast(`Create-and-save failed: ${e}`, 'error');
    } finally {
      setWsBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[120] flex justify-end" role="dialog" aria-modal="true">
      <div
        className="absolute inset-0 bg-[rgba(15,23,42,0.35)] backdrop-blur-sm animate-fade-in"
        onClick={onClose}
      />
      <aside
        className="relative w-full max-w-md bg-white shadow-xl flex flex-col h-full animate-slide-up border-l border-line"
      >
        <header className="flex items-center justify-between px-5 py-4 border-b border-line">
          <div>
            <h2 className="text-base font-semibold text-ink">Download manifest</h2>
            <p className="text-xs text-ink-muted mt-0.5">
              {count} {count === 1 ? 'entry' : 'entries'}
              {totalSize > 0 ? ` · ~${fmtBytes(totalSize)}` : ''}
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="Close manifest panel"
            className="btn-ghost p-1"
          >
            <X size={16} />
          </button>
        </header>

        <div className="flex border-b border-line bg-canvas-subtle/60">
          {([
            ['list', `Entries (${count})`],
            ['curl', 'curl script'],
            ['python', 'Python'],
          ] as const).map(([id, label]) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={`px-4 py-2 text-xs font-medium ${
                tab === id
                  ? 'text-accent border-b-2 border-accent bg-white'
                  : 'text-ink-muted hover:text-ink'
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="flex-1 overflow-y-auto">
          {tab === 'list' &&
            (count === 0 ? (
              <EmptyState />
            ) : (
              <>
              <div className="px-5 pt-3 flex items-center justify-between text-2xs text-ink-muted">
                <button
                  onClick={toggleSelectAll}
                  className="inline-flex items-center gap-1.5 hover:text-ink"
                  aria-label={allSelected ? 'Deselect all entries' : 'Select all entries'}
                >
                  {allSelected
                    ? <CheckSquare size={13} className="text-accent" />
                    : <Square size={13} />}
                  {allSelected ? 'Deselect all' : 'Select all'}
                </button>
                {selected.size > 0 && (
                  <span className="text-accent font-medium">{selected.size} selected</span>
                )}
              </div>
              <ul className="px-5 py-3 space-y-4 text-xs">
                {Array.from(grouped.entries()).map(([source, entries]) => (
                  <li key={source}>
                    <header className="flex items-center justify-between mb-1.5">
                      <span className="text-2xs tracking-wide text-ink-subtle">
                        {source}
                      </span>
                      <span className="text-2xs text-ink-subtle">
                        {entries.length}
                      </span>
                    </header>
                    <ul className="space-y-1">
                      {entries.map((e) => (
                        <li
                          key={e.key}
                          className={`flex items-start gap-2 group px-2 py-1.5 rounded ${
                            selected.has(e.key) ? 'bg-accent-subtle' : 'bg-canvas-subtle/40'
                          }`}
                        >
                          <input
                            type="checkbox"
                            checked={selected.has(e.key)}
                            onChange={() => toggleEntry(e.key)}
                            aria-label={`Select ${e.id}`}
                            className="mt-0.5 shrink-0 h-3.5 w-3.5 rounded"
                          />
                          <div className="min-w-0 flex-1">
                            <a
                              href={e.source_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="font-mono text-accent hover:underline inline-flex items-center gap-0.5"
                            >
                              {e.id} <ExternalLink size={9} />
                            </a>
                            {e.title && (
                              <p className="text-xs text-ink-muted line-clamp-1">
                                {e.title}
                              </p>
                            )}
                          </div>
                          <button
                            onClick={() => manifestRemove(e.source_db, e.id)}
                            className="opacity-0 group-hover:opacity-100 text-ink-subtle hover:text-[var(--error)] transition-opacity"
                            aria-label={`Remove ${e.id} from manifest`}
                          >
                            <Trash2 size={11} />
                          </button>
                        </li>
                      ))}
                    </ul>
                  </li>
                ))}
              </ul>
              </>
            ))}

          {tab === 'curl' && (
            <CodeBlock content={curlScript} onCopy={() => copy(curlScript, 'curl')} copied={copied === 'curl'} />
          )}
          {tab === 'python' && (
            <CodeBlock
              content={pythonSnippet}
              onCopy={() => copy(pythonSnippet, 'python')}
              copied={copied === 'python'}
            />
          )}
        </div>

        {wsLastSaved && (
          <div
            role="status"
            className="px-5 py-2 border-t border-emerald-200 bg-emerald-50/70 text-xs text-emerald-900 flex items-center justify-between gap-2"
          >
            <span>
              ✓ Saved {wsLastSaved.added} {wsLastSaved.added === 1 ? 'entry' : 'entries'} to{' '}
              <span className="font-medium">{wsLastSaved.name}</span>
            </span>
            <a
              href={`/singligent/workspace/${wsLastSaved.id}`}
              className="text-accent hover:underline inline-flex items-center gap-0.5 shrink-0"
            >
              Open workspace →
            </a>
          </div>
        )}

        <footer className="px-5 py-3 border-t border-line flex items-center justify-between gap-2">
          {selected.size > 0 ? (
            <button
              onClick={removeSelected}
              className="text-xs text-ink-muted hover:text-[var(--error)] inline-flex items-center gap-1"
            >
              <Trash2 size={12} /> Remove selected ({selected.size})
            </button>
          ) : (
            <button
              onClick={clearAll}
              disabled={!count}
              className="text-xs text-ink-muted hover:text-[var(--error)] disabled:opacity-40 inline-flex items-center gap-1"
            >
              <Trash2 size={12} /> Clear all
            </button>
          )}
          <div className="flex items-center gap-2">
            <button
              onClick={openWorkspacePicker}
              disabled={targetEntries.length === 0}
              className="btn-ghost text-xs inline-flex items-center gap-1 disabled:opacity-40"
              title="Persist these entries server-side so they survive across browsers"
            >
              <FolderPlus size={12} />
              {selected.size > 0 ? `Save ${selected.size} to workspace` : 'Save to workspace'}
            </button>
            <a
              href="/singligent/downloads"
              className="btn-ghost text-xs inline-flex items-center gap-1"
            >
              Open Downloads page →
            </a>
          </div>
        </footer>

        {wsPickerOpen && (
          <WorkspacePicker
            wsList={wsList}
            busy={wsBusy}
            wsNewName={wsNewName}
            setWsNewName={setWsNewName}
            onPick={saveToWorkspace}
            onCreate={createAndSave}
            onClose={() => setWsPickerOpen(false)}
            count={targetEntries.length}
            overlap={wsOverlap}
          />
        )}
      </aside>
    </div>
  );
}

interface WorkspacePickerProps {
  wsList: WorkspaceMeta[] | null;
  busy: boolean;
  wsNewName: string;
  setWsNewName: (s: string) => void;
  onPick: (id: number) => void;
  onCreate: () => void;
  onClose: () => void;
  count: number;
  /** Phase 31.A — map of workspace_id → number of manifest entries
   *  already in that workspace. Missing workspace IDs mean either
   *  the workspace is empty or the overlap probe failed. */
  overlap: Record<number, number>;
}

function WorkspacePicker(p: WorkspacePickerProps) {
  return (
    <div
      className="absolute inset-x-0 bottom-12 mx-5 bg-white border border-line rounded-lg shadow-lg p-3 z-10"
      role="dialog"
      aria-label="Pick a workspace to save these manifest entries to"
    >
      <header className="flex items-center justify-between mb-2">
        <p className="text-xs font-medium text-ink">
          Save {p.count} {p.count === 1 ? 'entry' : 'entries'} to…
        </p>
        <button
          onClick={p.onClose}
          aria-label="Close workspace picker"
          className="btn-ghost p-0.5"
        >
          <X size={11} />
        </button>
      </header>
      <div className="max-h-40 overflow-y-auto -mx-1">
        {p.wsList === null && (
          <div className="text-2xs text-ink-subtle text-center py-3 inline-flex items-center justify-center w-full gap-1">
            <Loader2 size={11} className="animate-spin" /> Loading workspaces…
          </div>
        )}
        {p.wsList?.length === 0 && (
          <p className="text-2xs text-ink-subtle px-1 py-2">
            No workspaces yet — create one below.
          </p>
        )}
        {p.wsList?.map((ws) => {
          const already = p.overlap[ws.id];
          const willAdd = already != null ? p.count - already : p.count;
          return (
            <button
              key={ws.id}
              disabled={p.busy}
              onClick={() => p.onPick(ws.id)}
              className="w-full text-left px-2 py-1.5 hover:bg-canvas-subtle rounded text-xs flex items-center justify-between disabled:opacity-50"
              aria-label={
                already != null && already > 0
                  ? `Save to ${ws.name}; ${already} of ${p.count} already there, will add ${willAdd}`
                  : `Save to ${ws.name}`
              }
            >
              <span className="truncate">{ws.name}</span>
              <span className="flex items-center gap-1.5 ml-2 shrink-0">
                {already != null && already > 0 && (
                  <span
                    className="text-2xs px-1.5 py-0.5 rounded-full bg-amber-50 text-amber-800 border border-amber-200"
                    title={`${already} of these ${p.count} entries are already in this workspace; ${willAdd} would be added.`}
                  >
                    {already} dup
                  </span>
                )}
                <span className="text-2xs text-ink-subtle">
                  {ws.item_count} item{ws.item_count === 1 ? '' : 's'}
                </span>
              </span>
            </button>
          );
        })}
      </div>
      <form
        onSubmit={(e) => { e.preventDefault(); p.onCreate(); }}
        className="flex items-center gap-1 mt-2 pt-2 border-t border-line-subtle"
      >
        <input
          type="text"
          placeholder="…or create new workspace"
          value={p.wsNewName}
          onChange={(e) => p.setWsNewName(e.target.value)}
          className="flex-1 text-xs border border-line rounded px-2 py-1"
          disabled={p.busy}
        />
        <button
          type="submit"
          disabled={p.busy || !p.wsNewName.trim()}
          className="btn-accent text-xs px-2 py-1 inline-flex items-center gap-1 disabled:opacity-50"
        >
          {p.busy ? <Loader2 size={11} className="animate-spin" /> : <FolderPlus size={11} />}
          Create
        </button>
      </form>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="px-6 py-10 text-center text-xs text-ink-muted">
      <p className="mb-1">Your manifest is empty.</p>
      <p className="text-2xs text-ink-subtle">
        Click the <strong>+</strong> next to any dataset in Explore, Advanced, or Discover to add it.
      </p>
    </div>
  );
}

function CodeBlock({
  content,
  onCopy,
  copied,
}: {
  content: string;
  onCopy: () => void;
  copied: boolean;
}) {
  return (
    <div className="p-4">
      <div className="flex items-center justify-end mb-2">
        <button
          onClick={onCopy}
          className="btn-ghost text-2xs inline-flex items-center gap-1 px-2 py-1"
        >
          {copied ? <Check size={11} /> : <Copy size={11} />}
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre className="code-block whitespace-pre overflow-x-auto text-2xs">{content}</pre>
    </div>
  );
}

function buildCurlScript(entries: { id: string; source_db: string; source_url?: string; download_url?: string | null }[]) {
  if (!entries.length) {
    return '# Empty manifest. Add datasets to populate this script.';
  }
  const lines = [
    '#!/usr/bin/env bash',
    '# Manifest generated by Singligent portal',
    'set -e',
    '',
  ];
  for (const e of entries) {
    const url = e.download_url || e.source_url;
    if (!url) continue;
    const filename = `${e.source_db.toLowerCase()}_${e.id}`;
    lines.push(`# ${e.source_db} ${e.id}`);
    lines.push(`curl -L -o "${filename}" "${url}"`);
  }
  return lines.join('\n');
}

function buildPythonSnippet(entries: { id: string; source_db: string; source_url?: string; download_url?: string | null }[]) {
  if (!entries.length) {
    return '# Empty manifest. Add datasets to populate this snippet.';
  }
  const items = entries
    .map(
      (e) =>
        `    {"source": "${e.source_db}", "id": "${e.id}", "url": "${e.download_url || e.source_url || ''}"},`,
    )
    .join('\n');
  return [
    '"""Download manifest exported from the Singligent portal."""',
    'import os, urllib.request',
    '',
    'MANIFEST = [',
    items,
    ']',
    '',
    'for entry in MANIFEST:',
    '    name = f"{entry[\'source\'].lower()}_{entry[\'id\']}"',
    '    if os.path.exists(name):',
    '        continue',
    '    print(f"Fetching {entry[\'source\']} {entry[\'id\']}…")',
    '    urllib.request.urlretrieve(entry["url"], name)',
  ].join('\n');
}
