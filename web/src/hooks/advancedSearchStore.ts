/**
 * advancedSearchStore — Phase 27.
 *
 * A module-scoped (singleton) store for the Advanced Search page so that:
 *  - a long-running NL→SQL query KEEPS RUNNING when the user navigates away,
 *    and its result is shown when they return (the prior hook lost it and the
 *    in-flight request set state on an unmounted component → "chaos");
 *  - only ONE request is in flight at a time (a new search aborts the prior),
 *    managed at module level rather than per-mount, so re-entering /search
 *    never spawns overlapping controllers;
 *  - phase timers live at module level and can't leak onto a dead component.
 *
 * The React hook (`useAdvancedSearch`) is a thin `useSyncExternalStore`
 * subscriber over this store.
 */

import type {
  ParsedCondition, AdvancedSearchResponse, ExploreRecord, FacetBucket,
} from '../types/api';
import { advancedSearch } from '../services/api';

export type NlPhase = 'idle' | 'parsing' | 'resolving' | 'querying' | 'fusing';

export interface AdvancedSearchState {
  conditions: ParsedCondition[];
  results: ExploreRecord[];
  totalCount: number;
  facets: Record<string, FacetBucket[]>;
  summary: string;
  provenance: AdvancedSearchResponse['provenance'] | null;
  suggestions: AdvancedSearchResponse['suggestions'];
  aggregation: Record<string, unknown>[];
  loading: boolean;
  loadingPhase: NlPhase;
  loadingStartedAt: number | null;
  error: string | null;
  page: number;
  sortBy: string;
  sortDir: string;
  /** Signature of the URL params last turned into a fresh search; lets the
   *  page decide whether a (re)mount should auto-run or just restore. */
  appliedSig: string | null;
}

export const LIMIT = 25;

const initialState: AdvancedSearchState = {
  conditions: [],
  results: [],
  totalCount: 0,
  facets: {},
  summary: '',
  provenance: null,
  suggestions: [],
  aggregation: [],
  loading: false,
  loadingPhase: 'idle',
  loadingStartedAt: null,
  error: null,
  page: 1,
  sortBy: 'n_cells',
  sortDir: 'desc',
  appliedSig: null,
};

/**
 * Phase 33 (B6) — survive a full page reload.
 *
 * The store is module-scoped, so navigating away and back keeps state, but a
 * hard refresh (F5) re-imports the module and wiped everything: results, the
 * executed SQL, the facets. And because NL queries / facet conditions are
 * never written to the URL, there was nothing to restore from either. We now
 * snapshot a curated subset of the *completed* state to sessionStorage and
 * rehydrate it on module load — refresh restores the last result set instantly
 * without re-running the (expensive) NL→SQL pipeline.
 */
const SNAPSHOT_KEY = 'sceqtl.advsearch.v1';
// Fields safe + useful to persist. Excludes transient flags (loading*, error,
// abort) and is capped so we don't blow the sessionStorage quota on huge runs.
const SNAPSHOT_FIELDS = [
  'conditions', 'results', 'totalCount', 'facets', 'summary', 'provenance',
  'suggestions', 'aggregation', 'page', 'sortBy', 'sortDir', 'appliedSig',
] as const;

function loadSnapshot(): AdvancedSearchState {
  if (typeof sessionStorage === 'undefined') return initialState;
  try {
    const raw = sessionStorage.getItem(SNAPSHOT_KEY);
    if (!raw) return initialState;
    const snap = JSON.parse(raw) as Partial<AdvancedSearchState>;
    // Restore as a settled (non-loading) state.
    return {
      ...initialState,
      ...snap,
      loading: false,
      loadingPhase: 'idle',
      loadingStartedAt: null,
      error: null,
    };
  } catch {
    return initialState;
  }
}

function saveSnapshot() {
  if (typeof sessionStorage === 'undefined') return;
  // Never persist an in-flight state — only completed result sets.
  if (_state.loading) return;
  try {
    const snap: Record<string, unknown> = {};
    for (const k of SNAPSHOT_FIELDS) snap[k] = _state[k];
    sessionStorage.setItem(SNAPSHOT_KEY, JSON.stringify(snap));
  } catch {
    // Quota exceeded (very large result set) — drop the cache rather than throw.
    try { sessionStorage.removeItem(SNAPSHOT_KEY); } catch { /* ignore */ }
  }
}

let _state: AdvancedSearchState = loadSnapshot();
const _listeners = new Set<() => void>();
let _abort: AbortController | null = null;
let _timers: number[] = [];
let _lastAttempt: {
  conditions: ParsedCondition[];
  nlQuery: string | undefined;
  page: number;
  sortBy: string;
  sortDir: string;
} | null = null;

function emit() {
  for (const cb of _listeners) cb();
}

function setState(patch: Partial<AdvancedSearchState>) {
  _state = { ..._state, ...patch };
  saveSnapshot();
  emit();
}

export function subscribe(cb: () => void): () => void {
  _listeners.add(cb);
  return () => _listeners.delete(cb);
}

export function getState(): AdvancedSearchState {
  return _state;
}

function clearTimers() {
  for (const id of _timers) window.clearTimeout(id);
  _timers = [];
}

// Phase-chip timers (observed medians): parse ~12s, ontology ~3s, SQL ~15s.
// With the Phase 27 turbo model the whole thing is usually a few seconds, so
// these are an upper-bound progress hint, not a simulation of completion.
function startPhaseTimers(isNlQuery: boolean) {
  clearTimers();
  if (!isNlQuery) return;
  _timers.push(
    window.setTimeout(() => { if (_state.loading) setState({ loadingPhase: 'resolving' }); }, 8_000),
    window.setTimeout(() => { if (_state.loading) setState({ loadingPhase: 'querying' }); }, 16_000),
    window.setTimeout(() => { if (_state.loading) setState({ loadingPhase: 'fusing' }); }, 30_000),
  );
}

/** Core executor — module-level, survives component unmount. */
export async function execute(
  conditions: ParsedCondition[],
  nlQuery: string | undefined,
  page: number,
  sortBy: string,
  sortDir: string,
) {
  _abort?.abort();
  const ac = new AbortController();
  _abort = ac;
  _lastAttempt = { conditions, nlQuery, page, sortBy, sortDir };

  const isNl = typeof nlQuery === 'string' && nlQuery.trim().length > 0;
  setState({
    loading: true,
    loadingPhase: isNl ? 'parsing' : 'idle',
    loadingStartedAt: Date.now(),
    error: null,
  });
  startPhaseTimers(isNl);

  try {
    const resp = await advancedSearch({
      nl_query: nlQuery,
      conditions,
      session_id: 'default',
      limit: LIMIT,
      offset: (page - 1) * LIMIT,
      sort_by: sortBy,
      sort_dir: sortDir,
    });
    if (ac.signal.aborted) return; // superseded by a newer search
    clearTimers();
    setState({
      conditions: resp.conditions,
      results: resp.results as ExploreRecord[],
      totalCount: resp.total_count,
      facets: resp.facets as Record<string, FacetBucket[]>,
      summary: resp.summary,
      provenance: resp.provenance,
      suggestions: resp.suggestions,
      aggregation: resp.aggregation || [],
      loading: false,
      loadingPhase: 'idle',
      loadingStartedAt: null,
      error: resp.error || null,
      page,
      sortBy,
      sortDir,
    });
  } catch (e) {
    if (ac.signal.aborted) return;
    clearTimers();
    setState({
      loading: false,
      loadingPhase: 'idle',
      loadingStartedAt: null,
      error: e instanceof Error ? e.message : 'Search failed',
    });
  }
}

export function setConditions(conditions: ParsedCondition[]) {
  setState({ conditions });
}

export function setAppliedSig(sig: string) {
  setState({ appliedSig: sig });
}

export function retry(): boolean {
  if (!_lastAttempt) return false;
  const l = _lastAttempt;
  void execute(l.conditions, l.nlQuery, l.page, l.sortBy, l.sortDir);
  return true;
}

export function dismissError() {
  setState({ error: null });
}

/** Hard reset — used by tests / "start over". */
export function resetAdvancedSearch() {
  _abort?.abort();
  clearTimers();
  _abort = null;
  _lastAttempt = null;
  _state = initialState;
  if (typeof sessionStorage !== 'undefined') {
    try { sessionStorage.removeItem(SNAPSHOT_KEY); } catch { /* ignore */ }
  }
  emit();
}
