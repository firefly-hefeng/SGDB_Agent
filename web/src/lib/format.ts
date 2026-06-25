/* Shared number / size / date formatters.
 * Consolidates the duplicate ``fmt(n)`` implementations spread across
 * StatsPage, QuickStats, DatabaseCards, ProjectsExplorePage, SeriesExplorePage. */

export function fmt(n: number | undefined | null): string {
  if (n === undefined || n === null || !Number.isFinite(n)) return '—';
  if (n >= 1e9) return (n / 1e9).toFixed(1).replace(/\.0$/, '') + 'B';
  if (n >= 1e6) return (n / 1e6).toFixed(1).replace(/\.0$/, '') + 'M';
  if (n >= 1e4) return (n / 1e3).toFixed(0) + 'K';
  if (n >= 1e3) return (n / 1e3).toFixed(1).replace(/\.0$/, '') + 'K';
  return String(n);
}

export function fmtBytes(bytes: number | undefined | null): string {
  if (bytes === undefined || bytes === null || !Number.isFinite(bytes)) return '—';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  if (bytes < 1024 ** 4) return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
  return `${(bytes / 1024 ** 4).toFixed(2)} TB`;
}

export function fmtDate(s: string | undefined | null): string {
  if (!s) return '—';
  // Already short? Return as-is.
  if (s.length === 10) return s;
  try {
    const d = new Date(s);
    if (Number.isNaN(d.getTime())) return s;
    return d.toISOString().slice(0, 10);
  } catch {
    return s;
  }
}

export function fmtMs(ms: number | undefined | null): string {
  if (ms === undefined || ms === null) return '—';
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

/* Canonical display casing for source-database / archive identifiers. The
 * underlying lowercase key is kept for filters & lookups; only display text
 * is humanized. Shared so every surface (Explore, Stats, Discover, detail)
 * renders the same brand casing. */
export const SOURCE_LABELS: Record<string, string> = {
  geo: 'GEO', ega: 'EGA', ncbi: 'NCBI', ebi: 'EBI', cellxgene: 'CellxGene',
  hca: 'HCA', scea: 'SCEA', htan: 'HTAN', psychad: 'PsychAD', sra: 'SRA',
};

/** Humanize a raw enum value: source-brand map first, else snake_case → sentence case. */
export function prettyLabel(v: unknown): string {
  const s = String(v ?? '');
  if (!s) return s;
  const k = s.toLowerCase();
  if (SOURCE_LABELS[k]) return SOURCE_LABELS[k];
  const spaced = s.replace(/_/g, ' ');
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/** Canonical display name for a source-database identifier (alias of prettyLabel). */
export function sourceLabel(v: unknown): string {
  return prettyLabel(v);
}
