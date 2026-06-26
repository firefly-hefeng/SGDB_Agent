import { useState, useEffect, useRef } from 'react';
import { ChevronDown, ChevronRight, Search, Microscope, Bug, FlaskConical, Dna, Database, Shapes, Users, SlidersHorizontal, Layers, Tag, TestTube, X } from 'lucide-react';
import type { FacetBucket } from '../../types/api';
import { fmt, sourceLabel, prettyLabel } from '../../lib/format';
import { useT } from '../../lib/i18n';

interface FacetSidebarProps {
  facets: Record<string, FacetBucket[]>;
  activeFilters: Record<string, string[]>;
  onFilterChange: (field: string, values: string[]) => void;
  loading: boolean;
  mobileOpen?: boolean;
  onMobileClose?: () => void;
}

const FACETS = [
  // Standardized (low cardinality — best for browsing)
  { key: 'tissue_system', label: 'Tissue System', labelKey: 'facet.tissue_system', filterKey: 'tissue_systems', icon: Layers },
  { key: 'disease_category', label: 'Disease Category', labelKey: 'facet.disease_category', filterKey: 'disease_categories', icon: Tag },
  { key: 'sample_type', label: 'Sample Type', labelKey: 'facet.sample_type', filterKey: 'sample_types', icon: TestTube },
  // Original (high cardinality)
  { key: 'tissue', label: 'Tissue', labelKey: 'facet.tissue', filterKey: 'tissues', icon: Microscope },
  { key: 'disease', label: 'Disease', labelKey: 'facet.disease', filterKey: 'diseases', icon: Bug },
  { key: 'assay', label: 'Assay', labelKey: 'facet.assay', filterKey: 'assays', icon: FlaskConical },
  { key: 'organism', label: 'Organism', labelKey: 'facet.organism', filterKey: 'organisms', icon: Dna },
  { key: 'source_database', label: 'Database', labelKey: 'facet.database', filterKey: 'source_databases', icon: Database },
  { key: 'cell_type', label: 'Cell Type', labelKey: 'facet.cell_type', filterKey: 'cell_types', icon: Shapes },
  { key: 'sex', label: 'Sex', labelKey: 'facet.sex', filterKey: 'sex', icon: Users },
];


function Group({ label, icon: Icon, buckets, selected, onChange, fmtValue }: {
  label: string; icon: React.ElementType; buckets: FacetBucket[]; selected: string[]; onChange: (v: string[]) => void;
  /** Display-only humanizer for the visible bucket text. The raw ``b.value``
   *  is always kept as the checkbox value / filter key / search target. */
  fmtValue?: (v: string) => string;
}) {
  const { t } = useT();
  const [open, setOpen] = useState(true);
  const [search, setSearch] = useState('');
  const [showAll, setShowAll] = useState(false);

  const filtered = search ? buckets.filter((b) => b.value.toLowerCase().includes(search.toLowerCase())) : buckets;
  const shown = showAll ? filtered : filtered.slice(0, 10);

  const toggle = (v: string) => {
    onChange(selected.includes(v) ? selected.filter((x) => x !== v) : [...selected, v]);
  };

  return (
    <div className="py-3 border-b border-line-subtle">
      <button onClick={() => setOpen(!open)}
        className="flex items-center justify-between w-full text-sm font-medium text-ink hover:text-ink transition-colors">
        <span className="flex items-center gap-1.5">
          <Icon size={13} className="text-ink-subtle" />
          {label}
        </span>
        <span className="flex items-center gap-1.5">
          {selected.length > 0 && (
            <span className="text-2xs font-semibold bg-accent-bg text-accent px-1.5 py-px rounded">{selected.length}</span>
          )}
          {open ? <ChevronDown size={13} className="text-ink-subtle" /> : <ChevronRight size={13} className="text-ink-subtle" />}
        </span>
      </button>
      {open && (
        <div className="mt-2">
          {buckets.length > 8 && (
            <div className="relative mb-2">
              <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-subtle pointer-events-none" />
              <input type="text" value={search} onChange={(e) => setSearch(e.target.value)}
                placeholder={t('facet.filter_ph', 'Filter...')}
                className="w-full pl-7 pr-2 py-1.5 text-xs bg-white border border-line rounded-md focus:outline-none focus:border-accent" />
            </div>
          )}
          <div className="space-y-0 max-h-[240px] overflow-y-auto">
            {shown.map((b) => (
              <label key={b.value}
                className="flex items-center gap-2 text-xs text-ink-muted hover:text-ink cursor-pointer py-[5px] px-1 rounded hover:bg-canvas-subtle transition-colors">
                <input type="checkbox" checked={selected.includes(b.value)} onChange={() => toggle(b.value)}
                  className="rounded border-line-strong text-accent focus:ring-2 focus:ring-accent-bg h-3.5 w-3.5 shrink-0" />
                <span className="flex-1 truncate">{fmtValue ? fmtValue(b.value) : b.value}</span>
                <span className="text-ink-subtle tabular-nums text-2xs shrink-0">{fmt(b.count)}</span>
              </label>
            ))}
            {shown.length === 0 && <p className="text-xs text-ink-subtle py-2 px-1">{t('facet.no_matches', 'No matches')}</p>}
          </div>
          {filtered.length > 10 && (
            <button onClick={() => setShowAll(!showAll)}
              className="text-xs text-accent hover:underline mt-1 px-1">
              {showAll ? t('facet.show_less', 'Show less') : `${t('facet.show_all', 'Show all')} ${filtered.length}`}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export function FacetSidebar({ facets, activeFilters, onFilterChange, loading, mobileOpen, onMobileClose }: FacetSidebarProps) {
  const { t } = useT();
  const totalActive = Object.values(activeFilters).reduce((s, v) => s + (v?.length || 0), 0);

  // a11y: mobile drawer focus management — Escape closes, focus moves into the
  // drawer on open and is restored to the trigger on close.
  const drawerRef = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!mobileOpen) return;
    const prev = document.activeElement as HTMLElement | null;
    drawerRef.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onMobileClose?.(); };
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('keydown', onKey); prev?.focus?.(); };
  }, [mobileOpen, onMobileClose]);

  const resetAll = () => {
    for (const { filterKey } of FACETS) {
      if (activeFilters[filterKey]?.length) onFilterChange(filterKey, []);
    }
  };

  const sidebarContent = (
    <>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-1.5">
          <SlidersHorizontal size={13} className="text-ink-subtle" />
          <span className="section-label">{t('facet.header', 'Filters')}</span>
          {totalActive > 0 && (
            <span className="text-2xs font-semibold bg-accent-bg text-accent px-1.5 py-px rounded">{totalActive}</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {totalActive > 0 && (
            <button onClick={resetAll} className="text-2xs text-accent hover:underline">{t('facet.reset', 'Reset')}</button>
          )}
          {onMobileClose && (
            <button onClick={onMobileClose} className="lg:hidden p-1 text-ink-subtle hover:text-ink-muted" aria-label={t('facet.close_aria', 'Close filters')}>
              <X size={16} />
            </button>
          )}
        </div>
      </div>
      {FACETS.map(({ key, label, labelKey, filterKey, icon }) => {
        const buckets = facets[key] || [];
        if (!buckets.length && !(activeFilters[filterKey]?.length > 0)) return null;
        // Display-only humanizer: source brands get canonical casing; the
        // visibly snake_case enum groups (tissue_system, disease_category,
        // sample_type) get Sentence-case. High-cardinality human groups
        // (tissue, disease, assay, organism, cell_type, sex) render verbatim.
        const fmtValue =
          key === 'source_database' ? sourceLabel
          : (key === 'tissue_system' || key === 'disease_category' || key === 'sample_type') ? prettyLabel
          : undefined;
        return <Group key={key} label={t(labelKey, label)} icon={icon} buckets={buckets}
          selected={activeFilters[filterKey] || []} onChange={(v) => onFilterChange(filterKey, v)} fmtValue={fmtValue} />;
      })}
    </>
  );

  return (
    <>
      {/* Desktop sidebar */}
      <aside className={`hidden lg:block w-[240px] shrink-0 bg-white border-r border-line px-4 py-3 overflow-y-auto transition-opacity ${loading ? 'opacity-50' : ''}`}>
        {sidebarContent}
      </aside>

      {/* Mobile overlay */}
      {mobileOpen && (
        <div className="lg:hidden fixed inset-0 z-50 flex">
          <div className="absolute inset-0 bg-black/30" onClick={onMobileClose} />
          <aside
            ref={drawerRef}
            tabIndex={-1}
            role="dialog"
            aria-modal="true"
            aria-label={t('facet.header', 'Filters')}
            className="relative w-[280px] max-w-[80vw] bg-white px-4 py-3 overflow-y-auto shadow-xl focus:outline-none"
          >
            {sidebarContent}
          </aside>
        </div>
      )}
    </>
  );
}
