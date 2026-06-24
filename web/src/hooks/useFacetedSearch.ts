import { useState, useEffect, useCallback, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { explore } from '../services/api';
import { useDebounce } from './useDebounce';
import { toast } from '../lib/toastApi';
import type { ExploreResponse, ExploreRecord, FacetBucket } from '../types/api';
import type { ExploreFilters } from '../types/filters';
import { DEFAULT_FILTERS } from '../types/filters';

const ARRAY_FIELDS = [
  'tissues', 'diseases', 'organisms', 'assays', 'cell_types', 'source_databases',
  'tissue_systems', 'disease_categories', 'sample_types',
] as const;

const PARAM_MAP: Record<string, string> = {
  tissues: 'tissue', diseases: 'disease', organisms: 'organism',
  assays: 'assay', cell_types: 'cell_type', source_databases: 'source_database',
  tissue_systems: 'tissue_system', disease_categories: 'disease_category',
  sample_types: 'sample_type',
};

function filtersFromParams(params: URLSearchParams): ExploreFilters {
  const f = { ...DEFAULT_FILTERS };
  for (const key of ARRAY_FIELDS) {
    const paramKey = PARAM_MAP[key];
    const val = params.get(paramKey);
    if (val) f[key] = val.split(',');
  }
  f.sex = params.get('sex') || null;
  f.text_search = params.get('q') || '';
  f.nl_query = params.get('nl') || '';
  f.collection = params.get('collection') || null;
  const mc = params.get('min_cells');
  if (mc) f.min_cells = parseInt(mc, 10);
  if (params.get('has_h5ad') === 'true') f.has_h5ad = true;
  return f;
}

function filtersToParams(filters: ExploreFilters): URLSearchParams {
  const p = new URLSearchParams();
  for (const key of ARRAY_FIELDS) {
    if (filters[key].length > 0) p.set(PARAM_MAP[key], filters[key].join(','));
  }
  if (filters.sex) p.set('sex', filters.sex);
  if (filters.text_search) p.set('q', filters.text_search);
  if (filters.nl_query) p.set('nl', filters.nl_query);
  if (filters.collection) p.set('collection', filters.collection);
  if (filters.min_cells) p.set('min_cells', String(filters.min_cells));
  if (filters.has_h5ad) p.set('has_h5ad', 'true');
  return p;
}

export function useFacetedSearch() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [filters, setFiltersState] = useState<ExploreFilters>(() => filtersFromParams(searchParams));
  const [results, setResults] = useState<ExploreRecord[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [facets, setFacets] = useState<Record<string, FacetBucket[]>>({});
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(() => {
    const p = searchParams.get('page');
    return p ? parseInt(p, 10) : 1;
  });
  const [sortBy, setSortBy] = useState(searchParams.get('sort') || 'n_cells');
  const [sortDir, setSortDir] = useState(searchParams.get('dir') || 'desc');
  const limit = 25;
  const abortRef = useRef<AbortController | null>(null);

  // Debounce filters to avoid rapid-fire API calls on checkbox clicks
  const debouncedFilters = useDebounce(filters, 300);

  const setFilters = useCallback((newFilters: ExploreFilters) => {
    setFiltersState(newFilters);
    setPage(1);
    const params = filtersToParams(newFilters);
    params.set('sort', sortBy);
    params.set('dir', sortDir);
    setSearchParams(params, { replace: true });
  }, [sortBy, sortDir, setSearchParams]);

  const setSort = useCallback((col: string) => {
    if (col === sortBy) {
      setSortDir((d) => d === 'desc' ? 'asc' : 'desc');
    } else {
      setSortBy(col);
      setSortDir('desc');
    }
  }, [sortBy]);

  // Fetch on debounced filter/page/sort change. setLoading is the
  // expected idiom here — the skeleton row needs to appear before the
  // request resolves.
  useEffect(() => {
    if (abortRef.current) abortRef.current.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    const offset = (page - 1) * limit;

    explore(debouncedFilters, offset, limit, sortBy, sortDir)
      .then((resp: ExploreResponse) => {
        if (ctrl.signal.aborted) return;
        setResults(resp.results);
        setTotalCount(resp.total_count);
        setFacets(resp.facets);
      })
      .catch((e) => {
        if (ctrl.signal.aborted) return;
        toast(`Explore failed: ${e}`, 'error');
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setLoading(false);
      });

    return () => ctrl.abort();
  }, [debouncedFilters, page, sortBy, sortDir]);

  // Sync URL params on page/sort changes
  useEffect(() => {
    const params = filtersToParams(filters);
    if (page > 1) params.set('page', String(page));
    params.set('sort', sortBy);
    params.set('dir', sortDir);
    setSearchParams(params, { replace: true });
  }, [page, sortBy, sortDir, filters, setSearchParams]);

  return {
    filters, setFilters,
    results, totalCount,
    facets, loading,
    page, setPage,
    sortBy, sortDir, setSort,
    limit,
  };
}
