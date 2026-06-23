/**
 * useAdvancedSearch — Phase 27.
 *
 * Thin React binding over the module-scoped `advancedSearchStore`. State lives
 * outside the component so an in-flight NL→SQL query keeps running (and its
 * result is shown) across navigation, and there is never more than one request
 * in flight. The hook only owns the URL-param → "fresh search vs restore"
 * decision on mount.
 */

import { useCallback, useSyncExternalStore, useRef, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import type { ParsedCondition } from '../types/api';
import {
  subscribe, getState, execute, setConditions, setAppliedSig,
  retry as storeRetry, dismissError as storeDismiss, LIMIT,
} from './advancedSearchStore';

export type { NlPhase } from './advancedSearchStore';

/** Map URL search params → initial conditions. */
function paramsToConditions(sp: URLSearchParams): ParsedCondition[] {
  const FIELDS: Record<string, string> = {
    tissue: 'Tissue', disease: 'Disease', organism: 'Organism',
    assay: 'Assay', cell_type: 'Cell Type', source_database: 'Database',
    sex: 'Sex', project_id: 'Project ID', sample_id: 'Sample ID',
  };
  const conds: ParsedCondition[] = [];
  for (const [field, label] of Object.entries(FIELDS)) {
    const raw = sp.get(field);
    if (raw) {
      const values = raw.split(',').filter(Boolean);
      if (values.length) {
        conds.push({
          field, operator: 'in', values,
          display_label: `${label}: ${values.join(', ')}`,
          source: 'facet_select', confidence: 1,
        });
      }
    }
  }
  const q = sp.get('q');
  if (q) {
    conds.push({
      field: 'text_search', operator: 'like', values: [q],
      display_label: `Text: ${q}`, source: 'nl_parse', confidence: 1,
    });
  }
  return conds;
}

const LABELS: Record<string, string> = {
  tissue: 'Tissue', disease: 'Disease', organism: 'Organism',
  assay: 'Assay', cell_type: 'Cell Type', source_database: 'Database', sex: 'Sex',
};

export function useAdvancedSearch() {
  const [searchParams] = useSearchParams();
  const state = useSyncExternalStore(subscribe, getState, getState);
  const didInit = useRef(false);

  // On mount: if the URL carries filters/query that differ from what the store
  // last ran, start a fresh search. Otherwise restore the store's prior state
  // (which may still be loading — the query keeps running across navigation).
  useEffect(() => {
    if (didInit.current) return;
    didInit.current = true;
    const sig = searchParams.toString();
    const urlConds = paramsToConditions(searchParams);
    if (urlConds.length > 0 && sig !== getState().appliedSig) {
      setAppliedSig(sig);
      setConditions(urlConds);
      void execute(urlConds, undefined, 1, getState().sortBy, getState().sortDir);
    }
    // No params + no prior state → leave empty (avoids a 30s "fetch everything").
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // R2-2: `refine` keeps the current conditions and ANDs the NL query onto
  // them (search-within-results); the default starts a fresh search by
  // clearing prior conditions so a new query doesn't silently inherit them.
  const sendQuery = useCallback((nl: string, refine = false) => {
    const s = getState();
    const base = refine ? s.conditions : [];
    if (!refine) setConditions([]);
    void execute(base, nl, 1, s.sortBy, s.sortDir);
  }, []);

  const removeCondition = useCallback((index: number) => {
    const s = getState();
    const next = s.conditions.filter((_, i) => i !== index);
    setConditions(next);
    void execute(next, undefined, 1, s.sortBy, s.sortDir);
  }, []);

  const addFacetCondition = useCallback((field: string, value: string) => {
    const s = getState();
    const existing = s.conditions.find((c) => c.field === field);
    let next: ParsedCondition[];
    if (existing) {
      if (existing.values.includes(value)) {
        const newVals = existing.values.filter((v) => v !== value);
        next = newVals.length === 0
          ? s.conditions.filter((c) => c.field !== field)
          : s.conditions.map((c) => c.field === field
            ? { ...c, values: newVals, display_label: `${LABELS[field] || field}: ${newVals.join(', ')}` }
            : c);
      } else {
        const newVals = [...existing.values, value];
        next = s.conditions.map((c) => c.field === field
          ? { ...c, values: newVals, display_label: `${LABELS[field] || field}: ${newVals.join(', ')}` }
          : c);
      }
    } else {
      next = [...s.conditions, {
        field, operator: 'in', values: [value],
        display_label: `${LABELS[field] || field}: ${value}`,
        source: 'facet_select' as const, confidence: 1,
      }];
    }
    setConditions(next);
    void execute(next, undefined, 1, s.sortBy, s.sortDir);
  }, []);

  const clearAll = useCallback(() => {
    const s = getState();
    setConditions([]);
    void execute([], undefined, 1, s.sortBy, s.sortDir);
  }, []);

  const setPage = useCallback((p: number) => {
    const s = getState();
    void execute(s.conditions, undefined, p, s.sortBy, s.sortDir);
  }, []);

  const setSort = useCallback((col: string) => {
    const s = getState();
    const dir = col === s.sortBy && s.sortDir === 'desc' ? 'asc' : 'desc';
    void execute(s.conditions, undefined, 1, col, dir);
  }, []);

  const retry = useCallback(() => storeRetry(), []);
  const dismissError = useCallback(() => storeDismiss(), []);

  // conditions → activeFilters map for FacetSidebar
  const activeFilters: Record<string, string[]> = {};
  for (const c of state.conditions) {
    const keyMap: Record<string, string> = {
      tissue: 'tissues', disease: 'diseases', organism: 'organisms',
      assay: 'assays', cell_type: 'cell_types', source_database: 'source_databases',
      sex: 'sex',
    };
    const fk = keyMap[c.field];
    if (fk) activeFilters[fk] = c.values;
  }

  return {
    ...state,
    activeFilters,
    limit: LIMIT,
    sendQuery,
    removeCondition,
    addFacetCondition,
    clearAll,
    setPage,
    setSort,
    retry,
    dismissError,
  };
}
