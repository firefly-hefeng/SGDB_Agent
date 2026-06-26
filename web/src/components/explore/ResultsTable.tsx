import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowUpDown, ArrowUp, ArrowDown, Radio, RotateCcw, Search, Download } from 'lucide-react';
import { SaveButton } from '../workspace/SaveButton';
import { BulkSaveToWorkspace } from '../workspace/BulkSaveToWorkspace';
import { manifestAdd } from '../../lib/manifest';
import { toast } from '../../lib/toastApi';
import { sourceLabel, prettyLabel } from '../../lib/format';
import { useT } from '../../lib/i18n';
import type { ExploreRecord } from '../../types/api';

interface Props {
  results: ExploreRecord[]; totalCount: number;
  sortBy: string; sortDir: string; onSort: (c: string) => void; loading: boolean;
  onDownloadSelected?: (pks: number[]) => void;
  /** Phase 31.E — empty-state polish.
   *  When the catalogue returns zero rows, surface actionable next steps
   *  rather than a flat "no results" sign. Callers pass the buttons that
   *  make sense in their context. */
  hasActiveFilters?: boolean;
  onClearFilters?: () => void;
  onTryDiscover?: () => void;
  /** Human-readable summary of the current search (e.g. NL query or
   *  joined facet list), used to make the empty-state copy concrete. */
  searchLabel?: string;
}

const COLS = [
  { key: 'sample_id', label: 'Sample ID', labelKey: 'results.col.sample_id', sort: true, mono: true },
  { key: 'organism_common', label: 'Organism', labelKey: 'results.col.organism', sort: true },
  { key: 'tissue', label: 'Tissue', labelKey: 'results.col.tissue', sort: true },
  { key: 'tissue_system', label: 'System', labelKey: 'results.col.system', sort: true },
  { key: 'disease', label: 'Disease', labelKey: 'results.col.disease', sort: true },
  { key: 'disease_category', label: 'Category', labelKey: 'results.col.category', sort: true },
  { key: 'sample_type', label: 'Sample Type', labelKey: 'results.col.sample_type', sort: true },
  { key: 'cell_type', label: 'Cell Type', labelKey: 'results.col.cell_type', sort: false },
  { key: 'assay', label: 'Assay', labelKey: 'results.col.assay', sort: true },
  { key: 'n_cells', label: 'Cells', labelKey: 'results.col.cells', sort: true, right: true },
  { key: 'source_database', label: 'Source', labelKey: 'results.col.source', sort: true },
  { key: 'project_id', label: 'Project', labelKey: 'results.col.project', sort: false, mono: true },
];

const SRC_BADGE: Record<string, string> = {
  geo: 'badge-blue', ncbi: 'badge-green', ebi: 'badge-orange', cellxgene: 'badge-purple',
  hca: 'badge-pink', htan: 'badge-red', panglao: 'badge-teal', scea: 'badge-amber',
  ega: 'badge-indigo', psychad: 'badge-rose', zenodo: 'badge-cyan',
  biscp: 'badge-lime', figshare: 'badge-fuchsia', dryad: 'badge-emerald',
  kpmp: 'badge-sky', mendeley: 'badge-violet', abcatlas: 'badge-yellow',
};

const SAMPLE_TYPE_BADGE: Record<string, string> = {
  primary_tissue: 'bg-emerald-100 text-emerald-700',
  tumor: 'bg-red-100 text-red-700',
  cell_line: 'bg-blue-100 text-blue-700',
  iPSC_derived: 'bg-violet-100 text-violet-700',
  PSC_derived: 'bg-purple-100 text-purple-700',
  organoid: 'bg-amber-100 text-amber-700',
  in_vitro_other: 'bg-cyan-100 text-cyan-700',
  unknown: 'bg-gray-100 text-gray-500',
};

function SortIcon({ col, sortBy, sortDir }: { col: string; sortBy: string; sortDir: string }) {
  if (col !== sortBy) return <ArrowUpDown size={11} className="text-ink-subtle opacity-0 group-hover:opacity-100 transition-opacity" />;
  return sortDir === 'asc' ? <ArrowUp size={11} className="text-accent" /> : <ArrowDown size={11} className="text-accent" />;
}

export function ResultsTable({
  results, sortBy, sortDir, onSort, loading, onDownloadSelected,
  hasActiveFilters, onClearFilters, onTryDiscover, searchLabel,
}: Props) {
  const navigate = useNavigate();
  const { t } = useT();
  const [sel, setSel] = useState<Set<number>>(new Set());

  const fmt = (col: string, row: ExploreRecord): string => {
    const v = row[col as keyof ExploreRecord];
    if (v == null) return '—';
    if (col === 'n_cells' && typeof v === 'number') return v >= 1000 ? `${(v / 1000).toFixed(1)}K` : v.toLocaleString();
    return String(v);
  };

  if (!results.length && !loading) {
    // Context-aware suggestions: if filters are active the user can drop
    // them; if not, point them at Discover (live cross-DB) and at the
    // single-query habits that usually catch zero-result mistakes.
    const trimmedLabel = searchLabel?.trim();
    return (
      <div
        role="status"
        aria-live="polite"
        className="flex flex-col items-center justify-center py-14 text-ink-subtle text-center"
      >
        <img
          src="/singligent/icons/empty-state.svg"
          alt=""
          className="w-[140px] h-[112px] mb-4 opacity-80"
        />
        <p className="text-base font-medium text-ink-muted mb-1">
          {t('results.empty.title', 'No samples match this search')}
        </p>
        {trimmedLabel && (
          <p className="text-xs text-ink-subtle mb-3 max-w-[460px] break-words">
            {t('results.empty.searched', 'Searched:')} <span className="font-mono text-ink-muted">{trimmedLabel}</span>
          </p>
        )}
        <ul className="text-xs text-ink-muted max-w-[480px] mx-auto mb-4 space-y-1 text-left">
          {hasActiveFilters && (
            <li>• {t('results.empty.dropfilter', 'Several filters are active — try removing one (e.g. drop the most specific tissue or cell type).')}</li>
          )}
          <li>• {t('results.empty.broaden', 'Try a broader term — “lung adenocarcinoma” is narrower than “lung cancer”.')}</li>
          <li>• {t('results.empty.spelling', 'Check the spelling and case (ontology labels are case-insensitive but typos won’t match).')}</li>
          <li>• {t('results.empty.coverage', 'The curated catalogue covers GEO/SRA/ArrayExpress + CellxGene/HCA. Live source databases may have more.')}</li>
        </ul>
        <div className="flex flex-wrap items-center justify-center gap-2">
          {hasActiveFilters && onClearFilters && (
            <button
              onClick={onClearFilters}
              type="button"
              className="btn-ghost text-xs inline-flex items-center gap-1 px-2.5 py-1.5"
            >
              <RotateCcw size={12} /> {t('results.empty.clearfilters', 'Clear filters')}
            </button>
          )}
          {onTryDiscover && (
            <button
              onClick={onTryDiscover}
              type="button"
              className="btn btn-accent text-xs inline-flex items-center gap-1 px-3 py-1.5"
            >
              <Radio size={12} /> {t('results.empty.trydiscover', 'Try Discover live')}
            </button>
          )}
          {!onTryDiscover && !onClearFilters && (
            <span className="text-xs inline-flex items-center gap-1 text-ink-subtle">
              <Search size={12} /> {t('results.empty.adjust', 'Adjust filters in the sidebar or refine your query')}
            </span>
          )}
        </div>
      </div>
    );
  }

  if (loading && !results.length) {
    return <div className="space-y-1.5 py-2">{Array.from({ length: 10 }).map((_, i) => <div key={i} className="skeleton h-9 w-full" />)}</div>;
  }

  return (
    <div className={`transition-opacity ${loading ? 'opacity-40' : ''}`}>
      <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="thead-row">
            <th scope="col" className="px-3 py-2.5 w-9 text-left">
              <input type="checkbox"
                aria-label={t('results.selectall.aria', 'Select all rows on this page')}
                checked={sel.size === results.length && results.length > 0}
                onChange={() =>
                  setSel((prev) =>
                    prev.size === results.length
                      ? new Set()
                      : new Set(results.map((r) => r.sample_pk)),
                  )
                }
                className="rounded border-line-strong h-4 w-4" />
            </th>
            {COLS.map((c) => {
              // aria-sort reflects the live sort state on the active column so
              // screen readers can announce ascending/descending/none. Only
              // sortable columns are operable (role=button + keyboard).
              const ariaSort: 'ascending' | 'descending' | 'none' | undefined = !c.sort
                ? undefined
                : c.key !== sortBy
                  ? 'none'
                  : sortDir === 'asc'
                    ? 'ascending'
                    : 'descending';
              return (
                <th key={c.key}
                  scope="col"
                  aria-sort={ariaSort}
                  role={c.sort ? 'button' : undefined}
                  tabIndex={c.sort ? 0 : undefined}
                  className={`px-3 py-2.5 text-left text-2xs font-semibold text-ink-muted uppercase tracking-[0.04em] group select-none ${
                    c.sort ? 'cursor-pointer hover:text-ink focus:outline-none focus:text-ink focus:ring-1 focus:ring-accent rounded-sm' : ''} ${c.right ? 'text-right' : ''}`}
                  onClick={() => c.sort && onSort(c.key)}
                  onKeyDown={(e) => {
                    if (c.sort && (e.key === 'Enter' || e.key === ' ')) {
                      e.preventDefault();
                      onSort(c.key);
                    }
                  }}>
                  <span className="inline-flex items-center gap-1">{t(c.labelKey, c.label)}{c.sort && <SortIcon col={c.key} sortBy={sortBy} sortDir={sortDir} />}</span>
                </th>
              );
            })}
            <th className="px-3 py-2.5 w-9"></th>
          </tr>
        </thead>
        <tbody>
          {results.map((row, i) => (
            <tr key={row.sample_pk}
              tabIndex={0}
              role="link"
              // No aria-label: the visible row content (sample_id, tissue,
              // disease, etc.) becomes the accessible name. An aria-label
              // that omits this text would fail WCAG label-content-name-match.
              className={`border-b border-line-subtle hover:bg-accent-bg/40 cursor-pointer transition-all hover:shadow-[inset_3px_0_0_var(--accent)] focus:outline-none focus:bg-accent-bg/40 focus:shadow-[inset_3px_0_0_var(--accent)] ${i % 2 ? 'bg-canvas-subtle/50' : ''}`}
              onClick={() => navigate(`/explore/${encodeURIComponent(row.project_id || row.sample_id)}`)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  navigate(`/explore/${encodeURIComponent(row.project_id || row.sample_id)}`);
                }
              }}>
              <td className="px-3 py-[7px]" onClick={(e) => e.stopPropagation()}>
                <input type="checkbox" checked={sel.has(row.sample_pk)}
                  aria-label={`${t('results.select.aria', 'Select sample')} ${row.sample_id}`}
                  onChange={() =>
                    setSel((prev) => {
                      const n = new Set(prev);
                      if (n.has(row.sample_pk)) n.delete(row.sample_pk);
                      else n.add(row.sample_pk);
                      return n;
                    })
                  }
                  className="rounded border-line-strong h-4 w-4" />
              </td>
              {COLS.map((c) => (
                <td key={c.key} className={`px-3 py-[7px] truncate max-w-[160px] ${c.mono ? 'font-mono text-xs' : ''} ${c.right ? 'text-right tabular-nums' : ''}`}>
                  {c.key === 'source_database' ? <span className={`badge ${SRC_BADGE[row.source_database] || 'badge-gray'}`}>{sourceLabel(row.source_database)}</span>
                    : c.key === 'sample_id' ? <span className="text-accent">{row.sample_id}</span>
                    : c.key === 'sample_type' && row.sample_type ? (
                      <span className={`text-2xs px-1.5 py-0.5 rounded-full font-medium ${SAMPLE_TYPE_BADGE[row.sample_type] || 'bg-gray-100 text-gray-500'}`}>
                        {prettyLabel(row.sample_type)}
                      </span>
                    )
                    : <span className="text-ink-muted">{fmt(c.key, row)}</span>}
                </td>
              ))}
              <td className="px-2 py-[7px]" onClick={(e) => e.stopPropagation()}>
                <SaveButton target={{
                  item_type: 'sample',
                  item_id: row.sample_id,
                  item_pk: row.sample_pk,
                  source_database: row.source_database,
                  title: row.project_title || row.series_title || null,
                }} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
      {sel.size > 0 && (
        <div className="sticky bottom-0 bg-white border-t border-line px-4 py-2.5 flex items-center gap-3 shadow-md animate-fade-in">
          <span className="text-xs text-ink-muted">{sel.size} {t('results.selected', 'selected')}</span>
          <button
            onClick={() => {
              const pks = Array.from(sel);
              if (onDownloadSelected) {
                onDownloadSelected(pks);
                return;
              }
              // Map selected primary keys back to entity ids the Downloads
              // page actually understands.
              const ids = pks
                .map((pk) => {
                  const r = results.find((x) => x.sample_pk === pk);
                  return r ? (r.project_id || r.sample_id) : '';
                })
                .filter(Boolean);
              navigate(`/downloads?ids=${encodeURIComponent(ids.join(','))}`);
            }}
            className="btn btn-primary text-xs py-1 px-3"
          >
            {t('results.download_selected', 'Download Selected')}
          </button>
          {/* R2-3 — add the selected results to the persistent download
              manifest (the cross-page cart the Downloads page reads). Advanced
              Search previously had no way to file results into the manifest. */}
          <button
            onClick={() => {
              const seen = new Set<string>();
              const entries = Array.from(sel)
                .map((pk) => results.find((x) => x.sample_pk === pk))
                .filter((r): r is ExploreRecord => !!r)
                .map((r) => {
                  // De-dupe to one entry per dataset (project), the unit the
                  // Downloads page resolves; fall back to sample_id.
                  const id = r.project_id || r.sample_id;
                  return {
                    id,
                    source_db: r.source_database,
                    source_url: undefined,
                    download_url: null,
                    file_type: null,
                    size_estimate: null,
                    title: r.project_title || r.series_title || null,
                  };
                })
                .filter((e) => {
                  if (!e.id || seen.has(`${e.source_db}::${e.id}`)) return false;
                  seen.add(`${e.source_db}::${e.id}`);
                  return true;
                });
              const added = manifestAdd(entries);
              toast(
                added
                  ? `${t('results.toast.added_1', 'Added')} ${added} ${added === 1 ? t('results.toast.dataset', 'dataset') : t('results.toast.datasets', 'datasets')} ${t('results.toast.to_manifest', 'to manifest')}`
                  : t('results.toast.already', 'Those datasets are already in the manifest'),
                added ? 'success' : 'info',
              );
            }}
            className="btn-ghost text-xs inline-flex items-center gap-1 px-3 py-1"
          >
            <Download size={12} /> {t('results.add_manifest', 'Add to manifest')}
          </button>
          {/* B2 — bulk path from a result selection straight into a workspace,
              at parity with the per-row star. */}
          <BulkSaveToWorkspace
            items={Array.from(sel)
              .map((pk) => results.find((x) => x.sample_pk === pk))
              .filter((r): r is ExploreRecord => !!r)
              .map((r) => ({
                item_type: 'sample' as const,
                item_id: r.sample_id,
                item_pk: r.sample_pk,
                source_database: r.source_database,
                title: r.project_title || r.series_title || null,
              }))}
          />
          <button onClick={() => setSel(new Set())} className="text-xs text-ink-subtle hover:text-ink-muted">{t('results.clear', 'Clear')}</button>
        </div>
      )}
    </div>
  );
}
