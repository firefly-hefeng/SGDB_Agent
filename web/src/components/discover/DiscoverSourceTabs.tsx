import type { DiscoveryResult, DiscoverySource } from '../../types/discovery';
import { sourceLabel } from '../../lib/format';
import { useT } from '../../lib/i18n';

interface Props {
  sources: DiscoverySource[];
  results: DiscoveryResult[];
  activeTab: string;
  setActiveTab: (id: string) => void;
  totalFound: number;
  pendingSources: number;
}

export function DiscoverSourceTabs({
  sources,
  results,
  activeTab,
  setActiveTab,
  totalFound,
  pendingSources,
}: Props) {
  const { t } = useT();
  const tabs: { id: string; label: string; count: number; error?: boolean; pending?: boolean }[] = [
    { id: 'all', label: t('discover.tabs.all', 'All'), count: totalFound, pending: pendingSources > 0 },
  ];
  const resultsBySource = new Map(results.map((r) => [r.source, r]));

  for (const s of sources) {
    const r = resultsBySource.get(s.id);
    tabs.push({
      id: s.id,
      label: sourceLabel(s.name),
      count: r?.total_found ?? 0,
      error: r ? r.error != null : false,
      pending: r == null,
    });
  }

  return (
    <nav
      className="flex items-center gap-1 overflow-x-auto scrollbar-hide"
      aria-label={t('discover.tabs.aria', 'Filter results by source')}
    >
      {tabs.map((tab) => {
        const active = tab.id === activeTab;
        return (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs whitespace-nowrap transition-colors ${
              active
                ? 'bg-accent-bg text-accent border border-accent-border'
                : 'text-ink-muted hover:bg-canvas-subtle hover:text-ink'
            }`}
          >
            <span>{tab.label}</span>
            <span
              className={`text-2xs tabular-nums rounded-full px-1.5 py-0.5 ${
                active ? 'bg-white/70' : 'bg-canvas-muted'
              }`}
            >
              {tab.count.toLocaleString()}
            </span>
            {tab.error && (
              <span className="text-[var(--warning)]" title={t('discover.tabs.source_error', 'Source error')}>
                ⚠
              </span>
            )}
            {tab.pending && !tab.error && (
              <span
                className="inline-block w-1.5 h-1.5 rounded-full bg-accent animate-pulse"
                title={t('discover.tabs.loading', 'Loading')}
              />
            )}
          </button>
        );
      })}
    </nav>
  );
}
