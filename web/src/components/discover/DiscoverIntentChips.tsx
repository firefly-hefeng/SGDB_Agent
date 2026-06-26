import type { QueryIntent } from '../../types/discovery';
import { useT } from '../../lib/i18n';

interface Props {
  intent: QueryIntent | null;
}

// kind → { i18n key, English fallback }. The label text is resolved through t().
const LABELS: Record<string, { key: string; en: string }> = {
  disease: { key: 'discover.intent.disease', en: 'Disease' },
  tissue: { key: 'discover.intent.tissue', en: 'Tissue' },
  tech: { key: 'discover.intent.tech', en: 'Tech' },
  species: { key: 'discover.intent.species', en: 'Species' },
  keywords: { key: 'discover.intent.keywords', en: 'Keywords' },
  negative_terms: { key: 'discover.intent.excluded', en: 'Excluded' },
};

const KIND_TO_BADGE: Record<string, string> = {
  disease: 'badge-rose',
  tissue: 'badge-emerald',
  tech: 'badge-indigo',
  species: 'badge-cyan',
  keywords: 'badge-gray',
  negative_terms: 'badge-amber',
};

export function DiscoverIntentChips({ intent }: Props) {
  const { t } = useT();
  if (!intent) return null;
  const entries: { kind: string; values: string[] }[] = [];
  for (const [k, label] of Object.entries(LABELS)) {
    void label;
    const v = (intent as unknown as Record<string, unknown>)[k];
    if (Array.isArray(v) && v.length > 0) {
      entries.push({ kind: k, values: v as string[] });
    }
  }
  if (intent.time_hint) {
    entries.push({ kind: 'time_hint', values: [intent.time_hint] });
  }
  if (intent.restrict_sources && intent.restrict_sources.length > 0) {
    entries.push({ kind: 'restrict', values: intent.restrict_sources });
  }
  if (!entries.length) return null;

  // Labels for the two synthetic kinds that aren't in LABELS.
  const labelFor = (kind: string): string => {
    const meta = LABELS[kind];
    if (meta) return t(meta.key, meta.en);
    if (kind === 'time_hint') return t('discover.intent.time', 'Time');
    if (kind === 'restrict') return t('discover.intent.restrict', 'Sources');
    return kind.replace('_', ' ');
  };

  return (
    <div className="flex flex-wrap items-center gap-1.5 text-xs">
      <span className="text-2xs uppercase tracking-wide text-ink-subtle mr-1">
        {t('discover.intent.parsed', 'Parsed intent')}
      </span>
      {entries.map(({ kind, values }) => (
        <span key={kind} className="inline-flex items-center gap-1">
          <span className="text-2xs text-ink-subtle">
            {labelFor(kind)}
          </span>
          {values.map((v) => (
            <span key={`${kind}-${v}`} className={`badge ${KIND_TO_BADGE[kind] ?? 'badge-gray'}`}>
              {v}
            </span>
          ))}
        </span>
      ))}
    </div>
  );
}
