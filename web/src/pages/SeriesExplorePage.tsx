import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Loader2, ExternalLink, FileText, Search, Database, AlertCircle, SlidersHorizontal, X } from 'lucide-react';
import { searchSeries } from '../services/api';
import { Pagination } from '../components/explore/Pagination';
import { TargetLevelTabs } from '../components/explore/TargetLevelTabs';
import { SaveButton } from '../components/workspace/SaveButton';
import { HowToUse } from '../components/ui/HowToUse';
import { Eyebrow } from '../components/ui/PageHeader';
import { useT } from '../lib/i18n';
import { fmt, sourceLabel } from '../lib/format';
import type { SeriesRecord, SeriesSearchRequest, SeriesSearchResponse } from '../types/api';

const PAGE_SIZE = 25;

interface FilterState {
  q: string;
  sources: string[];
  organisms: string[];
  assays: string[];
  assayModalities: string[];
  hasH5ad: boolean | null;
  hasRds: boolean | null;
}

function paramsFromState(s: FilterState, page: number, sort_by: string, sort_dir: string): SeriesSearchRequest {
  return {
    text_search: s.q || undefined,
    source_databases: s.sources.length ? s.sources : undefined,
    organisms: s.organisms.length ? s.organisms : undefined,
    assays: s.assays.length ? s.assays : undefined,
    assay_modalities: s.assayModalities.length ? s.assayModalities : undefined,
    has_h5ad: s.hasH5ad === null ? undefined : s.hasH5ad,
    has_rds: s.hasRds === null ? undefined : s.hasRds,
    offset: (page - 1) * PAGE_SIZE,
    limit: PAGE_SIZE,
    sort_by,
    sort_dir,
  };
}

export default function SeriesExplorePage() {
  const { t } = useT();
  const [params, setParams] = useSearchParams();

  const [state, setState] = useState<FilterState>(() => ({
    q: params.get('q') || '',
    sources: params.get('source_database')?.split(',').filter(Boolean) || [],
    organisms: params.get('organism')?.split(',').filter(Boolean) || [],
    assays: params.get('assay')?.split(',').filter(Boolean) || [],
    assayModalities: params.get('assay_modality')?.split(',').filter(Boolean) || [],
    hasH5ad:
      params.get('has_h5ad') === 'true'
        ? true
        : params.get('has_h5ad') === 'false'
          ? false
          : null,
    hasRds:
      params.get('has_rds') === 'true'
        ? true
        : params.get('has_rds') === 'false'
          ? false
          : null,
  }));
  const [page, setPage] = useState<number>(parseInt(params.get('page') || '1', 10));
  const [sortBy, setSortBy] = useState<string>(params.get('sort_by') || 'cell_count');
  const [sortDir, setSortDir] = useState<string>(params.get('sort_dir') || 'desc');

  const [data, setData] = useState<SeriesSearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false);

  // Persist filters in URL
  useEffect(() => {
    const next = new URLSearchParams();
    if (state.q) next.set('q', state.q);
    if (state.sources.length) next.set('source_database', state.sources.join(','));
    if (state.organisms.length) next.set('organism', state.organisms.join(','));
    if (state.assays.length) next.set('assay', state.assays.join(','));
    if (state.assayModalities.length) next.set('assay_modality', state.assayModalities.join(','));
    if (state.hasH5ad !== null) next.set('has_h5ad', String(state.hasH5ad));
    if (state.hasRds !== null) next.set('has_rds', String(state.hasRds));
    if (page > 1) next.set('page', String(page));
    if (sortBy !== 'cell_count') next.set('sort_by', sortBy);
    if (sortDir !== 'desc') next.set('sort_dir', sortDir);
    setParams(next, { replace: true });
  }, [state, page, sortBy, sortDir, setParams]);

  // Fetch on filter change
  // See ProjectsExplorePage for why the setState-in-effect is intentional.
  useEffect(() => {
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    setError(null);
    searchSeries(paramsFromState(state, page, sortBy, sortDir))
      .then((r) => { if (!cancelled) setData(r); })
      .catch((e) => { if (!cancelled) setError(String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [state, page, sortBy, sortDir]);

  const updateFilter = <K extends keyof FilterState>(k: K, v: FilterState[K]) => {
    setState((prev) => ({ ...prev, [k]: v }));
    setPage(1);
  };

  const toggle = (k: 'sources' | 'organisms' | 'assays' | 'assayModalities', v: string) => {
    const cur = state[k];
    updateFilter(k, cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v]);
  };

  // "Data format" maps a single selection onto the existing has_h5ad / has_rds
  // booleans: h5ad → has_h5ad=true, rds → has_rds=true, raw/links only → clear both.
  const dataFormatValue: string | null =
    state.hasH5ad === true ? 'h5ad' : state.hasRds === true ? 'rds' : null;
  const setDataFormat = (fmt: string | null) => {
    setState((prev) => ({
      ...prev,
      hasH5ad: fmt === 'h5ad' ? true : null,
      hasRds: fmt === 'rds' ? true : null,
    }));
    setPage(1);
  };

  const sourceFacets = data?.facets?.source_database || [];
  const organismFacets = data?.facets?.organism || [];
  const assayFacets = data?.facets?.assay || [];
  const assayModalityFacets = data?.facets?.assay_modality || [];
  const dataFormatFacets = data?.facets?.data_format || [];
  const platformFacets = data?.facets?.platform || [];

  const sidebarContent = (
    <>
      <div className="flex items-center justify-between mb-4 lg:hidden">
        <span className="section-label">{t('facet.header', 'Filters')}</span>
        <button
          onClick={() => setMobileFiltersOpen(false)}
          className="p-1 text-ink-subtle hover:text-ink-muted"
          aria-label={t('facet.close_aria', 'Close filters')}
        >
          <X size={16} />
        </button>
      </div>

      <div className="mb-4">
        <h2 className="text-sm font-semibold mb-2 text-ink">{t('tabs.targetlevel', 'Target level')}</h2>
        <TargetLevelTabs />
      </div>

      <div className="mb-4">
        <h3 className="text-xs font-semibold mb-2 text-ink uppercase tracking-wide">{t('facet.source', 'Source')}</h3>
        <div className="space-y-1 max-h-48 overflow-y-auto">
          {sourceFacets.map((f) => (
            <label key={f.value} className="flex items-center justify-between py-1 px-2 rounded hover:bg-canvas-subtle cursor-pointer">
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={state.sources.includes(f.value)}
                  onChange={() => toggle('sources', f.value)}
                  className="rounded"
                />
                <span className="text-xs text-ink">{f.value}</span>
              </div>
              <span className="text-2xs text-ink-subtle tabular-nums">{f.count}</span>
            </label>
          ))}
        </div>
      </div>

      <div className="mb-4">
        <h3 className="text-xs font-semibold mb-2 text-ink uppercase tracking-wide">{t('facet.organism', 'Organism')}</h3>
        <div className="space-y-1 max-h-40 overflow-y-auto">
          {organismFacets.slice(0, 10).map((f) => (
            <label key={f.value} className="flex items-center justify-between py-1 px-2 rounded hover:bg-canvas-subtle cursor-pointer">
              <div className="flex items-center gap-2">
                <input type="checkbox"
                  checked={state.organisms.includes(f.value)}
                  onChange={() => toggle('organisms', f.value)}
                  className="rounded" />
                <span className="text-xs text-ink truncate">{f.value}</span>
              </div>
              <span className="text-2xs text-ink-subtle tabular-nums">{f.count}</span>
            </label>
          ))}
        </div>
      </div>

      <div className="mb-4">
        <h3 className="text-xs font-semibold mb-2 text-ink uppercase tracking-wide">{t('facet.assay', 'Assay')}</h3>
        <div className="space-y-1 max-h-48 overflow-y-auto">
          {assayFacets.slice(0, 12).map((f) => (
            <label key={f.value} className="flex items-center justify-between py-1 px-2 rounded hover:bg-canvas-subtle cursor-pointer">
              <div className="flex items-center gap-2">
                <input type="checkbox"
                  checked={state.assays.includes(f.value)}
                  onChange={() => toggle('assays', f.value)}
                  className="rounded" />
                <span className="text-xs text-ink truncate" title={f.value}>{f.value}</span>
              </div>
              <span className="text-2xs text-ink-subtle tabular-nums">{f.count}</span>
            </label>
          ))}
        </div>
      </div>

      {assayModalityFacets.length > 0 && (
        <div className="mb-4">
          <h3 className="text-xs font-semibold mb-2 text-ink uppercase tracking-wide">{t('facet.assay_modality', 'Assay modality')}</h3>
          <div className="space-y-1 max-h-40 overflow-y-auto">
            {assayModalityFacets.map((f) => (
              <label key={f.value} className="flex items-center justify-between py-1 px-2 rounded hover:bg-canvas-subtle cursor-pointer">
                <div className="flex items-center gap-2">
                  <input type="checkbox"
                    checked={state.assayModalities.includes(f.value)}
                    onChange={() => toggle('assayModalities', f.value)}
                    className="rounded" />
                  <span className="text-xs text-ink truncate" title={f.value}>{f.value}</span>
                </div>
                <span className="text-2xs text-ink-subtle tabular-nums">{f.count}</span>
              </label>
            ))}
          </div>
        </div>
      )}

      {dataFormatFacets.length > 0 && (
        <div className="mb-4">
          <h3 className="text-xs font-semibold mb-2 text-ink uppercase tracking-wide">{t('facet.data_format', 'Data format')}</h3>
          <div className="space-y-1 max-h-40 overflow-y-auto">
            {dataFormatFacets.map((f) => {
              // "raw/links only" → no boolean filter; h5ad/rds → their boolean.
              const selectValue = f.value === 'h5ad' ? 'h5ad' : f.value === 'rds' ? 'rds' : null;
              const active =
                selectValue === null
                  ? dataFormatValue === null
                  : dataFormatValue === selectValue;
              return (
                <label key={f.value} className="flex items-center justify-between py-1 px-2 rounded hover:bg-canvas-subtle cursor-pointer">
                  <div className="flex items-center gap-2">
                    <input type="checkbox"
                      checked={active}
                      onChange={() => setDataFormat(active ? null : selectValue)}
                      className="rounded" />
                    <span className="text-xs text-ink truncate" title={f.value}>{f.value}</span>
                  </div>
                  <span className="text-2xs text-ink-subtle tabular-nums">{f.count}</span>
                </label>
              );
            })}
          </div>
        </div>
      )}

      <div className="mb-4">
        <h3 className="text-xs font-semibold mb-2 text-ink uppercase tracking-wide">{t('facet.h5ad', 'h5ad available')}</h3>
        <div className="flex gap-1">
          {[
            { v: null, label: t('common.any', 'Any') },
            { v: true, label: t('common.yes', 'Yes') },
            { v: false, label: t('common.no', 'No') },
          ].map((o) => (
            <button
              key={String(o.v)}
              onClick={() => updateFilter('hasH5ad', o.v as boolean | null)}
              className={`flex-1 py-1 text-xs rounded border ${
                state.hasH5ad === o.v
                  ? 'bg-accent text-white border-accent'
                  : 'border-line text-ink hover:bg-canvas-subtle'
              }`}
            >
              {o.label}
            </button>
          ))}
        </div>
      </div>

      {platformFacets.length > 0 && (
        <div className="mb-4">
          <h3 className="text-xs font-semibold mb-2 text-ink uppercase tracking-wide">{t('series.top_platforms', 'Top platforms')}</h3>
          <div className="space-y-0.5 max-h-32 overflow-y-auto">
            {platformFacets.slice(0, 6).map((f) => (
              <div key={f.value} className="flex items-center justify-between py-0.5 text-2xs">
                <span className="text-ink-muted truncate" title={f.value}>{f.value}</span>
                <span className="text-ink-subtle tabular-nums shrink-0 ml-2">{f.count}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );

  return (
    <div className="flex flex-1 min-h-0">
      {/* Desktop sidebar */}
      <aside className="hidden lg:block w-[260px] shrink-0 overflow-y-auto border-r border-line bg-canvas p-4">
        {sidebarContent}
      </aside>

      {/* Mobile filter drawer */}
      {mobileFiltersOpen && (
        <div className="lg:hidden fixed inset-0 z-50 flex">
          <div className="absolute inset-0 bg-black/30" onClick={() => setMobileFiltersOpen(false)} />
          <aside className="relative w-[280px] max-w-[80vw] overflow-y-auto bg-canvas p-4 shadow-xl">
            {sidebarContent}
          </aside>
        </div>
      )}

      {/* Main */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden bg-canvas">
        <header className="page-header-band px-5 pt-4 pb-3 bg-canvas">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between sm:gap-3 mb-3">
            <div className="min-w-0">
              <Eyebrow>{t('series.eyebrow', 'Curated catalog')}</Eyebrow>
              <h1 className="text-2xl font-semibold text-ink leading-tight">{t('series.title', 'Explore series')}</h1>
              <p className="text-xs text-ink-muted mt-1 max-w-[60rem]">
                {t('series.desc',
                  'Browse individual sequencing series. Assay-level metadata, with file availability badges and download URLs where catalogued.')}
              </p>
            </div>
            <div className="flex items-center gap-2 shrink-0 flex-wrap sm:flex-nowrap sm:justify-end">
              <button
                onClick={() => setMobileFiltersOpen(true)}
                className="lg:hidden btn-ghost text-xs inline-flex items-center gap-1 px-2 py-1"
                title={t('explore.show_filters', 'Show filters')}
                aria-label={t('explore.show_filters', 'Show filters')}
              >
                <SlidersHorizontal size={13} /> {t('explore.filters', 'Filters')}
              </button>
              <select
                value={`${sortBy}|${sortDir}`}
                onChange={(e) => {
                  const [b, d] = e.target.value.split('|');
                  setSortBy(b);
                  setSortDir(d);
                }}
                aria-label={t('series.sort.aria', 'Sort series')}
                className="text-xs border border-line rounded px-2 py-1 bg-canvas"
              >
                <option value="cell_count|desc">{t('sort.most_cells', 'Most cells')}</option>
                <option value="sample_count|desc">{t('sort.most_samples', 'Most samples')}</option>
                <option value="published_at|desc">{t('sort.newest', 'Newest first')}</option>
                <option value="published_at|asc">{t('sort.oldest', 'Oldest first')}</option>
                <option value="citation_count|desc">{t('sort.most_cited', 'Most cited')}</option>
                <option value="title|asc">{t('sort.title_az', 'Title A→Z')}</option>
              </select>
              {loading && <Loader2 size={14} className="animate-spin text-accent" />}
              <span className="text-xs text-ink-subtle tabular-nums">
                {data?.total_count.toLocaleString() ?? 0} {t('series.count', 'series')}
              </span>
            </div>
          </div>

          <div className="relative">
            <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-subtle" />
            <input
              type="text"
              value={state.q}
              onChange={(e) => updateFilter('q', e.target.value)}
              placeholder={t('ph.series.search', 'Search series titles, assays, platforms…')}
              aria-label={t('series.search.aria', 'Search series')}
              className="w-full pl-8 pr-3 py-2 text-sm border border-line rounded-md bg-canvas focus:outline-none focus:border-accent focus:ring-2 focus:ring-accent-bg"
            />
          </div>
          <HowToUse
            className="mt-2"
            body={t('intro.series.body',
              'Individual sequencing series — assay-level metadata with file-availability badges (h5ad / rds) and download URLs where catalogued.')}
            examples={[
              { label: 'has_h5ad sort=Most cells', to: '/series?has_h5ad=true&sort_by=cell_count&sort_dir=desc', hint: 'biggest downloadable atlases' },
              { label: 'assay=10x 3\' v3', to: '/series?assay=10x 3\' v3' },
              { label: 'brain Alzheimer', to: '/series?q=brain Alzheimer' },
            ]}
          />
        </header>

        <div className="flex-1 overflow-y-auto px-5 py-2">
          {error && (
            <div
              role="alert"
              className="flex items-start gap-2 text-sm text-[var(--error)] bg-[color-mix(in_srgb,var(--error)_8%,white)] border border-[color-mix(in_srgb,var(--error)_25%,white)] rounded-md px-3 py-2 my-3"
            >
              <AlertCircle size={14} className="mt-0.5 shrink-0" />
              <span className="flex-1">{error}</span>
              <button
                onClick={() => setState((s) => ({ ...s }))}
                className="text-xs text-accent hover:underline shrink-0"
              >
                {t('series.retry', 'Retry')}
              </button>
            </div>
          )}
          {data && data.results.length === 0 && !loading && !error && (
            <div className="text-center py-16 text-ink-muted">
              <FileText size={28} className="mx-auto mb-2 text-ink-subtle" />
              <p className="text-sm font-medium">{t('series.empty.title', 'No series match your filters.')}</p>
              <p className="text-xs text-ink-subtle mt-1">
                {t('series.empty.hint', 'Try widening the source / organism / assay filters.')}
              </p>
            </div>
          )}
          {data?.results.map((s) => <SeriesCard key={s.series_pk} series={s} />)}
        </div>

        <div className="px-5 border-t border-line">
          <Pagination
            page={page}
            totalCount={data?.total_count ?? 0}
            limit={PAGE_SIZE}
            onPageChange={setPage}
          />
        </div>
      </div>
    </div>
  );
}

function SeriesCard({ series }: { series: SeriesRecord }) {
  const { t } = useT();
  return (
    <article className="border-b border-line py-3 hover:bg-canvas-subtle/30 transition-colors -mx-5 px-5">
      <div className="flex items-start justify-between gap-3 mb-1">
        <div className="flex items-center gap-2 flex-wrap min-w-0">
          <span className="px-1.5 py-0.5 text-2xs font-medium rounded bg-canvas-muted text-ink">
            {sourceLabel(series.source_database)}
          </span>
          <Link
            to={`/explore/${encodeURIComponent(series.series_id)}`}
            className="text-sm font-mono text-accent hover:underline"
          >
            {series.series_id}
          </Link>
          {series.organism && (
            <span className="text-2xs text-ink-muted italic">{series.organism}</span>
          )}
          {series.published_at && (
            <span className="text-2xs text-ink-subtle">
              {series.published_at.slice(0, 10)}
            </span>
          )}
          {series.has_h5ad && (
            <span className="badge badge-emerald inline-flex items-center gap-0.5">
              <Database size={10} /> h5ad
            </span>
          )}
        </div>
        <div className="flex items-center gap-3 shrink-0 text-2xs text-ink-muted tabular-nums">
          {series.cell_count != null && <span>{fmt(series.cell_count)} {t('common.cells', 'cells')}</span>}
          {series.sample_count != null && <span>{fmt(series.sample_count)} {t('common.samples', 'samples')}</span>}
          {series.citation_count != null && series.citation_count > 0 && (
            <span>{series.citation_count} {t('common.citations', 'citations')}</span>
          )}
          <SaveButton target={{
            item_type: 'series',
            item_id: series.series_id,
            item_pk: series.series_pk,
            source_database: series.source_database,
            title: series.title,
          }} />
        </div>
      </div>
      {series.title && (
        <h3 className="text-sm font-medium text-ink leading-snug mb-1 line-clamp-2">
          {series.title}
        </h3>
      )}
      <div className="flex items-center gap-3 mt-1 text-2xs text-ink-muted">
        {series.assay && <span>{series.assay}</span>}
        {series.platform && <span className="text-ink-subtle">{series.platform}</span>}
        {series.asset_h5ad_url && (
          <a
            href={series.asset_h5ad_url}
            target="_blank" rel="noreferrer"
            className="hover:text-accent inline-flex items-center gap-0.5"
          >
            h5ad<ExternalLink size={10} />
          </a>
        )}
        {series.asset_rds_url && (
          <a
            href={series.asset_rds_url}
            target="_blank" rel="noreferrer"
            className="hover:text-accent inline-flex items-center gap-0.5"
          >
            rds<ExternalLink size={10} />
          </a>
        )}
        {series.project_id && (
          <Link
            to={`/projects?source_database=${encodeURIComponent(series.source_database)}`}
            className="hover:text-accent"
          >
            {t('series.project_label', 'project:')} {series.project_id}
          </Link>
        )}
      </div>
    </article>
  );
}
