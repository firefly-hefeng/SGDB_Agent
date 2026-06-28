/* Phase 30.B — phased progress chip for NL→SQL cold-path queries.
 *
 * The NL agent's first call takes 50-90s (most of it LLM round-trips
 * for parsing + SQL generation). A static "Searching…" spinner makes
 * the user wonder if the system is hung. This chip walks through the
 * agent's expected phases on a client-side timer and shows elapsed
 * seconds — so the user sees the system is making progress, not stuck.
 *
 * Phases are advanced by the parent hook (useAdvancedSearch). The
 * elapsed counter is ticked inside this component to avoid re-rendering
 * the entire results table once a second.
 */

import { useEffect, useState } from 'react';
import { Brain, FlaskConical, Database, Layers, Loader2 } from 'lucide-react';
import type { NlPhase } from '../../hooks/useAdvancedSearch';
import { useT } from '../../lib/i18n';

interface Props {
  phase: NlPhase;
  startedAt: number | null;
}

// label/hint are resolved through t() at render via the .key / .en fallbacks.
const PHASE_META: Record<Exclude<NlPhase, 'idle'>, { labelKey: string; labelEn: string; hintKey: string; hintEn: string; icon: typeof Brain }> = {
  parsing: {
    labelKey: 'nlp.parsing.label',
    labelEn: 'Parsing your query',
    hintKey: 'nlp.parsing.hint',
    hintEn: 'The agent is reading your intent and picking out entities (~10-15 s).',
    icon: Brain,
  },
  resolving: {
    labelKey: 'nlp.resolving.label',
    labelEn: 'Resolving ontologies',
    hintKey: 'nlp.resolving.hint',
    hintEn: 'Expanding terms via UBERON / MONDO / CL / EFO.',
    icon: FlaskConical,
  },
  querying: {
    labelKey: 'nlp.querying.label',
    labelEn: 'Running SQL against 943 K samples',
    hintKey: 'nlp.querying.hint',
    hintEn: 'Generating + executing the candidate query plans.',
    icon: Database,
  },
  fusing: {
    labelKey: 'nlp.fusing.label',
    labelEn: 'De-duplicating across sources',
    hintKey: 'nlp.fusing.hint',
    hintEn: 'Cross-source rollup — almost done.',
    icon: Layers,
  },
};

export function NlProgress({ phase, startedAt }: Props) {
  const { t } = useT();
  // Store elapsed seconds in state, updated via interval callback only.
  // Avoids both react-hooks/set-state-in-effect (no sync setState in effect
  // body) and react-hooks/purity (no Date.now() in render).
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!startedAt) return;
    const id = window.setInterval(() => {
      setElapsed(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);
    return () => window.clearInterval(id);
  }, [startedAt]);

  if (phase === 'idle') return null;
  const meta = PHASE_META[phase];
  const Icon = meta.icon;

  return (
    <div
      role="status"
      aria-live="polite"
      className="flex items-center gap-3 text-xs bg-accent-subtle border border-accent-border/40 rounded-md px-3 py-2"
    >
      <Loader2 size={13} className="animate-spin text-accent shrink-0" aria-hidden="true" />
      <Icon size={13} className="text-accent shrink-0" aria-hidden="true" />
      <div className="flex-1 min-w-0">
        <p className="font-medium text-ink">{t(meta.labelKey, meta.labelEn)}…</p>
        <p className="text-2xs text-ink-subtle">{t(meta.hintKey, meta.hintEn)}</p>
      </div>
      <span className="text-2xs tabular-nums text-ink-subtle shrink-0" aria-label={t('nlp.elapsed.aria', 'elapsed seconds')}>
        {elapsed}s
      </span>
    </div>
  );
}
