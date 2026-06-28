/* Phase 31.C — actionable error card for NL/advanced-search failures.
 *
 * Replaces the bare red alert bar. Classifies the error message into
 * timeout / 5xx / network / parser and:
 *   - shows friendlier copy for each class
 *   - offers a "Try again" button (calls back into the hook's retry)
 *   - offers a "Dismiss" button to clear the banner without retrying
 *   - shows a "Help" hint for the most common biologist failure mode
 *
 * Stays compact — should never push the results table below the fold.
 */

import { AlertCircle, RotateCw, X } from 'lucide-react';
import { useT } from '../../lib/i18n';

interface Props {
  /** Raw error string from the hook (e.g. "API error 500: ...",
   *  "TypeError: Failed to fetch", "timeout"). */
  error: string;
  /** Returns true if a previous attempt was recorded and re-fired. */
  onRetry: () => boolean;
  onDismiss: () => void;
}

type ErrorClass = 'timeout' | 'server' | 'parser' | 'network' | 'unknown';

// classify() returns only the error class; the human copy is resolved through
// t() in the component so it follows the active language.
function classify(error: string): ErrorClass {
  const lower = (error || '').toLowerCase();
  if (lower.includes('timeout') || lower.includes('timed out') || lower.includes('aborted')) {
    return 'timeout';
  }
  if (lower.includes(' 5') && /api error 5\d\d/.test(lower)) {
    return 'server';
  }
  if (lower.includes('failed to fetch') || lower.includes('network')) {
    return 'network';
  }
  if (lower.includes('parser') || lower.includes('parse failed') || lower.includes(' 422')) {
    return 'parser';
  }
  return 'unknown';
}

const COPY: Record<ErrorClass, { titleKey: string; titleEn: string; hintKey: string; hintEn: string }> = {
  timeout: {
    titleKey: 'err.timeout.title',
    titleEn: 'The agent didn’t answer in time',
    hintKey: 'err.timeout.hint',
    hintEn:
      'Cold-cache NL queries can take 60–90 s on the first call. Try again — the parser cache should make it instant the second time. If it times out again, simplify the query (one disease + one tissue) and retry.',
  },
  server: {
    titleKey: 'err.server.title',
    titleEn: 'The server returned an error',
    hintKey: 'err.server.hint',
    hintEn:
      'The backend hit an exception while running your query. Try again; if it persists, simplify the filters or check /scdbAPI/health.',
  },
  network: {
    titleKey: 'err.network.title',
    titleEn: 'Could not reach the server',
    hintKey: 'err.network.hint',
    hintEn:
      'Network or the API process is offline. Check that the server is running and your VPN/tunnel is up, then retry.',
  },
  parser: {
    titleKey: 'err.parser.title',
    titleEn: 'Could not parse the query',
    hintKey: 'err.parser.hint',
    hintEn:
      'The agent didn’t recognise the structure. Try a simpler phrasing — e.g. "lung COVID-19" instead of multi-clause natural language.',
  },
  unknown: {
    titleKey: 'err.unknown.title',
    titleEn: 'Search failed',
    hintKey: 'err.unknown.hint',
    hintEn: 'Try again; if it persists, simplify the query or check the server logs.',
  },
};

export function SearchErrorCard({ error, onRetry, onDismiss }: Props) {
  const { t } = useT();
  const copy = COPY[classify(error)];
  const title = t(copy.titleKey, copy.titleEn);
  const hint = t(copy.hintKey, copy.hintEn);
  return (
    <div
      role="alert"
      aria-live="assertive"
      className="flex items-start gap-2.5 text-sm text-[var(--error)] bg-[color-mix(in_srgb,var(--error)_6%,white)] border border-[color-mix(in_srgb,var(--error)_25%,white)] rounded-md px-3 py-2.5"
    >
      <AlertCircle size={15} className="mt-0.5 shrink-0" aria-hidden="true" />
      <div className="flex-1 min-w-0">
        <p className="font-medium leading-tight">{title}</p>
        <p className="text-xs text-ink-muted mt-1 leading-snug">{hint}</p>
        <p
          className="text-2xs font-mono text-ink-subtle mt-1.5 break-words"
          aria-label={t('err.original.aria', 'Original error message')}
        >
          {error}
        </p>
      </div>
      <div className="flex items-center gap-1 shrink-0">
        <button
          type="button"
          onClick={onRetry}
          className="btn-ghost text-xs inline-flex items-center gap-1 px-2 py-1 hover:bg-white/60"
          aria-label={t('err.tryagain.aria', 'Retry the last search')}
        >
          <RotateCw size={11} /> {t('err.tryagain', 'Try again')}
        </button>
        <button
          type="button"
          onClick={onDismiss}
          aria-label={t('err.dismiss.aria', 'Dismiss error banner')}
          className="btn-ghost p-1 hover:bg-white/60"
        >
          <X size={11} />
        </button>
      </div>
    </div>
  );
}
