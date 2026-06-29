import { useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, Download, ArrowRight, Loader2, Sparkles, SlidersHorizontal } from 'lucide-react';
import { useAdvancedSearch } from '../hooks/useAdvancedSearch';
import { FacetSidebar } from '../components/explore/FacetSidebar';
import { ResultsTable } from '../components/explore/ResultsTable';
import { Pagination } from '../components/explore/Pagination';
import { ConditionCards } from '../components/search/ConditionCards';
import { ExecutionTrace } from '../components/search/ExecutionTrace';
import { AggregationResult } from '../components/search/AggregationResult';
import { NlProgress } from '../components/search/NlProgress';
import { SearchErrorCard } from '../components/search/SearchErrorCard';
import { HowToUse } from '../components/ui/HowToUse';
import { Eyebrow } from '../components/ui/PageHeader';
import { downloadMetadata, downloadBlob } from '../services/api';
import { toast } from '../lib/toastApi';
import { useT } from '../lib/i18n';

export default function AdvancedSearchPage() {
  const navigate = useNavigate();
  const { t } = useT();
  const [nlInput, setNlInput] = useState('');
  // R2-2: when on, a new NL query refines within the current conditions
  // (AND) instead of starting fresh.
  const [refineMode, setRefineMode] = useState(false);
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false);

  const {
    conditions, results, totalCount, facets, summary, provenance,
    suggestions, loading, loadingPhase, loadingStartedAt, error,
    page, sortBy, sortDir, aggregation,
    activeFilters, limit,
    sendQuery, removeCondition, addFacetCondition, clearAll, setPage, setSort,
    retry, dismissError,
  } = useAdvancedSearch();

  const handleSubmit = useCallback((e: React.FormEvent) => {
    e.preventDefault();
    const q = nlInput.trim();
    if (!q) return;
    sendQuery(q, refineMode && conditions.length > 0);
    setNlInput('');
  }, [nlInput, sendQuery, refineMode, conditions.length]);

  const handleFacetChange = useCallback((filterKey: string, values: string[]) => {
    const keyMap: Record<string, string> = {
      tissues: 'tissue', diseases: 'disease', organisms: 'organism',
      assays: 'assay', cell_types: 'cell_type', source_databases: 'source_database',
      sex: 'sex',
    };
    const field = keyMap[filterKey] || filterKey;

    // addFacetCondition is a TOGGLE — diff symmetric, toggle once per item.
    const current = conditions.find((c) => c.field === field);
    const currentVals = current?.values || [];
    const symmetricDiff = [
      ...values.filter((v) => !currentVals.includes(v)),
      ...currentVals.filter((v) => !values.includes(v)),
    ];
    for (const v of symmetricDiff) addFacetCondition(field, v);
  }, [conditions, addFacetCondition]);

  const handleMetadataDownload = useCallback(async (format: 'csv' | 'json') => {
    try {
      const pks = results.map((r) => r.sample_pk);
      const blob = await downloadMetadata(pks, format);
      downloadBlob(blob, `singligent_metadata.${format}`);
      toast(`${t('advanced.toast.downloaded_1', 'Downloaded')} ${results.length} ${t('advanced.toast.downloaded_2', 'samples as')} ${format.toUpperCase()}${t('advanced.toast.downloaded_3', '')}`);
    } catch (e) {
      toast(`${t('advanced.toast.download_failed', 'Metadata download failed:')} ${e}`, 'error');
    }
  }, [results, t]);

  const handleSendToDownloads = () => {
    const ids = results.map((r) => r.project_id || r.sample_id).filter(Boolean);
    if (!ids.length) {
      toast(t('advanced.toast.no_ids', 'No dataset IDs in the current results'), 'error');
      return;
    }
    navigate(`/downloads?ids=${encodeURIComponent(ids.join(','))}`);
  };

  return (
    <div className="flex flex-1 min-h-0 bg-canvas">
      <FacetSidebar
        facets={facets}
        activeFilters={activeFilters}
        onFilterChange={handleFacetChange}
        loading={loading}
        mobileOpen={mobileFiltersOpen}
        onMobileClose={() => setMobileFiltersOpen(false)}
      />

      <div className="flex flex-col flex-1 min-w-0 overflow-y-auto">
        <header className="page-header-band px-5 pt-4 pb-3 bg-canvas">
          <Eyebrow>{t('advanced.eyebrow', 'Advanced search')}</Eyebrow>
          <h1 className="text-2xl font-semibold text-ink leading-tight mb-2">
            {t('advanced.title', 'Build a query in natural language')}
          </h1>
          <p className="text-xs text-ink-muted mb-3 max-w-[60rem]">
            {t('advanced.desc',
              'The agent parses your query, expands ontology terms, generates SQL, runs it, and returns a faceted result set. Refine using the sidebar.')}
          </p>
          <button
            onClick={() => setMobileFiltersOpen(true)}
            className="lg:hidden btn-ghost text-xs inline-flex items-center gap-1 px-2 py-1 mb-2 border border-line rounded-md"
            title={t('explore.show_filters', 'Show filters')}
            aria-label={t('explore.show_filters', 'Show filters')}
          >
            <SlidersHorizontal size={13} /> {t('advanced.filters', 'Filters')}
          </button>
          <form onSubmit={handleSubmit} className="flex gap-2">
            <div className="relative flex-1">
              <Search
                size={15}
                className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-subtle pointer-events-none"
              />
              <input
                type="text"
                value={nlInput}
                onChange={(e) => setNlInput(e.target.value)}
                placeholder={t('advanced.input.placeholder', 'e.g. "human liver cancer 10x datasets" or "pancreatic islet from healthy donors"')}
                aria-label={t('advanced.input.aria', 'Natural-language search input')}
                className="w-full pl-10 pr-3 py-2.5 text-base bg-canvas border border-line rounded-md focus:outline-none focus:border-accent focus:ring-2 focus:ring-accent-bg"
                disabled={loading}
              />
            </div>
            <button
              type="submit"
              disabled={loading || !nlInput.trim()}
              className="btn btn-accent px-5 py-2.5 text-sm shrink-0 min-w-[110px]"
            >
              {loading ? (
                <>
                  <Loader2 size={14} className="animate-spin" /> {t('advanced.searching', 'Searching')}
                </>
              ) : (
                <>
                  <Sparkles size={14} /> {refineMode && conditions.length > 0 ? t('advanced.refine', 'Refine') : t('advanced.search', 'Search')}
                </>
              )}
            </button>
          </form>
          {/* R2-2: refine-within-results. Only meaningful once a range exists. */}
          {conditions.length > 0 && (
            <label className="mt-2 inline-flex items-center gap-1.5 text-xs text-ink-muted cursor-pointer select-none">
              <input
                type="checkbox"
                checked={refineMode}
                onChange={(e) => setRefineMode(e.target.checked)}
                className="rounded h-3.5 w-3.5"
              />
              {t('advanced.refine_within', 'Refine within current results')}
              <span className="text-ink-subtle">
                {t('advanced.refine_and_1', '(AND onto the')} {conditions.length} {conditions.length === 1 ? t('advanced.refine_and_condition', 'active condition') : t('advanced.refine_and_conditions', 'active conditions')}{t('advanced.refine.suffix', ')')}
              </span>
            </label>
          )}
          <HowToUse
            className="mt-3"
            body={t('intro.advanced.body',
              'One natural-language box over the curated catalog: the agent parses intent, expands ontology terms, generates SQL and returns a faceted result set. For keyword or ID lookup, Explore is faster.')}
            examples={[
              { label: 'human liver cancer 10x datasets', onPick: () => setNlInput('human liver cancer 10x datasets') },
              { label: 'pancreatic islet from healthy donors', onPick: () => setNlInput('pancreatic islet from healthy donors') },
              { label: 'how many COVID-19 lung samples per source', onPick: () => setNlInput('how many COVID-19 lung samples per source'), hint: 'aggregation query' },
            ]}
          />
        </header>

        <div className="px-5 py-4 space-y-3">
          {loading && loadingPhase !== 'idle' && (
            <NlProgress phase={loadingPhase} startedAt={loadingStartedAt} />
          )}

          <ConditionCards
            conditions={conditions}
            onRemove={removeCondition}
            onClearAll={clearAll}
          />

          {summary && (
            <div className="text-sm text-ink-muted bg-accent-bg border border-accent-border/50 rounded-md px-3 py-2">
              {summary}
            </div>
          )}

          {error && (
            <SearchErrorCard
              error={error}
              onRetry={retry}
              onDismiss={dismissError}
            />
          )}

          {suggestions.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-2xs uppercase tracking-wider text-ink-subtle mr-1">{t('advanced.refine_label', 'Refine:')}</span>
              {suggestions.map((s, i) => (
                <button
                  key={i}
                  onClick={() => {
                    const q = s.action_query || s.text || '';
                    if (!q) return;
                    setNlInput(q);
                    sendQuery(q);
                  }}
                  className="text-xs text-accent bg-accent-subtle hover:bg-accent-bg rounded-full px-3 py-1 transition-colors"
                >
                  {s.text}
                </button>
              ))}
            </div>
          )}

          <div className="flex items-center justify-between">
            <span className="text-sm text-ink-muted">
              {totalCount > 0 ? `${totalCount.toLocaleString()} ${t('common.samples', 'samples')}` : ''}
            </span>
            {results.length > 0 && (
              <div className="flex items-center gap-2">
                <button
                  onClick={() => handleMetadataDownload('csv')}
                  className="btn-ghost text-xs inline-flex items-center gap-1 px-2 py-1"
                >
                  <Download size={12} /> CSV
                </button>
                <button
                  onClick={() => handleMetadataDownload('json')}
                  className="btn-ghost text-xs inline-flex items-center gap-1 px-2 py-1"
                >
                  <Download size={12} /> JSON
                </button>
                <button
                  onClick={handleSendToDownloads}
                  className="btn-ghost text-xs inline-flex items-center gap-1 px-2 py-1"
                >
                  <ArrowRight size={12} /> Downloads
                </button>
              </div>
            )}
          </div>

          {/* Idle (no query run yet): show a prompt, NOT an empty "no results"
              table — the latter wrongly implies a search returned nothing. */}
          {(!loading && !error && !summary && results.length === 0 && !(aggregation && aggregation.length > 0)) ? (
            <div className="text-center text-ink-muted py-20 text-sm">
              {t('advanced.idle', 'Enter a natural-language query above to search the curated catalog.')}
            </div>
          ) : aggregation && aggregation.length > 0 ? (
            <AggregationResult rows={aggregation} summary={summary} />
          ) : (
            <>
              <ResultsTable
                results={results}
                totalCount={totalCount}
                sortBy={sortBy}
                sortDir={sortDir}
                onSort={setSort}
                loading={loading}
                hasActiveFilters={conditions.length > 0}
                onClearFilters={clearAll}
                onTryDiscover={() => {
                  const q = conditions
                    .flatMap((c) => c.values || [])
                    .filter(Boolean)
                    .join(' ');
                  navigate(q ? `/discover?q=${encodeURIComponent(q)}` : '/discover');
                }}
                searchLabel={
                  conditions
                    .map((c) => `${c.field}: ${(c.values || []).join(', ')}`)
                    .filter(Boolean)
                    .join(' · ') || undefined
                }
              />

              {totalCount > limit && (
                <Pagination
                  page={page}
                  totalCount={totalCount}
                  limit={limit}
                  onPageChange={setPage}
                />
              )}
            </>
          )}

          <ExecutionTrace provenance={provenance} summary={summary} />
        </div>
      </div>
    </div>
  );
}
