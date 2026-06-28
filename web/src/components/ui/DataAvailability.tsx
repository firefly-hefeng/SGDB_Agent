import { Database, ExternalLink, FileDown, ShieldCheck } from 'lucide-react';
import { DATA_RELEASE, dataReleasePublished } from '../../config/dataRelease';
import { useT } from '../../lib/i18n';
import { fmt } from '../../lib/format';

/**
 * Data-availability / bulk-download section (FAIR). Links to the deposited
 * catalog tables (Zenodo DOI + Hugging Face) and is explicit that this is the
 * harmonized METADATA, not the raw sequencing data.
 */
export function DataAvailability({ className = '' }: { className?: string }) {
  const { t } = useT();
  const published = dataReleasePublished();

  return (
    <section className={`card p-5 ${className}`}>
      <div className="flex items-center gap-2 mb-1.5">
        <Database size={16} className="text-accent" />
        <h2 className="text-base font-semibold text-ink">{t('data.title', 'Data availability')}</h2>
      </div>
      <p className="text-sm text-ink-muted leading-relaxed mb-3">
        {t('data.body',
          'The full curated catalog is openly downloadable as bulk tables (Parquet + CSV) and a complete SQLite snapshot.')}
      </p>

      {/* Metadata-vs-raw-data clarification (important) */}
      <div className="rounded-md border border-line-subtle bg-canvas-subtle p-3 text-2xs text-ink-muted leading-relaxed mb-4">
        <ShieldCheck size={12} className="inline mr-1 -mt-0.5 text-accent" />
        {t('data.note',
          'This bundle is the harmonized metadata (sample / project / series / cell-type descriptions), not the raw sequencing data — count matrices and FASTQ/BAM remain at the source archives, and the portal resolves exact per-dataset download links to them.')}
      </div>

      {/* Tables */}
      <ul className="grid sm:grid-cols-2 gap-2 mb-4">
        {DATA_RELEASE.tables.map((tb) => (
          <li key={tb.name} className="rounded-md border border-line-subtle p-2.5">
            <div className="flex items-center justify-between">
              <code className="text-xs text-ink">{tb.name}</code>
              <span className="text-2xs text-ink-subtle tabular-nums">{fmt(tb.rows)} {t('data.rows', 'rows')}</span>
            </div>
            <div className="text-2xs text-ink-subtle mt-0.5">{t(`data.tier.${tb.name}`, tb.desc)}</div>
          </li>
        ))}
      </ul>

      {published ? (
        <div className="flex flex-wrap items-center gap-2">
          {DATA_RELEASE.zenodoUrl && (
            <a href={DATA_RELEASE.zenodoUrl} target="_blank" rel="noopener noreferrer"
               className="btn btn-accent text-sm inline-flex items-center gap-1.5">
              <FileDown size={14} /> {t('data.zenodo', 'Download (Zenodo)')}
              {DATA_RELEASE.zenodoDoi && <span className="text-2xs opacity-85">DOI: {DATA_RELEASE.zenodoDoi}</span>}
            </a>
          )}
          {DATA_RELEASE.hfUrl && (
            <a href={DATA_RELEASE.hfUrl} target="_blank" rel="noopener noreferrer"
               className="btn btn-secondary text-sm inline-flex items-center gap-1.5">
              <ExternalLink size={14} /> {t('data.hf', 'Browse on Hugging Face')}
            </a>
          )}
        </div>
      ) : (
        <p className="text-xs text-ink-subtle italic">
          {t('data.pending', 'Public deposition pending — the bundle is being archived to Zenodo (DOI) and Hugging Face.')}
        </p>
      )}

      <p className="text-2xs text-ink-subtle mt-3">
        {t('data.license', 'License')}: {DATA_RELEASE.license} · {t('data.snapshot', 'snapshot')} <code>{DATA_RELEASE.snapshot}</code>
        {' · '}{t('data.ega', 'EGA: metadata-only; data access requires DAC approval.')}
      </p>
    </section>
  );
}
