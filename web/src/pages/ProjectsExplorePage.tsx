import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Loader2, ExternalLink, FileText, Search, AlertCircle, SlidersHorizontal, X } from 'lucide-react';
import { searchProjects } from '../services/api';
import { Pagination } from '../components/explore/Pagination';
import { TargetLevelTabs } from '../components/explore/TargetLevelTabs';
import { SaveButton } from '../components/workspace/SaveButton';
import { HowToUse } from '../components/ui/HowToUse';
import { Eyebrow } from '../components/ui/PageHeader';
import { fmt, sourceLabel } from '../lib/format';
import { useT } from '../lib/i18n';
import type { ProjectRecord, ProjectSearchRequest, ProjectSearchResponse } from '../types/api';

const PAGE_SIZE = 25;

interface FilterState {
  q: string;
  sources: string[];
  organisms: string[];
  hasPmid: boolean | null;
  dataAvailability: string | null;
  years: string[];
}

function paramsFromState(s: FilterState, page: number, sort_by: string, sort_dir: string): ProjectSearchRequest {
  return {
    text_search: s.q || undefined,
    source_databases: s.sources.length ? s.sources : undefined,
    organisms: s.organisms.length ? s.organisms : undefined,
    has_pmid: s.hasPmid === null ? undefined : s.hasPmid,
    data_availability: s.dataAvailability || undefined,
    years: s.years.length ? s.years : undefined,
    offset: (page - 1) * PAGE_SIZE,
    limit: PAGE_SIZE,
    sort_by,
    sort_dir,
  };
}


export default function ProjectsExplorePage() {
  const { t } = useT();
  const [params, setParams] = useSearchParams();

  // ── Initial URL → state, computed once on mount ──
  const [state, setState] = useState<FilterState>(() => ({
    q: params.get('q') || '',
    sources: params.get('source_database')?.split(',').filter(Boolean) || [],
    organisms: params.get('organism')?.split(',').filter(Boolean) || [],
    hasPmid:
      params.get('has_pmid') === 'true'
        ? true
        : params.get('has_pmid') === 'false'
          ? false
          : null,
    dataAvailability: params.get('data_availability') || null,
    years: params.get('years')?.split(',').filter(Boolean) || [],
  }));
  const [page, setPage] = useState<number>(parseInt(params.get('page') || '1', 10));
  const [sortBy, setSortBy] = useState<string>(params.get('sort_by') || 'publication_date');
  const [sortDir, setSortDir] = useState<string>(params.get('sort_dir') || 'desc');

  const [data, setData] = useState<ProjectSearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false);

  // Persist filters in URL
  useEffect(() => {
    const next = new URLSearchParams();
    if (state.q) next.set('q', state.q);
    if (state.sources.length) next.set('source_database', state.sources.join(','));
    if (state.organisms.length) next.set('organism', state.organisms.join(','));
    if (state.hasPmid !== null) next.set('has_pmid', String(state.hasPmid));
    if (state.dataAvailability) next.set('data_availability', state.dataAvailability);
    if (state.years.length) next.set('years', state.years.join(','));
    if (page > 1) next.set('page', String(page));
    if (sortBy !== 'publication_date') next.set('sort_by', sortBy);
    if (sortDir !== 'desc') next.set('sort_dir', sortDir);
    setParams(next, { replace: true });
  }, [state, page, sortBy, sortDir, setParams]);

  // Fetch on filter change. The setState calls in the effect body are
  // intentional — we want the skeleton to show *before* the request
  // starts, not after it resolves. The advisory react-hooks rule is
  // pessimistic about cascading renders, but here both setters batch
  // into a single render and Suspense is not yet wired for this view.
  useEffect(() => {
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    setError(null);
    searchProjects(paramsFromState(state, page, sortBy, sortDir))
      .then((r) => { if (!cancelled) setData(r); })
      .catch((e) => { if (!cancelled) setError(String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [state, page, sortBy, sortDir]);

  const updateFilter = <K extends keyof FilterState>(k: K, v: FilterState[K]) => {
    setState((prev) => ({ ...prev, [k]: v }));
    setPage(1);
  };

  const toggleSource = (src: string) => {
    const cur = state.sources;
    updateFilter('sources', cur.includes(src) ? cur.filter((s) => s !== src) : [...cur, src]);
  };

  const toggleYear = (year: string) => {
    const cur = state.years;
    updateFilter('years', cur.includes(year) ? cur.filter((y) => y !== year) : [...cur, year]);
  };

  const sourceFacets = data?.facets?.source_database || [];
  const organismFacets = data?.facets?.organism || [];
  const journalFacets = data?.facets?.journal || [];
  const dataAvailabilityFacets = data?.facets?.data_availability || [];
  const yearFacets = data?.facets?.year || [];

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
        <div className="space-y-1 max-h-60 overflow-y-auto">
          {sourceFacets.map((f) => (
            <label key={f.value} className="flex items-center justify-between py-1 px-2 rounded hover:bg-canvas-subtle cursor-pointer">
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={state.sources.includes(f.value)}
                  onChange={() => toggleSource(f.value)}
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
          {organismFacets.slice(0, 10).map((f) => {
            const active = state.organisms.includes(f.value);
            return (
              <label key={f.value} className="flex items-center justify-between py-1 px-2 rounded hover:bg-canvas-subtle cursor-pointer">
                <div className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={active}
                    onChange={() => updateFilter('organisms',
                      active ? state.organisms.filter((o) => o !== f.value) : [...state.organisms, f.value])}
                    className="rounded"
                  />
                  <span className="text-xs text-ink truncate">{f.value}</span>
                </div>
                <span className="text-2xs text-ink-subtle tabular-nums">{f.count}</span>
              </label>
            );
          })}
        </div>
      </div>

      <div className="mb-4">
        <h3 className="text-xs font-semibold mb-2 text-ink uppercase tracking-wide">{t('facet.has_pmid', 'Has PMID')}</h3>
        <div className="flex gap-1">
          {[
            { v: null, label: t('common.any', 'Any') },
            { v: true, label: t('common.yes', 'Yes') },
            { v: false, label: t('common.no', 'No') },
          ].map((o) => (
            <button
              key={String(o.v)}
              onClick={() => updateFilter('hasPmid', o.v as boolean | null)}
              className={`flex-1 py-1 text-xs rounded border ${
                state.hasPmid === o.v
                  ? 'bg-accent text-white border-accent'
                  : 'border-line text-ink hover:bg-canvas-subtle'
              }`}
            >
              {o.label}
            </button>
          ))}
        </div>
      </div>

      {dataAvailabilityFacets.length > 0 && (
        <div className="mb-4">
          <h3 className="text-xs font-semibold mb-2 text-ink uppercase tracking-wide">{t('facet.data_availability', 'Data availability')}</h3>
          <div className="space-y-1 max-h-40 overflow-y-auto">
            {dataAvailabilityFacets.map((f) => {
              const active = state.dataAvailability === f.value;
              return (
                <label key={f.value} className="flex items-center justify-between py-1 px-2 rounded hover:bg-canvas-subtle cursor-pointer">
                  <div className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={active}
                      onChange={() => updateFilter('dataAvailability', active ? null : f.value)}
                      className="rounded"
                    />
                    <span className="text-xs text-ink truncate capitalize">{f.value}</span>
                  </div>
                  <span className="text-2xs text-ink-subtle tabular-nums">{f.count}</span>
                </label>
              );
            })}
          </div>
        </div>
      )}

      {yearFacets.length > 0 && (
        <div className="mb-4">
          <h3 className="text-xs font-semibold mb-2 text-ink uppercase tracking-wide">{t('facet.year', 'Year published')}</h3>
          <div className="space-y-1 max-h-40 overflow-y-auto">
            {yearFacets.map((f) => {
              const active = state.years.includes(f.value);
              return (
                <label key={f.value} className="flex items-center justify-between py-1 px-2 rounded hover:bg-canvas-subtle cursor-pointer">
                  <div className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={active}
                      onChange={() => toggleYear(f.value)}
                      className="rounded"
                    />
                    <span className="text-xs text-ink truncate">{f.value}</span>
                  </div>
                  <span className="text-2xs text-ink-subtle tabular-nums">{f.count}</span>
                </label>
              );
            })}
          </div>
        </div>
      )}

      {journalFacets.length > 0 && (
        <div className="mb-4">
          <h3 className="text-xs font-semibold mb-2 text-ink uppercase tracking-wide" id="top-journals-label">{t('facet.journals', 'Top journals')}</h3>
          <div
            className="space-y-0.5 max-h-40 overflow-y-auto"
            tabIndex={0}
            role="region"
            aria-labelledby="top-journals-label"
          >
            {journalFacets.slice(0, 8).map((f) => (
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
              <Eyebrow>{t('projects.eyebrow', 'Curated catalog')}</Eyebrow>
              <h1 className="text-2xl font-semibold text-ink leading-tight">{t('projects.title', 'Explore projects')}</h1>
              <p className="text-xs text-ink-muted mt-1 max-w-[60rem]">
                {t('projects.desc',
                  'Browse published studies (full-text search over title / description / organism). Group-level metadata. Use Samples for cell-level filtering.')}
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
                aria-label={t('projects.sort.aria', 'Sort projects')}
                className="text-xs border border-line rounded px-2 py-1 bg-canvas"
              >
                <option value="publication_date|desc">{t('sort.newest', 'Newest first')}</option>
                <option value="publication_date|asc">{t('sort.oldest', 'Oldest first')}</option>
                <option value="citation_count|desc">{t('sort.most_cited', 'Most cited')}</option>
                <option value="sample_count|desc">{t('sort.most_samples', 'Most samples')}</option>
                <option value="total_cells|desc">{t('sort.most_cells', 'Most cells')}</option>
                <option value="title|asc">{t('sort.title_az', 'Title A→Z')}</option>
              </select>
              {loading && <Loader2 size={14} className="animate-spin text-accent" />}
              <span className="text-xs text-ink-subtle tabular-nums">
                {data?.total_count.toLocaleString() ?? 0} {t('projects.count', 'projects')}
              </span>
            </div>
          </div>

          <div className="relative">
            <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-subtle" />
            <input
              type="text"
              value={state.q}
              onChange={(e) => updateFilter('q', e.target.value)}
              placeholder={t('ph.projects.search', 'Search project titles, descriptions, organisms…')}
              aria-label={t('projects.search.aria', 'Search projects')}
              className="w-full pl-8 pr-3 py-2 text-sm border border-line rounded-md bg-canvas focus:outline-none focus:border-accent focus:ring-2 focus:ring-accent-bg"
            />
          </div>
          <HowToUse
            className="mt-2"
            body={t('intro.projects.body',
              'Study-level (group) metadata with full-text search over title, description and organism. Switch to Samples for cell-level filtering.')}
            examples={[
              { label: 'COVID-19 lung', to: '/projects?q=COVID-19 lung' },
              { label: 'GSE149614', to: '/explore/GSE149614', hint: 'jump straight to a project' },
              { label: 'has_pmid sort=Most cited', to: '/projects?has_pmid=true&sort_by=citation_count&sort_dir=desc' },
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
                {t('projects.retry', 'Retry')}
              </button>
            </div>
          )}
          {data && data.results.length === 0 && !loading && !error && (
            <div className="text-center py-16 text-ink-muted">
              <FileText size={28} className="mx-auto mb-2 text-ink-subtle" />
              <p className="text-sm font-medium">{t('projects.empty.title', 'No projects match your filters.')}</p>
              <p className="text-xs text-ink-subtle mt-1">
                {t('projects.empty.hint', 'Try widening the source or organism filters, or clearing the search box.')}
              </p>
            </div>
          )}
          {data?.results.map((p) => <ProjectCard key={p.project_pk} project={p} />)}
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

function ProjectCard({ project }: { project: ProjectRecord }) {
  const { t } = useT();
  return (
    <article className="border-b border-line py-3 hover:bg-canvas-subtle/30 transition-colors -mx-5 px-5">
      <div className="flex items-start justify-between gap-3 mb-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="px-1.5 py-0.5 text-2xs font-medium rounded bg-canvas-muted text-ink">
            {sourceLabel(project.source_database)}
          </span>
          <Link
            to={`/explore/${encodeURIComponent(project.project_id)}`}
            className="text-sm font-mono text-accent hover:underline"
          >
            {project.project_id}
          </Link>
          {project.organism && (
            <span className="text-2xs text-ink-muted italic">{project.organism}</span>
          )}
          {project.publication_date && (
            <span className="text-2xs text-ink-subtle">
              {project.publication_date.slice(0, 10)}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3 shrink-0 text-2xs text-ink-muted tabular-nums">
          {project.sample_count != null && <span>{fmt(project.sample_count)} {t('common.samples', 'samples')}</span>}
          {project.total_cells != null && <span>{fmt(project.total_cells)} {t('common.cells', 'cells')}</span>}
          {project.citation_count != null && project.citation_count > 0 && (
            <span>{project.citation_count} {t('common.citations', 'citations')}</span>
          )}
          <SaveButton
            target={{
              item_type: 'project',
              item_id: project.project_id,
              item_pk: project.project_pk,
              source_database: project.source_database,
              title: project.title,
            }}
          />
        </div>
      </div>
      {project.title && (
        <h3 className="text-sm font-medium text-ink leading-snug mb-1 line-clamp-2">
          {project.title}
        </h3>
      )}
      {project.description && (
        <p className="text-xs text-ink-muted leading-snug line-clamp-2">
          {project.description}
        </p>
      )}
      <div className="flex items-center gap-3 mt-2 text-2xs text-ink-muted">
        {project.journal && <span className="italic">{project.journal}</span>}
        {project.pmid && (
          <a
            href={`https://pubmed.ncbi.nlm.nih.gov/${project.pmid}/`}
            target="_blank" rel="noreferrer"
            className="hover:text-accent inline-flex items-center gap-0.5"
          >
            PMID:{project.pmid}<ExternalLink size={10} />
          </a>
        )}
        {project.doi && (
          <a
            href={`https://doi.org/${project.doi}`}
            target="_blank" rel="noreferrer"
            className="hover:text-accent inline-flex items-center gap-0.5"
          >
            DOI<ExternalLink size={10} />
          </a>
        )}
        {project.access_url && (
          <a
            href={project.access_url}
            target="_blank" rel="noreferrer"
            className="hover:text-accent inline-flex items-center gap-0.5"
          >
            {t('common.source', 'Source')}<ExternalLink size={10} />
          </a>
        )}
      </div>
    </article>
  );
}
