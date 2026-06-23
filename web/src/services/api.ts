/* API client service — with stale-while-revalidate cache for stats */

import type {
  StatsResponse,
  ExploreResponse, DatasetDetailResponse, DashboardStats,
  AdvancedSearchRequest, AdvancedSearchResponse,
  ProjectSearchRequest, ProjectSearchResponse,
  SeriesSearchRequest, SeriesSearchResponse,
  ProjectsStatsBySource,
  WorkspaceMeta, WorkspaceWithItems, WorkspaceItem, AddItemsResult,
  DownloadOption, DownloadEstimate,
  CellTypeSearchResponse, CellTypeProjectsResponse, CellTypeSort,
} from '../types/api';
import type { ExploreFilters } from '../types/filters';

const BASE_URL: string =
  (import.meta.env.VITE_API_BASE as string | undefined) ?? '/singligent/scdbAPI';

// ── Client-side cache (stale-while-revalidate) ──

interface CacheEntry<T> {
  data: T;
  timestamp: number;
}

const _cache = new Map<string, CacheEntry<unknown>>();
const CACHE_TTL_MS = 5 * 60 * 1000; // 5 minutes

function getCached<T>(key: string): T | null {
  const entry = _cache.get(key);
  if (!entry) return null;
  if (Date.now() - entry.timestamp > CACHE_TTL_MS) {
    _cache.delete(key);
    return null;
  }
  return entry.data as T;
}

function setCache<T>(key: string, data: T): void {
  _cache.set(key, { data, timestamp: Date.now() });
}

async function fetchWithCache<T>(key: string, fetcher: () => Promise<T>): Promise<T> {
  const cached = getCached<T>(key);
  if (cached) {
    // Revalidate in background (fire-and-forget)
    fetcher().then((fresh) => setCache(key, fresh)).catch(() => {});
    return cached;
  }
  const data = await fetcher();
  setCache(key, data);
  return data;
}

// ── Core fetch ──

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API error ${res.status}: ${text}`);
  }
  return res.json();
}

export async function getStats(): Promise<StatsResponse> {
  return fetchWithCache('stats', () =>
    fetchJSON<StatsResponse>(`${BASE_URL}/stats`)
  );
}

// Phase 30.C — provenance for citation-grade reproducibility.
export interface VersionInfo {
  service: string;
  app_version: string;
  phase: number;
  db_build_date?: string;
  db_sample_count?: number;
  db_project_count?: number;
  last_etl_run?: { label: string; finished_at: string };
  agent_parser_mode?: string;
  ontology?: {
    total_terms: number;
    by_source: Record<string, number>;
    total_mappings: number;
  };
}

export async function getVersion(): Promise<VersionInfo> {
  return fetchWithCache('version', () =>
    fetchJSON<VersionInfo>(`${BASE_URL}/version`)
  );
}

export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ── Explore API ──

export async function explore(
  filters: ExploreFilters,
  offset = 0,
  limit = 25,
  sort_by = 'n_cells',
  sort_dir = 'desc',
): Promise<ExploreResponse> {
  return fetchJSON<ExploreResponse>(`${BASE_URL}/explore`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      ...filters,
      sex: filters.sex || undefined,
      min_cells: filters.min_cells || undefined,
      has_h5ad: filters.has_h5ad || undefined,
      text_search: filters.text_search || undefined,
      nl_query: filters.nl_query || undefined,
      collection: filters.collection || undefined,
      offset,
      limit,
      sort_by,
      sort_dir,
    }),
  });
}

// ── Dataset Detail API ──

export async function getDatasetDetail(id: string): Promise<DatasetDetailResponse> {
  return fetchJSON<DatasetDetailResponse>(`${BASE_URL}/dataset/${encodeURIComponent(id)}`);
}

// ── Dashboard Stats API (cached) ──

export async function getDashboardStats(): Promise<DashboardStats> {
  return fetchWithCache('dashboard', () =>
    fetchJSON<DashboardStats>(`${BASE_URL}/stats/dashboard`)
  );
}

// ── Downloads API ──

export async function getDownloads(
  id: string,
  deep = false,
): Promise<{
  entity_id: string;
  source_database: string;
  deep: boolean;
  total_bytes: number | null;
  total_size_human: string | null;
  downloads: DownloadOption[];
}> {
  const q = deep ? '?deep=true' : '';
  return fetchJSON(`${BASE_URL}/downloads/${encodeURIComponent(id)}${q}`);
}

export async function estimateDownloads(
  entityIds: string[],
  fileTypes: string[],
  entries: ManifestEntryIn[] = [],
  deep = true,
): Promise<DownloadEstimate> {
  return fetchJSON<DownloadEstimate>(`${BASE_URL}/downloads/estimate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ entity_ids: entityIds, entries, file_types: fileTypes, deep }),
  });
}

export interface ManifestEntryIn {
  id: string;
  source_db?: string;
  url?: string | null;
  file_type?: string | null;
  title?: string | null;
}

export async function generateManifest(
  entityIds: string[],
  fileTypes: string[] = ['fastq'],
  format: string = 'tsv',
  entries: ManifestEntryIn[] = [],
  deep = true,
): Promise<Blob> {
  const res = await fetch(`${BASE_URL}/downloads/manifest`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    // Phase 27: send inline manifest entries (with URLs) so Discover-sourced
    // datasets not in the local catalog still make it into the script.
    // Phase 36: deep=true resolves exact files (sizes + MD5) from ENA/GEO.
    body: JSON.stringify({ entity_ids: entityIds, entries, file_types: fileTypes, format, deep }),
  });
  if (!res.ok) {
    let detail = `${res.status}`;
    try { const j = await res.json(); detail = j.detail || detail; } catch { /* keep status */ }
    throw new Error(detail);
  }
  return res.blob();
}

// ── Advanced Search API ──

export async function advancedSearch(
  req: AdvancedSearchRequest,
): Promise<AdvancedSearchResponse> {
  return fetchJSON<AdvancedSearchResponse>(`${BASE_URL}/advanced-search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
}

// ── Metadata Download ──

export async function downloadMetadata(
  samplePks: number[],
  format: 'csv' | 'json' = 'csv',
  limit = 1000,
): Promise<Blob> {
  const res = await fetch(`${BASE_URL}/downloads/metadata`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sample_pks: samplePks, format, limit }),
  });
  if (!res.ok) throw new Error(`Metadata download failed: ${res.status}`);
  return res.blob();
}

// ── Project & Series search (Phase 15B) ──

export async function searchProjects(
  req: ProjectSearchRequest,
): Promise<ProjectSearchResponse> {
  return fetchJSON<ProjectSearchResponse>(`${BASE_URL}/projects/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
}

export async function searchSeries(
  req: SeriesSearchRequest,
): Promise<SeriesSearchResponse> {
  return fetchJSON<SeriesSearchResponse>(`${BASE_URL}/series/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
}

export async function getProjectsStatsBySource(): Promise<ProjectsStatsBySource> {
  return fetchWithCache('projects_stats_by_source', () =>
    fetchJSON<ProjectsStatsBySource>(`${BASE_URL}/projects/stats_by_source`)
  );
}

// ── Cell-type browse tier (Phase 39) ──

export async function searchCellTypes(opts: {
  q?: string;
  sort?: CellTypeSort;
  minSamples?: number;
  limit?: number;
  offset?: number;
}): Promise<CellTypeSearchResponse> {
  const p = new URLSearchParams();
  if (opts.q) p.set('q', opts.q);
  if (opts.sort) p.set('sort', opts.sort);
  if (opts.minSamples) p.set('min_samples', String(opts.minSamples));
  if (opts.limit != null) p.set('limit', String(opts.limit));
  if (opts.offset != null) p.set('offset', String(opts.offset));
  const qs = p.toString();
  return fetchJSON<CellTypeSearchResponse>(`${BASE_URL}/celltypes/search${qs ? `?${qs}` : ''}`);
}

export async function getCellTypeProjects(
  name: string,
  limit = 50,
): Promise<CellTypeProjectsResponse> {
  return fetchJSON<CellTypeProjectsResponse>(
    `${BASE_URL}/celltypes/${encodeURIComponent(name)}/projects?limit=${limit}`,
  );
}

// ── Workspace (Phase 15D) ──
//
// Identity is the X-Client-UUID header (persisted in localStorage)
// joined with the request IP server-side. Each call below ensures
// the header is set and re-uses the stored UUID.

const WORKSPACE_UUID_KEY = 'sceqtl.workspace.uuid';

function getOrCreateClientUuid(): string {
  let uuid = localStorage.getItem(WORKSPACE_UUID_KEY);
  if (!uuid) {
    // crypto.randomUUID() is widely available; fall back to Math.random
    uuid = (typeof crypto !== 'undefined' && 'randomUUID' in crypto)
      ? crypto.randomUUID()
      : `ws-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
    localStorage.setItem(WORKSPACE_UUID_KEY, uuid);
  }
  return uuid;
}

function workspaceHeaders(): HeadersInit {
  return {
    'Content-Type': 'application/json',
    'X-Client-UUID': getOrCreateClientUuid(),
  };
}

export async function workspaceList(includeDeleted = false): Promise<{ workspaces: WorkspaceMeta[] }> {
  const qs = includeDeleted ? '?include_deleted=true' : '';
  return fetchJSON(`${BASE_URL}/workspace/list${qs}`, { headers: workspaceHeaders() });
}

export async function workspaceCreate(name: string, description = ''): Promise<WorkspaceMeta> {
  return fetchJSON(`${BASE_URL}/workspace/create`, {
    method: 'POST',
    headers: workspaceHeaders(),
    body: JSON.stringify({ name, description }),
  });
}

export async function workspaceGet(id: number): Promise<WorkspaceWithItems> {
  return fetchJSON(`${BASE_URL}/workspace/${id}`, { headers: workspaceHeaders() });
}

export async function workspaceUpdate(
  id: number, patch: { name?: string; description?: string },
): Promise<WorkspaceMeta> {
  return fetchJSON(`${BASE_URL}/workspace/${id}`, {
    method: 'PATCH',
    headers: workspaceHeaders(),
    body: JSON.stringify(patch),
  });
}

export async function workspaceAddItems(
  id: number, items: Omit<WorkspaceItem, 'id' | 'workspace_id' | 'added_at'>[],
): Promise<AddItemsResult> {
  return fetchJSON(`${BASE_URL}/workspace/${id}/items`, {
    method: 'POST',
    headers: workspaceHeaders(),
    body: JSON.stringify({ items }),
  });
}

export async function workspaceRemoveItem(id: number, itemPk: number): Promise<{ removed: boolean }> {
  return fetchJSON(`${BASE_URL}/workspace/${id}/items/${itemPk}`, {
    method: 'DELETE',
    headers: workspaceHeaders(),
  });
}

export async function workspaceDelete(id: number): Promise<{ deleted: boolean }> {
  return fetchJSON(`${BASE_URL}/workspace/${id}`, {
    method: 'DELETE',
    headers: workspaceHeaders(),
  });
}

export async function workspaceRecover(id: number): Promise<{ recovered: boolean }> {
  return fetchJSON(`${BASE_URL}/workspace/${id}/recover`, {
    method: 'POST',
    headers: workspaceHeaders(),
  });
}

export async function workspaceExport(id: number, format: 'csv' | 'json'): Promise<Blob> {
  const res = await fetch(`${BASE_URL}/workspace/${id}/export?format=${format}`, {
    headers: workspaceHeaders(),
  });
  if (!res.ok) throw new Error(`Workspace export failed: ${res.status}`);
  return res.blob();
}
