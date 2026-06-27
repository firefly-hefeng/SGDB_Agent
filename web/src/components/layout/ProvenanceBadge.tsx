/* Phase 30.C — provenance badge for the TopNav.
 *
 * A biologist publishing a paper that used the portal needs to cite
 * a specific build of the catalog + ontology. This badge:
 *  - loads /scdbAPI/version on mount
 *  - shows just the DB build date in the TopNav as a compact chip
 *  - opens a popover with the full provenance (app version, phase,
 *    sample/project counts, agent parser mode, ontology source counts,
 *    last ETL run) when clicked
 *  - includes a copy-to-clipboard cite snippet ready to paste into
 *    a Methods section
 *
 * Failure modes: if /version 404s (older deployment) the badge stays
 * collapsed and silent; the page still works.
 */

import { useEffect, useRef, useState } from 'react';
import { Info, Copy, Check } from 'lucide-react';
import { getVersion, type VersionInfo } from '../../services/api';

interface Props {
  /** TopNav uses dark surface on landing; light elsewhere. */
  dark?: boolean;
}

function formatBuildDate(raw?: string): string {
  if (!raw) return '';
  // Server returns "YYYY-MM-DD HH:MM:SS" UTC; show just the date.
  return raw.slice(0, 10);
}

function buildCitation(v: VersionInfo): string {
  const parts: string[] = [];
  parts.push(`${v.service} v${v.app_version} (Phase ${v.phase})`);
  if (v.db_build_date) parts.push(`DB build ${v.db_build_date}`);
  if (v.db_sample_count) parts.push(`${v.db_sample_count.toLocaleString()} samples`);
  if (v.ontology?.by_source) {
    const onto = Object.entries(v.ontology.by_source)
      .map(([k, n]) => `${k}=${n}`)
      .join(', ');
    parts.push(`ontologies(${onto})`);
  }
  return parts.join(' · ');
}

export function ProvenanceBadge({ dark = false }: Props) {
  const [version, setVersion] = useState<VersionInfo | null>(null);
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const popoverRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    getVersion().then(setVersion).catch(() => {
      // /version not available on this deployment — stay silent.
    });
  }, []);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onEsc);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onEsc);
    };
  }, [open]);

  if (!version) return null;

  const cite = buildCitation(version);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(cite);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      /* silently ignore — clipboard may be unavailable */
    }
  };

  const dateStr = formatBuildDate(version.db_build_date);

  return (
    <div className="relative" ref={popoverRef}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        title="Click for full provenance (DB build, ontology versions, agent mode)"
        aria-haspopup="dialog"
        aria-expanded={open}
        className={`inline-flex items-center gap-1 text-2xs px-2 py-0.5 rounded-md font-medium transition-colors ${
          dark
            ? 'bg-white/10 text-white/80 hover:bg-white/20'
            : 'bg-canvas-subtle text-ink-muted hover:bg-canvas-strong border border-line'
        }`}
      >
        <Info size={10} aria-hidden="true" />
        DB {dateStr || version.app_version}
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Service provenance"
          className="absolute right-0 mt-2 w-[360px] bg-white border border-line rounded-lg shadow-lg z-50 text-ink"
        >
          <header className="px-4 py-3 border-b border-line">
            <p className="text-2xs uppercase tracking-wider text-ink-subtle">Provenance</p>
            <p className="text-sm font-semibold mt-0.5">
              {version.service} v{version.app_version}
            </p>
          </header>

          <dl className="px-4 py-3 grid grid-cols-[110px_1fr] gap-x-3 gap-y-1.5 text-xs">
            {version.db_build_date && (
              <>
                <dt className="text-ink-subtle">DB build</dt>
                <dd className="font-mono">{version.db_build_date}</dd>
              </>
            )}
            {version.db_sample_count != null && (
              <>
                <dt className="text-ink-subtle">Samples</dt>
                <dd className="tabular-nums">{version.db_sample_count.toLocaleString()}</dd>
              </>
            )}
            {version.db_project_count != null && (
              <>
                <dt className="text-ink-subtle">Projects</dt>
                <dd className="tabular-nums">{version.db_project_count.toLocaleString()}</dd>
              </>
            )}
            {version.agent_parser_mode && (
              <>
                <dt className="text-ink-subtle">Agent</dt>
                <dd>{version.agent_parser_mode}</dd>
              </>
            )}
            {version.ontology?.by_source && (
              <>
                <dt className="text-ink-subtle">Ontologies</dt>
                <dd className="font-mono text-2xs">
                  {Object.entries(version.ontology.by_source)
                    .map(([k, n]) => `${k}:${n.toLocaleString()}`)
                    .join(' · ')}
                </dd>
              </>
            )}
          </dl>

          <footer className="px-4 py-3 border-t border-line bg-canvas-subtle/50 flex items-center justify-between gap-2">
            <p className="text-2xs text-ink-subtle">Copy a one-line cite snippet:</p>
            <button
              type="button"
              onClick={copy}
              className="btn-ghost text-2xs inline-flex items-center gap-1 px-2 py-1"
              aria-label="Copy provenance citation to clipboard"
            >
              {copied ? <Check size={10} /> : <Copy size={10} />}
              {copied ? 'Copied' : 'Copy cite'}
            </button>
          </footer>
        </div>
      )}
    </div>
  );
}
