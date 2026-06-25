/* Cross-page manifest store backed by localStorage.
 * Identity is per-browser; no server-side persistence. */

export interface ManifestEntry {
  /** Stable composite key (source_db + id), used for dedup. */
  key: string;
  id: string;
  source_db: string;
  source_url?: string;
  download_url?: string | null;
  file_type?: string | null;
  size_estimate?: number | null;
  title?: string | null;
  added_at: string; // ISO timestamp
}

export interface Manifest {
  entries: ManifestEntry[];
  updated_at: string;
}

const KEY = 'sceqtl.manifest.v1';

const _listeners = new Set<() => void>();

// Cached snapshot for useSyncExternalStore. Must be the same object reference
// between calls until the underlying store actually changes, or React enters
// an infinite re-render loop ("getSnapshot should be cached").
let _snapshot: Manifest | null = null;

function emit() {
  // Invalidate the cached snapshot so the next getSnapshot reads fresh.
  _snapshot = null;
  for (const cb of _listeners) cb();
}

function readFromStorage(): Manifest {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return { entries: [], updated_at: '1970-01-01T00:00:00.000Z' };
    const parsed = JSON.parse(raw) as Manifest;
    if (!parsed || !Array.isArray(parsed.entries)) {
      return { entries: [], updated_at: '1970-01-01T00:00:00.000Z' };
    }
    return parsed;
  } catch {
    return { entries: [], updated_at: '1970-01-01T00:00:00.000Z' };
  }
}

function read(): Manifest {
  if (_snapshot === null) _snapshot = readFromStorage();
  return _snapshot;
}

function write(m: Manifest) {
  try {
    localStorage.setItem(KEY, JSON.stringify(m));
  } catch {
    // localStorage may be disabled (private mode); keep in-memory state.
  }
  _snapshot = m;
  for (const cb of _listeners) cb();
}

export function entryKey(source_db: string, id: string): string {
  return `${(source_db || '').toLowerCase()}::${id}`;
}

export function manifestGet(): Manifest {
  return read();
}

export function manifestHas(source_db: string, id: string): boolean {
  return read().entries.some((e) => e.key === entryKey(source_db, id));
}

export function manifestAdd(
  rows: Omit<ManifestEntry, 'key' | 'added_at'>[],
): number {
  const cur = read();
  const existing = new Set(cur.entries.map((e) => e.key));
  const newEntries: ManifestEntry[] = [];
  for (const r of rows) {
    if (!r.id || !r.source_db) continue;
    const k = entryKey(r.source_db, r.id);
    if (existing.has(k)) continue;
    newEntries.push({
      ...r,
      key: k,
      added_at: new Date().toISOString(),
    });
    existing.add(k);
  }
  if (!newEntries.length) return 0;
  write({
    entries: [...cur.entries, ...newEntries],
    updated_at: new Date().toISOString(),
  });
  return newEntries.length;
}

export function manifestRemove(source_db: string, id: string): void {
  const cur = read();
  const k = entryKey(source_db, id);
  const filtered = cur.entries.filter((e) => e.key !== k);
  if (filtered.length === cur.entries.length) return;
  write({ entries: filtered, updated_at: new Date().toISOString() });
}

export function manifestClear(): void {
  write({ entries: [], updated_at: new Date().toISOString() });
}

export function manifestSubscribe(cb: () => void): () => void {
  _listeners.add(cb);
  return () => _listeners.delete(cb);
}

// Cross-tab sync.
if (typeof window !== 'undefined') {
  window.addEventListener('storage', (e) => {
    if (e.key === KEY) emit();
  });
}
