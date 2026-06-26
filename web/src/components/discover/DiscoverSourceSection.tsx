import { useMemo, useState } from 'react';
import { ExternalLink, Download, ChevronLeft, ChevronRight, FileDown, Plus, Check } from 'lucide-react';
import type { DiscoveryResult, DatasetResult } from '../../types/discovery';
import { fmt, fmtMs, sourceLabel } from '../../lib/format';
import { manifestAdd, manifestHas, manifestRemove } from '../../lib/manifest';
import { useManifest } from '../../hooks/useManifest';
import { toast } from '../../lib/toastApi';
import { SaveButton } from '../workspace/SaveButton';
import { useT } from '../../lib/i18n';

interface Props {
  result: DiscoveryResult;
  pageSize?: number;
}

function csvEscape(v: unknown): string {
  if (v === null || v === undefined) return '';
  const s = String(v);
  if (/[",\n]/.test(s)) return '"' + s.replaceAll('"', '""') + '"';
  return s;
}

function exportRowsAsCsv(source: string, rows: DatasetResult[]) {
  const header = [
    'id',
    'title',
    'organism',
    'sample_count',
    'date',
    'source_db',
    'source_url',
    'download_url',
    'mirrors',
  ];
  const lines = [header.join(',')];
  for (const r of rows) {
    const mirrorsStr = (r.mirrors || []).map((m) => `${m.source_db}:${m.id}`).join('|');
    lines.push(
      [
        r.id,
        r.title,
        r.organism,
        r.sample_count,
        r.date,
        r.source_db,
        r.source_url,
        r.download_url,
        mirrorsStr,
      ]
        .map(csvEscape)
        .join(','),
    );
  }
  const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `discovery_${source}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export function DiscoverSourceSection({ result, pageSize = 10 }: Props) {
  const { t } = useT();
  const [page, setPage] = useState(0);
  const { count: manifestCount } = useManifest();
  void manifestCount; // re-render trigger only

  const rows = useMemo(() => result.results ?? [], [result.results]);
  const total = rows.length;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const safePage = Math.min(page, totalPages - 1);
  const slice = useMemo(
    () => rows.slice(safePage * pageSize, safePage * pageSize + pageSize),
    [rows, safePage, pageSize],
  );

  const srcLabel = sourceLabel(result.source);

  const addAll = () => {
    const added = manifestAdd(
      rows
        .filter((r) => r.id)
        .map((r) => ({
          id: r.id,
          source_db: r.source_db,
          source_url: r.source_url,
          download_url: r.download_url ?? null,
          file_type: null,
          size_estimate: null,
          title: r.title,
        })),
    );
    toast(`${t('discover.sec.toast.added_rows_1', 'Added')} ${added} ${srcLabel} ${added === 1 ? t('discover.sec.toast.row', 'row') : t('discover.sec.toast.rows', 'rows')} ${t('discover.sec.toast.to_manifest', 'to manifest')}`);
  };

  return (
    <article className="border border-line rounded-md bg-white overflow-hidden">
      <header className="flex items-center justify-between px-4 py-2.5 bg-canvas-subtle border-b border-line">
        <div className="flex items-center gap-3 min-w-0">
          <h3 className="text-sm font-semibold text-ink">{srcLabel}</h3>
          <span className="text-xs text-ink-muted">
            {result.total_found.toLocaleString()} {t('discover.sec.found', 'found')}
          </span>
          <span className="text-2xs text-ink-subtle tabular-nums">
            {fmtMs(result.latency_ms)}
          </span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={addAll}
            disabled={!rows.length}
            title={t('discover.sec.add_manifest.title', 'Add all visible rows to manifest')}
            className="btn-ghost text-2xs inline-flex items-center gap-1 px-2 py-1 disabled:opacity-40"
          >
            <FileDown size={12} /> {t('discover.sec.add_manifest', 'Add to manifest')}
          </button>
          <button
            onClick={() => exportRowsAsCsv(result.source, rows)}
            disabled={!rows.length}
            title={t('discover.sec.csv.title', 'Download these rows as CSV')}
            className="btn-ghost text-2xs inline-flex items-center gap-1 px-2 py-1 disabled:opacity-40"
          >
            <Download size={12} /> CSV
          </button>
        </div>
      </header>

      {result.error && (
        <div className="px-4 py-2 text-xs text-[var(--error)] bg-red-50 border-b border-red-100">
          {result.error}
        </div>
      )}

      {rows.length === 0 ? (
        <p className="px-4 py-3 text-xs text-ink-subtle">{t('discover.sec.empty', 'No matching datasets.')}</p>
      ) : (
        <>
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-2xs uppercase tracking-wide text-ink-subtle border-b border-line-subtle">
                <th className="px-4 py-1.5 font-medium w-[140px]">ID</th>
                <th className="px-4 py-1.5 font-medium">{t('discover.sec.col.title', 'Title')}</th>
                <th className="px-4 py-1.5 font-medium w-[120px]">{t('discover.sec.col.organism', 'Organism')}</th>
                <th className="px-4 py-1.5 font-medium w-[80px] text-right">{t('discover.sec.col.samples', 'Samples')}</th>
                <th className="px-4 py-1.5 font-medium w-[100px]">{t('discover.sec.col.date', 'Date')}</th>
                <th className="px-4 py-1.5 font-medium w-[80px]">{t('discover.sec.col.actions', 'Actions')}</th>
              </tr>
            </thead>
            <tbody>
              {slice.map((r) => (
                <DatasetRow key={`${result.source}-${r.id}`} row={r} />
              ))}
            </tbody>
          </table>

          {totalPages > 1 && (
            <footer className="flex items-center justify-between px-4 py-2 border-t border-line-subtle bg-canvas-subtle">
              <span className="text-2xs text-ink-muted tabular-nums">
                {safePage * pageSize + 1}–{Math.min((safePage + 1) * pageSize, total)} {t('discover.sec.of', 'of')} {total}
              </span>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => setPage(Math.max(0, safePage - 1))}
                  disabled={safePage === 0}
                  className="btn-ghost text-2xs inline-flex items-center gap-0.5 px-1.5 py-1 disabled:opacity-40"
                >
                  <ChevronLeft size={13} /> {t('discover.sec.prev', 'Prev')}
                </button>
                <span className="text-2xs text-ink-subtle tabular-nums">
                  {safePage + 1} / {totalPages}
                </span>
                <button
                  onClick={() => setPage(Math.min(totalPages - 1, safePage + 1))}
                  disabled={safePage + 1 >= totalPages}
                  className="btn-ghost text-2xs inline-flex items-center gap-0.5 px-1.5 py-1 disabled:opacity-40"
                >
                  {t('discover.sec.next', 'Next')} <ChevronRight size={13} />
                </button>
              </div>
            </footer>
          )}
        </>
      )}
    </article>
  );
}

function DatasetRow({ row }: { row: DatasetResult }) {
  const { t } = useT();
  const isInManifest = manifestHas(row.source_db, row.id);

  const toggleManifest = () => {
    if (isInManifest) {
      manifestRemove(row.source_db, row.id);
      toast(`${t('discover.sec.toast.removed_row', 'Removed')} ${row.id} ${t('discover.sec.toast.from_manifest', 'from manifest')}`, 'info');
    } else {
      manifestAdd([
        {
          id: row.id,
          source_db: row.source_db,
          source_url: row.source_url,
          download_url: row.download_url ?? null,
          file_type: null,
          size_estimate: null,
          title: row.title,
        },
      ]);
      toast(`${t('discover.sec.toast.added_row', 'Added')} ${row.id} ${t('discover.sec.toast.to_manifest', 'to manifest')}`);
    }
  };

  return (
    <tr className="border-b border-line-subtle hover:bg-canvas-subtle/40">
      <td className="px-4 py-2 align-top">
        <div className="flex flex-col gap-1">
          <a
            href={row.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-accent hover:underline font-mono text-xs inline-flex items-center gap-0.5"
          >
            {row.id} <ExternalLink size={10} />
          </a>
          {row.mirrors?.length ? (
            <div className="flex flex-wrap gap-0.5">
              {row.mirrors.map((m) => (
                <a
                  key={`${m.source_db}-${m.id}`}
                  href={m.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  title={`${t('discover.sec.mirror.title', 'Same study in')} ${sourceLabel(m.source_db)}`}
                  className="text-2xs px-1 py-0 rounded bg-canvas-muted text-ink-muted hover:bg-accent-subtle hover:text-accent"
                >
                  {sourceLabel(m.source_db)}
                </a>
              ))}
            </div>
          ) : null}
        </div>
      </td>
      <td className="px-4 py-2 align-top text-ink line-clamp-2">{row.title}</td>
      <td className="px-4 py-2 align-top text-ink-muted italic">{row.organism || '—'}</td>
      <td className="px-4 py-2 align-top text-right tabular-nums text-ink-muted">
        {row.sample_count != null ? fmt(row.sample_count) : '—'}
      </td>
      <td className="px-4 py-2 align-top text-ink-subtle tabular-nums">
        {row.date || '—'}
      </td>
      <td className="px-4 py-2 align-top">
        <div className="flex items-center gap-0.5">
          <button
            onClick={toggleManifest}
            title={isInManifest ? t('discover.sec.remove_row.title', 'Remove from manifest') : t('discover.sec.add_row.title', 'Add to manifest')}
            className={`btn-ghost p-1 ${isInManifest ? 'text-[var(--success)]' : 'text-ink-subtle'} hover:text-ink`}
          >
            {isInManifest ? <Check size={13} /> : <Plus size={13} />}
          </button>
          {/* B3 — file a discovered dataset straight into a server-side
              workspace, without the manifest detour. */}
          <SaveButton
            target={{
              item_type: 'project',
              item_id: row.id,
              source_database: row.source_db,
              title: row.title,
            }}
            size={13}
          />
        </div>
      </td>
    </tr>
  );
}
