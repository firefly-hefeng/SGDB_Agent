import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Radio, Info, Sparkles, ChevronDown } from 'lucide-react';
import { DiscoverSearchBar } from '../components/discover/DiscoverSearchBar';
import { DiscoverIntentChips } from '../components/discover/DiscoverIntentChips';
import { DiscoverSourceTabs } from '../components/discover/DiscoverSourceTabs';
import { DiscoverSourceSection } from '../components/discover/DiscoverSourceSection';
import { MarkdownView } from '../components/discover/MarkdownView';
import { useDiscoverStream } from '../hooks/useDiscoverStream';
import { listDiscoverySources } from '../services/discovery';
import type { DiscoverySource } from '../types/discovery';
import { fmtMs } from '../lib/format';
import { HowToUse } from '../components/ui/HowToUse';
import { Eyebrow } from '../components/ui/PageHeader';
import { useT } from '../lib/i18n';

/**
 * Live cross-database discovery — the replacement for the iframe-based
 * Cross-API Live page. Native React, same-origin SSE, fully integrated
 * with the global manifest.
 */
export default function DiscoverPage() {
  const { t } = useT();
  const [searchParams, setSearchParams] = useSearchParams();
  const [query, setQuery] = useState(searchParams.get('q') ?? '');
  const [sources, setSources] = useState<DiscoverySource[]>([]);
  const [selectedSources, setSelectedSources] = useState<string[]>([]);
  const [maxPerSource, setMaxPerSource] = useState<number>(50);
  const [synthesize, setSynthesize] = useState<boolean>(true);
  const [activeTab, setActiveTab] = useState<string>('all');
  const [showIntentJson, setShowIntentJson] = useState(false);

  const stream = useDiscoverStream();

  // Load source catalogue once.
  useEffect(() => {
    listDiscoverySources()
      .then((r) => {
        setSources(r.sources);
        setSelectedSources((prev) => (prev.length ? prev : r.default_selection));
      })
      .catch(() => {
        // Hard-coded fallback if /sources is unreachable.
        const fallback: DiscoverySource[] = [
          { id: 'geo', name: 'GEO', full_name: 'Gene Expression Omnibus', description: '', host: 'ncbi.nlm.nih.gov' },
          { id: 'ebi', name: 'EBI', full_name: 'EBI BioStudies', description: '', host: 'ebi.ac.uk' },
          { id: 'scea', name: 'SCEA', full_name: 'EBI Single-Cell Expression Atlas', description: '', host: 'ebi.ac.uk' },
          { id: 'cellxgene', name: 'CellxGene', full_name: 'CellxGene Discover', description: '', host: 'cellxgene.cziscience.com' },
          { id: 'hca', name: 'HCA', full_name: 'Human Cell Atlas', description: '', host: 'data.humancellatlas.org' },
          { id: 'sra', name: 'SRA', full_name: 'Sequence Read Archive', description: '', host: 'ncbi.nlm.nih.gov' },
        ];
        setSources(fallback);
        if (!selectedSources.length) setSelectedSources(['geo', 'ebi', 'scea', 'cellxgene', 'hca']);
      });
    // Once on mount; no dep on selectedSources.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // If the URL ?q= is present and we have sources loaded, auto-run.
  useEffect(() => {
    const q = searchParams.get('q');
    if (q && q.trim() && sources.length && selectedSources.length && stream.status === 'idle') {
      stream.start({
        query: q.trim(),
        options: {
          sources: selectedSources,
          synthesize,
          max_results_per_source: maxPerSource,
        },
      });
    }
    // We only auto-run on initial query, not on subsequent edits.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sources.length]);

  const onSubmit = useCallback(() => {
    const q = query.trim();
    if (!q) return;
    setSearchParams((sp) => {
      sp.set('q', q);
      return sp;
    });
    stream.reset();
    setActiveTab('all');
    setTimeout(() => {
      stream.start({
        query: q,
        options: {
          sources: selectedSources,
          synthesize,
          max_results_per_source: maxPerSource,
        },
      });
    }, 0);
  }, [query, selectedSources, synthesize, maxPerSource, setSearchParams, stream]);

  const onAbort = useCallback(() => {
    stream.abort();
  }, [stream]);

  const pendingSources = useMemo(
    () => (stream.status === 'streaming' ? Math.max(0, selectedSources.length - stream.sources.length) : 0),
    [stream.status, stream.sources.length, selectedSources.length],
  );

  const visibleSections = useMemo(
    () =>
      activeTab === 'all'
        ? stream.sources
        : stream.sources.filter((s) => s.source === activeTab),
    [stream.sources, activeTab],
  );

  return (
    <div className="flex-1 overflow-y-auto bg-canvas">
      {/* Page header */}
      <header className="page-header-band px-6 pt-6 pb-3 bg-canvas">
        <div className="max-w-[1280px] mx-auto">
          <div className="flex items-start justify-between gap-3">
            <div>
              <Eyebrow icon={<Radio size={12} className="text-accent" />}>
                {t('discover.eyebrow', 'Live cross-database')}
              </Eyebrow>
              <h1 className="text-2xl font-semibold tracking-[-0.01em] text-ink">
                {t('discover.title', 'Discover datasets across public scRNA-seq archives')}
              </h1>
              <p className="text-sm text-ink-muted mt-1 max-w-[60rem]">
                {t('discover.sub',
                  'One natural-language query, up to six public databases — GEO, EBI BioStudies, EBI Single-Cell Atlas, CellxGene, HCA (and SRA on demand) — queried in parallel with mirror detection and cross-source dedup.')}
              </p>
              <HowToUse
                className="mt-3 max-w-[60rem]"
                body={t('intro.discover.body',
                  'Live federation across up to six public archives (GEO, EBI BioStudies, SCEA, CellxGene, HCA by default; SRA on demand) with mirror detection and cross-source dedup. Use this for the newest submissions or sources not yet in the curated catalog (SRA, SCEA).')}
                examples={[
                  { label: 'pancreatic islet diabetes single-cell', onPick: () => setQuery('pancreatic islet diabetes single-cell') },
                  { label: 'Alzheimer hippocampus scRNA-seq', onPick: () => setQuery('Alzheimer hippocampus scRNA-seq') },
                  { label: 'tumor-infiltrating T cells lung cancer', onPick: () => setQuery('tumor-infiltrating T cells lung cancer') },
                ]}
              />
            </div>
          </div>
        </div>
      </header>

      <DiscoverSearchBar
        query={query}
        setQuery={setQuery}
        sources={sources}
        selectedSources={selectedSources}
        setSelectedSources={setSelectedSources}
        maxPerSource={maxPerSource}
        setMaxPerSource={setMaxPerSource}
        synthesize={synthesize}
        setSynthesize={setSynthesize}
        onSubmit={onSubmit}
        onAbort={onAbort}
        loading={stream.status === 'streaming'}
      />

      {/* Status strip */}
      {stream.status !== 'idle' && (
        <section className="px-6 py-3 bg-white border-b border-line">
          <div className="max-w-[1280px] mx-auto space-y-2">
            <div className="flex items-center gap-3 text-xs flex-wrap">
              {stream.status === 'streaming' && (
                <span className="inline-flex items-center gap-1.5 text-accent">
                  <span className="w-1.5 h-1.5 bg-accent rounded-full animate-pulse" />
                  {t('discover.searching', 'Searching…')} {stream.sources.length}/{selectedSources.length} {t('discover.done_count', 'done')}
                </span>
              )}
              {stream.status === 'done' && (
                <span className="text-[var(--success)]">
                  ✓ {stream.totalFound.toLocaleString()} {t('discover.hits_across_1', 'hits across')} {stream.sources.length} {t('discover.hits_across_2', 'sources')}
                  · {fmtMs(stream.totalLatencyMs)}
                </span>
              )}
              {stream.status === 'error' && stream.error && (
                <div className="flex items-center gap-2 flex-wrap" role="alert">
                  <span className="text-[var(--error)]">{stream.error}</span>
                  <button
                    onClick={onSubmit}
                    className="btn-ghost text-xs px-2 py-0.5 text-accent hover:underline"
                  >
                    {t('discover.retry', 'Retry')}
                  </button>
                </div>
              )}
            </div>
            <DiscoverIntentChips intent={stream.intent} />
            {stream.intent && (
              <details
                open={showIntentJson}
                onToggle={(e) => setShowIntentJson((e.target as HTMLDetailsElement).open)}
                className="text-2xs"
              >
                <summary className="cursor-pointer text-ink-subtle hover:text-ink-muted inline-flex items-center gap-1">
                  <ChevronDown
                    size={11}
                    className={`transition-transform ${showIntentJson ? '' : '-rotate-90'}`}
                  />
                  {t('discover.intent_json', 'Parsed intent JSON')}
                </summary>
                <pre className="mt-1 code-block text-2xs">
                  {JSON.stringify(stream.intent, null, 2)}
                </pre>
              </details>
            )}
          </div>
        </section>
      )}

      {/* Tabs + results */}
      {(stream.status === 'streaming' || stream.status === 'done') && stream.sources.length > 0 && (
        <section className="px-6 py-4">
          <div className="max-w-[1280px] mx-auto space-y-3">
            <DiscoverSourceTabs
              sources={sources}
              results={stream.sources}
              activeTab={activeTab}
              setActiveTab={setActiveTab}
              totalFound={stream.totalFound}
              pendingSources={pendingSources}
            />
            <div className="space-y-3">
              {visibleSections.map((r) => (
                <DiscoverSourceSection key={r.source} result={r} />
              ))}
            </div>

            {/* Live skeletons for pending sources */}
            {stream.status === 'streaming' &&
              activeTab === 'all' &&
              selectedSources
                .filter((id) => !stream.sources.some((s) => s.source === id))
                .map((id) => (
                  <div
                    key={`skeleton-${id}`}
                    className="border border-line rounded-md bg-white"
                  >
                    <div className="flex items-center justify-between px-4 py-2.5 bg-canvas-subtle border-b border-line">
                      <span className="text-sm font-semibold text-ink-subtle flex items-center gap-2">
                        {id.toUpperCase()}
                        <span className="w-1.5 h-1.5 bg-accent rounded-full animate-pulse" />
                      </span>
                      <span className="text-2xs text-ink-subtle">{t('discover.searching_short', 'searching…')}</span>
                    </div>
                    <div className="p-4 space-y-2">
                      <div className="skeleton h-3 w-3/4" />
                      <div className="skeleton h-3 w-1/2" />
                      <div className="skeleton h-3 w-2/3" />
                    </div>
                  </div>
                ))}
          </div>
        </section>
      )}

      {/* Synth */}
      {stream.synth && (
        <section className="px-6 py-4 border-t border-line bg-canvas-subtle/50">
          <div className="max-w-[1280px] mx-auto">
            <header className="flex items-center gap-2 mb-3">
              <Sparkles size={14} className="text-accent" />
              <h2 className="text-base font-semibold text-ink">
                {t('discover.llm_summary', 'LLM summary')}
              </h2>
              <span className="text-2xs text-ink-subtle">
                ({(synthesize ? t('discover.synth.generated', 'generated from streaming results') : t('discover.synth.cached', 'cached'))})
              </span>
            </header>
            <div className="card p-5 bg-white">
              <MarkdownView markdown={stream.synth} />
            </div>
          </div>
        </section>
      )}

      {/* Empty state */}
      {stream.status === 'idle' && (
        <section className="px-6 py-10">
          <div className="max-w-[640px] mx-auto text-center text-ink-muted">
            <Radio size={28} className="mx-auto mb-3 text-ink-subtle" />
            <p className="text-base">{t('discover.empty.title', 'Type a query to fan out across all selected databases.')}</p>
            <p className="text-xs text-ink-subtle mt-1.5">
              {t('discover.empty.sub_1', 'Results stream in as each source responds. Same query already catalogued internally?')}{' '}
              <a href="/singligent/explore" className="text-accent underline">
                {t('discover.empty.try_explore', 'Try Explore')}
              </a>{' '}
              {t('discover.empty.sub_2', 'for instant results.')}
            </p>
          </div>
        </section>
      )}

      {/* Done state with 0 hits */}
      {stream.status === 'done' && stream.totalFound === 0 && (
        <section className="px-6 py-8">
          <div className="max-w-[640px] mx-auto text-center text-ink-muted flex flex-col items-center gap-2">
            <Info size={22} className="text-ink-subtle" />
            <p className="text-base">{t('discover.nohits_1', 'No live hits across')} {stream.sources.length} {t('discover.nohits_2', 'sources.')}</p>
            <p className="text-xs text-ink-subtle">
              {t('discover.nohits.sub', 'Try broadening the terms, removing the year restriction, or running the same query against the curated catalog —')}{' '}
              <a
                href={`/singligent/explore?q=${encodeURIComponent(query)}`}
                className="text-accent hover:underline"
              >
                {t('discover.nohits.explore', 'Explore →')}
              </a>
            </p>
          </div>
        </section>
      )}
    </div>
  );
}
