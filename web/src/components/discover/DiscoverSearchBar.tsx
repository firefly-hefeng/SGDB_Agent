import { useEffect, useRef, useState } from 'react';
import { Search, Loader2, X, ChevronDown } from 'lucide-react';
import type { DiscoverySource } from '../../types/discovery';
import { sourceLabel } from '../../lib/format';
import { useT } from '../../lib/i18n';

interface Props {
  query: string;
  setQuery: (q: string) => void;
  sources: DiscoverySource[];
  selectedSources: string[];
  setSelectedSources: (s: string[]) => void;
  maxPerSource: number;
  setMaxPerSource: (n: number) => void;
  synthesize: boolean;
  setSynthesize: (b: boolean) => void;
  onSubmit: () => void;
  onAbort: () => void;
  loading: boolean;
}

const SUGGESTED_QUERIES = [
  'Alzheimer hippocampus scRNA-seq',
  'pancreatic islet 10x',
  'CD8+ T cells lung cancer',
  'mouse embryonic stem cells',
  'kidney organoid single-cell',
  'zebrafish brain atlas',
];

export function DiscoverSearchBar({
  query,
  setQuery,
  sources,
  selectedSources,
  setSelectedSources,
  maxPerSource,
  setMaxPerSource,
  synthesize,
  setSynthesize,
  onSubmit,
  onAbort,
  loading,
}: Props) {
  const { t } = useT();
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!sourcesOpen) return;
    const onDoc = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setSourcesOpen(false);
      }
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [sourcesOpen]);

  const toggleSource = (id: string) => {
    if (selectedSources.includes(id)) {
      setSelectedSources(selectedSources.filter((s) => s !== id));
    } else {
      setSelectedSources([...selectedSources, id]);
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (loading) {
      onAbort();
    } else if (query.trim() && selectedSources.length) {
      onSubmit();
    }
  };

  return (
    <section className="px-6 py-5 border-b border-line bg-white">
      <form onSubmit={handleSubmit} className="max-w-[1100px] mx-auto">
        <div className="flex gap-2 items-center">
          <div className="relative flex-1">
            <Search
              size={16}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-subtle pointer-events-none"
            />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t('discover.bar.placeholder', "Describe the datasets you're looking for — e.g. Alzheimer hippocampus scRNA-seq")}
              className="w-full pl-10 pr-9 py-2.5 text-base bg-white border border-line rounded-md focus:outline-none focus:border-accent focus:ring-2 focus:ring-[var(--accent-bg)] disabled:bg-canvas-subtle"
              autoFocus
            />
            {query && !loading && (
              <button
                type="button"
                onClick={() => setQuery('')}
                aria-label={t('discover.bar.clear.aria', 'Clear query')}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-ink-subtle hover:text-ink"
              >
                <X size={14} />
              </button>
            )}
          </div>

          <div ref={popoverRef} className="relative">
            <button
              type="button"
              onClick={() => setSourcesOpen((v) => !v)}
              className="btn btn-secondary text-sm inline-flex items-center gap-1.5 py-2.5 px-3"
              aria-haspopup="listbox"
              aria-expanded={sourcesOpen}
            >
              {t('discover.bar.sources', 'Sources')}
              <span className="text-ink-subtle">·</span>
              <span className="tabular-nums"><span className="font-medium">{selectedSources.length}</span>/{sources.length}</span>
              <ChevronDown size={13} className={`transition-transform ${sourcesOpen ? 'rotate-180' : ''}`} />
            </button>
            {sourcesOpen && (
              <div className="absolute right-0 mt-1 w-72 bg-white border border-line rounded-md shadow-lg z-30 animate-scale-in p-3">
                <p className="text-2xs uppercase tracking-wide text-ink-subtle mb-2">
                  {t('discover.bar.search_across', 'Search across…')}
                </p>
                <ul className="space-y-1 max-h-72 overflow-y-auto">
                  {sources.map((s) => {
                    const checked = selectedSources.includes(s.id);
                    return (
                      <li key={s.id}>
                        <label className="flex items-start gap-2 px-2 py-1.5 rounded hover:bg-canvas-subtle cursor-pointer">
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() => toggleSource(s.id)}
                            className="mt-0.5 shrink-0"
                          />
                          <span className="min-w-0">
                            <span className="block text-sm font-medium text-ink">{sourceLabel(s.name)}</span>
                            <span className="block text-2xs text-ink-muted line-clamp-2">{s.description}</span>
                          </span>
                        </label>
                      </li>
                    );
                  })}
                </ul>
                <div className="mt-3 pt-2 border-t border-line-subtle flex items-center justify-between text-2xs text-ink-muted">
                  <label className="flex items-center gap-1.5">
                    <input
                      type="checkbox"
                      checked={synthesize}
                      onChange={(e) => setSynthesize(e.target.checked)}
                    />
                    {t('discover.bar.llm_summary', 'LLM summary')}
                  </label>
                  <label className="flex items-center gap-1.5" title={t('discover.bar.per_source.title', 'Max results fetched from each source (1–100)')}>
                    {t('discover.bar.per_source', 'Per source')}
                    <input
                      type="number"
                      min={1}
                      max={100}
                      value={maxPerSource}
                      onChange={(e) => {
                        const n = Number(e.target.value) || 50;
                        setMaxPerSource(Math.min(100, Math.max(1, n)));
                      }}
                      className="w-12 px-1 py-0.5 border border-line rounded text-right"
                    />
                  </label>
                </div>
              </div>
            )}
          </div>

          <button
            type="submit"
            disabled={(!loading && !query.trim()) || selectedSources.length === 0}
            className={`btn ${loading ? 'btn-secondary' : 'btn-accent'} px-5 py-2.5 text-sm shrink-0 min-w-[110px]`}
          >
            {loading ? (
              <>
                <Loader2 size={14} className="animate-spin" /> {t('discover.bar.stop', 'Stop')}
              </>
            ) : (
              <>
                <Search size={14} /> {t('discover.bar.discover', 'Discover')}
              </>
            )}
          </button>
        </div>

        {!loading && !query && (
          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            <span className="text-2xs text-ink-subtle mr-1">{t('discover.bar.try', 'Try:')}</span>
            {SUGGESTED_QUERIES.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setQuery(s)}
                className="text-xs px-2 py-0.5 rounded-full bg-canvas-muted hover:bg-accent-subtle hover:text-accent text-ink-muted transition-colors"
              >
                {s}
              </button>
            ))}
          </div>
        )}
      </form>
    </section>
  );
}
