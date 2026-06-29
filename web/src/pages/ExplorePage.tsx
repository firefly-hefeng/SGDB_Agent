import { useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Loader2, SearchCode, Radio, Sparkles, X, SlidersHorizontal } from 'lucide-react';
import { useFacetedSearch } from '../hooks/useFacetedSearch';
import { FacetSidebar } from '../components/explore/FacetSidebar';
import { ActiveFilters } from '../components/explore/ActiveFilters';
import { SearchBar } from '../components/explore/SearchBar';
import { ResultsTable } from '../components/explore/ResultsTable';
import { Pagination } from '../components/explore/Pagination';
import { TargetLevelTabs } from '../components/explore/TargetLevelTabs';
import { HowToUse } from '../components/ui/HowToUse';
import { Eyebrow } from '../components/ui/PageHeader';
import { DEFAULT_FILTERS } from '../types/filters';
import { useT } from '../lib/i18n';

export default function ExplorePage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { t } = useT();
  const {
    filters,
    setFilters,
    results,
    totalCount,
    facets,
    loading,
    page,
    setPage,
    sortBy,
    sortDir,
    setSort,
    limit,
  } = useFacetedSearch();
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false);

  const active: Record<string, string[]> = {
    tissues: filters.tissues,
    diseases: filters.diseases,
    organisms: filters.organisms,
    assays: filters.assays,
    cell_types: filters.cell_types,
    source_databases: filters.source_databases,
  };

  const remove = (f: string, v: string) => {
    const cur = (filters as unknown as Record<string, unknown>)[f];
    if (Array.isArray(cur)) {
      setFilters({ ...filters, [f]: cur.filter((x: string) => x !== v) });
    }
  };

  const goToSearch = () => {
    const params = new URLSearchParams();
    const map: Record<string, string> = {
      tissues: 'tissue',
      diseases: 'disease',
      organisms: 'organism',
      assays: 'assay',
      cell_types: 'cell_type',
      source_databases: 'source_database',
    };
    for (const [fk, field] of Object.entries(map)) {
      const vals = active[fk];
      if (vals?.length) params.set(field, vals.join(','));
    }
    if (filters.sex) params.set('sex', filters.sex);
    if (filters.text_search) params.set('q', filters.text_search);
    navigate(`/search?${params.toString()}`);
  };

  const goToDiscover = () => {
    // Carry the user's intent across the dual-agent handoff: if there's no free-text
    // query, synthesize one from the active facet filters (organism/tissue/disease/
    // cell-type/assay) so Discover doesn't start blank.
    const facetTerms = ['organisms', 'tissues', 'diseases', 'cell_types', 'assays']
      .flatMap((k) => active[k] || []);
    const q = (filters.text_search || filters.nl_query || facetTerms.join(' ')).trim();
    navigate(q ? `/discover?q=${encodeURIComponent(q)}` : '/discover');
  };

  return (
    <div className="flex flex-1 min-h-0">
      <FacetSidebar
        facets={facets}
        activeFilters={active}
        onFilterChange={(f, v) => setFilters({ ...filters, [f]: v })}
        loading={loading}
        mobileOpen={mobileFiltersOpen}
        onMobileClose={() => setMobileFiltersOpen(false)}
      />
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden bg-canvas">
        <header className="page-header-band px-5 pt-4 pb-2.5 bg-canvas">
          <div className="relative flex items-start justify-between gap-3 mb-3">
            <div className="min-w-0">
              <Eyebrow>{t('explore.eyebrow', 'Curated catalog')}</Eyebrow>
              <div className="flex items-center gap-3 min-w-0">
                <h1 className="text-2xl font-semibold text-ink leading-tight">{t('explore.title', 'Explore datasets')}</h1>
                <TargetLevelTabs />
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <button
                onClick={() => setMobileFiltersOpen(true)}
                className="lg:hidden btn-ghost text-xs inline-flex items-center gap-1 px-2 py-1"
                title={t('explore.show_filters', 'Show filters')}
                aria-label={t('explore.show_filters', 'Show filters')}
              >
                <SlidersHorizontal size={13} /> {t('explore.filters', 'Filters')}
              </button>
              <button
                onClick={goToSearch}
                className="btn-ghost text-xs inline-flex items-center gap-1 px-2 py-1"
                title={t('explore.advanced.title', 'Open in Advanced Search with the current filters')}
              >
                <SearchCode size={13} /> {t('explore.advanced', 'Advanced')}
              </button>
              <button
                onClick={goToDiscover}
                className="btn-ghost text-xs inline-flex items-center gap-1 px-2 py-1"
                title={t('explore.discover.title', 'Run the same query live against public source databases')}
              >
                <Radio size={13} /> {t('explore.discover_live', 'Discover live')}
              </button>
              {loading && <Loader2 size={14} className="animate-spin text-accent" />}
              <span className="text-xs text-ink-subtle tabular-nums">
                {totalCount.toLocaleString()} {t('explore.results', 'results')}
              </span>
            </div>
          </div>
          <SearchBar
            textSearch={filters.text_search}
            nlQuery={filters.nl_query}
            onTextSearchChange={(t) => setFilters({ ...filters, text_search: t })}
            onNlQueryChange={(t) => setFilters({ ...filters, nl_query: t })}
          />
          <ActiveFilters
            filters={active}
            onRemove={remove}
            onClearAll={() => {
              setFilters({ ...DEFAULT_FILTERS });
              setPage(1);
              setSort('n_cells');
            }}
          />
          <HowToUse
            className="mt-2"
            body={t('intro.explore.body',
              'Faceted browse of the curated sample catalog — the cell-level tier. Reach for Projects/Series for study-level metadata, or Discover for the newest public submissions.')}
            examples={[
              { label: 'tissue=lung disease=COVID-19', to: '/explore?tissue=lung&disease=COVID-19', hint: 'lung samples in COVID-19 studies' },
              { label: 'tissue=pancreas disease=type 2 diabetes', to: '/explore?tissue=pancreas&disease=type 2 diabetes' },
              { label: 'assay=10x has_h5ad', to: '/explore?assay=10x&has_h5ad=true', hint: 'downloadable 10x objects' },
            ]}
          />
          {/* R2-4: when arriving from a Featured Collection, make the curated
              filter explicit and offer a one-click exit to the full catalog. */}
          {filters.collection && (
            <div className="mt-2 flex items-center justify-between gap-2 rounded-md border border-accent-border/50 bg-accent-bg px-3 py-1.5">
              <span className="text-xs text-accent inline-flex items-center gap-1.5 min-w-0">
                <Sparkles size={12} className="shrink-0" />
                <span className="truncate">
                  {t('explore.collection.label', 'Curated collection:')}{' '}
                  <span className="font-medium">
                    {(location.state as { collectionTitle?: string } | null)?.collectionTitle
                      || filters.collection}
                  </span>
                </span>
              </span>
              <button
                onClick={() => { setFilters({ ...filters, collection: null }); setPage(1); }}
                className="text-2xs text-accent hover:underline inline-flex items-center gap-1 shrink-0"
              >
                <X size={11} /> {t('explore.collection.browse_full', 'Browse full catalog')}
              </button>
            </div>
          )}
        </header>
        <div className="flex-1 overflow-y-auto px-5">
          <ResultsTable
            results={results}
            totalCount={totalCount}
            sortBy={sortBy}
            sortDir={sortDir}
            onSort={setSort}
            loading={loading}
            hasActiveFilters={
              Object.values(active).some((v) => v?.length > 0) ||
              !!filters.text_search || !!filters.nl_query || !!filters.sex
            }
            onClearFilters={() => {
              setFilters({ ...DEFAULT_FILTERS });
              setPage(1);
              setSort('n_cells');
            }}
            onTryDiscover={goToDiscover}
            searchLabel={filters.text_search || filters.nl_query || undefined}
          />
        </div>
        <div className="px-5 border-t border-line">
          <Pagination
            page={page}
            totalCount={totalCount}
            limit={limit}
            onPageChange={setPage}
          />
        </div>
      </div>
    </div>
  );
}
