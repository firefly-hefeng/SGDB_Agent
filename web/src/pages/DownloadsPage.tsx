import { useState, useEffect, useMemo } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import {
  Download,
  Plus,
  X,
  Loader2,
  ArrowRight,
  Database,
  ChevronDown,
  Trash2,
  ExternalLink,
  HardDrive,
  ShieldCheck,
  Zap,
} from 'lucide-react';
import {
  getDownloads,
  generateManifest,
  downloadBlob,
  downloadMetadata,
  estimateDownloads,
} from '../services/api';
import type { DownloadOption, DownloadEstimate } from '../types/api';
import { useManifest } from '../hooks/useManifest';
import { manifestClear, manifestRemove } from '../lib/manifest';
import { toast } from '../lib/toastApi';
import { sourceLabel } from '../lib/format';
import { ProvenanceBadge } from '../components/layout/ProvenanceBadge';
import { HowToUse } from '../components/ui/HowToUse';
import { Eyebrow } from '../components/ui/PageHeader';
import { DataAvailability } from '../components/ui/DataAvailability';
import { useT } from '../lib/i18n';

const FILE_TYPES = [
  { id: 'fastq', label: 'FASTQ', badge: 'badge-blue' },
  { id: 'bam', label: 'BAM', badge: 'badge-sky' },
  { id: 'h5ad', label: 'H5AD', badge: 'badge-purple' },
  { id: 'rds', label: 'RDS', badge: 'badge-green' },
  { id: 'matrix', label: 'Matrix', badge: 'badge-orange' },
  { id: 'supplementary', label: 'Supp.', badge: 'badge-amber' },
];
const FORMATS = [
  { v: 'tsv', l: 'TSV', desc: 'Tabular manifest (url + metadata).' },
  { v: 'bash', l: 'Bash', desc: 'Self-contained script: dep-check, retry, logging, per-dataset dirs.' },
  { v: 'aria2', l: 'aria2', desc: 'High-speed parallel aria2c input file.' },
  { v: 'snakemake', l: 'Snakemake', desc: 'Reproducible Snakemake workflow.' },
  { v: 'python', l: 'Python', desc: 'Stdlib Python downloader with retry.' },
];
const METADATA_LIMITS = [
  { v: 250, l: '250' },
  { v: 1000, l: '1K' },
  { v: 10000, l: '10K' },
  { v: 100000, l: '100K' },
];

export default function DownloadsPage() {
  const { t } = useT();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { manifest, count: manifestCount } = useManifest();

  const [ids, setIds] = useState<string[]>([]);
  const [inp, setInp] = useState('');
  const [res, setRes] = useState<Record<string, DownloadOption[]>>({});
  const [totals, setTotals] = useState<Record<string, string | null>>({});
  const [loading, setLoading] = useState(false);
  // Phase 36: resolve the exact files (with sizes + MD5) live from ENA/GEO.
  const [deep, setDeep] = useState(true);
  const [estimate, setEstimate] = useState<DownloadEstimate | null>(null);
  const [estimating, setEstimating] = useState(false);

  const [fmt, setFmt] = useState('tsv');
  const [fileTypes, setFileTypes] = useState(['fastq', 'h5ad', 'supplementary']);

  const [metaLimit, setMetaLimit] = useState<number>(1000);
  const [metaBusy, setMetaBusy] = useState<'csv' | 'json' | null>(null);

  useEffect(() => {
    const idsParam = searchParams.get('ids');
    if (idsParam) {
      const parsed = idsParam.split(',').map((s) => s.trim()).filter(Boolean);
      if (parsed.length) setIds(parsed);
    }
  }, [searchParams]);

  // Pre-populate ids with manifest entries when the page opens with no ?ids=.
  useEffect(() => {
    if (!searchParams.get('ids') && !ids.length && manifestCount > 0) {
      setIds(Array.from(new Set(manifest.entries.map((e) => e.id))));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const add = () => {
    const t = inp.trim();
    if (!t || ids.includes(t)) return;
    setIds([...ids, t]);
    setInp('');
  };
  const rm = (id: string) => {
    setIds(ids.filter((i) => i !== id));
    const n = { ...res };
    delete n[id];
    setRes(n);
  };

  const lookup = async () => {
    setLoading(true);
    const r: Record<string, DownloadOption[]> = {};
    const t: Record<string, string | null> = {};
    // Resolve concurrently — deep lookups hit ENA/GEO and would be slow serially.
    await Promise.all(
      ids.map(async (id) => {
        try {
          const resp = await getDownloads(id, deep);
          r[id] = resp.downloads as DownloadOption[];
          t[id] = resp.total_size_human ?? null;
        } catch {
          r[id] = [];
          t[id] = null;
        }
      }),
    );
    setRes(r);
    setTotals(t);
    setLoading(false);
    toast(`Looked up ${ids.length} dataset${ids.length === 1 ? '' : 's'}${deep ? ' (exact files)' : ''}`);
  };

  const runEstimate = async () => {
    if (!fileTypes.length || !ids.length) return;
    setEstimating(true);
    setEstimate(null);
    try {
      const idSet = new Set(ids);
      const entries = manifest.entries
        .filter((e) => idSet.has(e.id))
        .map((e) => ({
          id: e.id, source_db: e.source_db,
          url: e.download_url || e.source_url || null,
          file_type: e.file_type ?? null, title: e.title ?? null,
        }));
      const est = await estimateDownloads(ids, fileTypes, entries, deep);
      setEstimate(est);
    } catch (e) {
      toast(`Size estimate failed: ${e instanceof Error ? e.message : e}`, 'error');
    } finally {
      setEstimating(false);
    }
  };

  const FILENAMES: Record<string, string> = {
    bash: 'singligent_download.sh', aria2: 'singligent_downloads.aria2',
    snakemake: 'Snakefile', python: 'singligent_download.py', tsv: 'singligent_downloads.tsv',
  };

  const generateScript = async () => {
    if (!fileTypes.length) {
      toast('Pick at least one file type', 'error');
      return;
    }
    try {
      // Phase 27: forward the manifest entries (with their known URLs) for the
      // ids in play, so Discover-sourced datasets not in the local catalog are
      // still included via their stored URL rather than silently dropped.
      const idSet = new Set(ids);
      const entries = manifest.entries
        .filter((e) => idSet.has(e.id))
        .map((e) => ({
          id: e.id, source_db: e.source_db,
          url: e.download_url || e.source_url || null,
          file_type: e.file_type ?? null, title: e.title ?? null,
        }));
      const blob = await generateManifest(ids, fileTypes, fmt, entries, deep);
      downloadBlob(blob, FILENAMES[fmt] || `singligent_downloads.${fmt}`);
      toast(`Generated ${fmt.toUpperCase()} for ${ids.length} dataset${ids.length === 1 ? '' : 's'}`);
    } catch (e) {
      toast(`Script generation failed: ${e instanceof Error ? e.message : e}`, 'error');
    }
  };

  const tog = (t: string) =>
    setFileTypes((p) => (p.includes(t) ? p.filter((x) => x !== t) : [...p, t]));

  const downloadMeta = async (format: 'csv' | 'json') => {
    setMetaBusy(format);
    try {
      const blob = await downloadMetadata([], format, metaLimit);
      downloadBlob(blob, `singligent_metadata_${metaLimit}.${format}`);
      toast(`Downloaded up to ${metaLimit.toLocaleString()} samples as ${format.toUpperCase()}`);
    } catch (e) {
      toast(`Metadata download failed: ${e}`, 'error');
    } finally {
      setMetaBusy(null);
    }
  };

  const B: Record<string, string> = useMemo(() => {
    const m: Record<string, string> = {};
    for (const t of FILE_TYPES) m[t.id] = t.badge;
    return m;
  }, []);

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-[920px] mx-auto px-6 py-8">
        <header className="page-header-band bg-canvas -mx-6 px-6 pt-2 pb-4 mb-6">
          <div className="flex items-start justify-between gap-3 mb-1">
            <Eyebrow>Downloads</Eyebrow>
            <ProvenanceBadge />
          </div>
          <h1 className="text-2xl font-semibold tracking-[-0.01em] text-ink mb-1">
            Build a manifest, then pull the data.
          </h1>
          <p className="text-sm text-ink-muted max-w-[60rem]">
            Look up direct download URLs for any catalogued dataset, export a bulk script (TSV / curl /
            aria2), or pull a slice of unified sample metadata as CSV/JSON. Items added to the global
            manifest from Explore, Search, Discover, or dataset detail pages flow through here.
          </p>
          <HowToUse
            className="mt-3 max-w-[640px]"
            body={t('intro.downloads.body',
              'Look up direct download URLs for any catalogued dataset, export a bulk script from your manifest, or pull a slice of unified sample metadata.')}
            examples={[
              { label: 'GSE149614', onPick: () => setInp('GSE149614'), hint: 'GEO series — resolves files + sizes' },
              { label: 'PRJNA625551', onPick: () => setInp('PRJNA625551') },
              { label: 'E-MTAB-1234', onPick: () => setInp('E-MTAB-1234') },
            ]}
          />
        </header>

        {/* Bulk catalog download (full tables + DB) */}
        <DataAvailability className="mb-6" />

        {/* Manifest banner */}
        {manifestCount > 0 && (
          <section className="mb-5 card p-4 bg-accent-subtle border-accent-border">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-sm font-semibold text-accent mb-0.5">
                  Manifest has {manifestCount} {manifestCount === 1 ? 'entry' : 'entries'}
                </p>
                <p className="text-xs text-ink-muted">
                  These are pre-loaded below; you can also clear them.
                </p>
              </div>
              <div className="flex items-center gap-1.5 shrink-0">
                <button
                  onClick={() => {
                    manifestClear();
                    toast('Manifest cleared');
                  }}
                  className="btn-ghost text-xs inline-flex items-center gap-1 px-2 py-1"
                >
                  <Trash2 size={11} /> Clear
                </button>
              </div>
            </div>
            <ul className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-1.5">
              {manifest.entries.slice(0, 8).map((e) => (
                <li
                  key={e.key}
                  className="flex items-center gap-2 bg-white/70 rounded px-2 py-1 text-xs"
                >
                  <span className={`badge badge-${e.source_db.toLowerCase() === 'geo' ? 'blue' : 'gray'} text-2xs`}>
                    {sourceLabel(e.source_db)}
                  </span>
                  <span className="font-mono text-xs text-accent truncate">{e.id}</span>
                  <span className="flex-1 text-xs text-ink-muted truncate">
                    {e.title || ''}
                  </span>
                  <button
                    onClick={() => manifestRemove(e.source_db, e.id)}
                    className="text-ink-subtle hover:text-[var(--error)] shrink-0"
                    aria-label={`Remove ${e.id}`}
                  >
                    <X size={10} />
                  </button>
                </li>
              ))}
              {manifest.entries.length > 8 && (
                <li className="col-span-full text-2xs text-ink-subtle text-center">
                  …and {manifest.entries.length - 8} more
                </li>
              )}
            </ul>
          </section>
        )}

        <section className="card p-5 mb-5">
          <div className="section-label mb-2">Dataset IDs</div>
          <div className="flex gap-2 mb-3">
            <input
              type="text"
              value={inp}
              onChange={(e) => setInp(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  add();
                }
              }}
              placeholder="GSE149614, PRJNA625551, E-MTAB-1234…"
              className="input text-sm py-2"
            />
            <button onClick={add} className="btn btn-secondary px-3" aria-label="Add ID">
              <Plus size={15} />
            </button>
          </div>
          {ids.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mb-3">
              {ids.map((id) => (
                <span
                  key={id}
                  className="badge badge-sky font-mono inline-flex items-center gap-1"
                >
                  {id}
                  <button
                    onClick={() => rm(id)}
                    aria-label={`Remove ${id}`}
                    className="opacity-40 hover:opacity-100"
                  >
                    <X size={11} />
                  </button>
                </span>
              ))}
            </div>
          )}
          <div className="flex flex-wrap items-center gap-3">
            <button
              onClick={lookup}
              disabled={!ids.length || loading}
              className="btn btn-primary text-sm disabled:opacity-40"
            >
              {loading ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />} Look
              up
            </button>
            <label className="flex items-center gap-2 text-xs text-ink-muted cursor-pointer select-none">
              <input
                type="checkbox"
                checked={deep}
                onChange={(e) => setDeep(e.target.checked)}
                className="accent-[var(--accent)]"
              />
              <Zap size={12} className="text-accent" />
              Resolve exact files (live ENA / GEO — sizes + checksums)
            </label>
          </div>
          {deep && (
            <p className="text-2xs text-ink-subtle mt-2">
              Queries the European Nucleotide Archive &amp; GEO for the real file list with
              byte-exact sizes and MD5 checksums. Slightly slower; turn off for instant pointers.
            </p>
          )}
        </section>

        {Object.keys(res).length > 0 && (
          <section className="space-y-3 mb-5">
            {Object.entries(res).map(([id, dls]) => (
              <article key={id} className="card p-5">
                <div className="mb-3 flex items-center justify-between gap-2">
                  <span className="badge badge-sky font-mono">{id}</span>
                  <span className="text-2xs text-ink-subtle flex items-center gap-2">
                    {totals[id] && (
                      <span className="inline-flex items-center gap-1 text-ink-muted font-medium">
                        <HardDrive size={11} /> {totals[id]}
                      </span>
                    )}
                    {dls.length} file{dls.length === 1 ? '' : 's'}
                  </span>
                </div>
                {!dls.length ? (
                  <p className="text-sm text-ink-subtle">No options found.</p>
                ) : (
                  <div className="space-y-1.5 max-h-[420px] overflow-y-auto">
                    {dls.map((dl, i) => (
                      <div
                        key={i}
                        className="flex items-center gap-2.5 p-2.5 bg-canvas-subtle rounded-md border border-line-subtle"
                      >
                        <span className={`badge ${B[dl.file_type] || 'badge-gray'}`}>
                          {dl.file_type.toUpperCase()}
                        </span>
                        <span className="flex-1 text-sm text-ink-muted truncate" title={dl.label}>
                          {dl.label}
                        </span>
                        {dl.file_size_human && (
                          <span className="text-2xs text-ink-subtle font-mono whitespace-nowrap">
                            {dl.file_size_human}
                          </span>
                        )}
                        {dl.checksum_note && (
                          <span
                            className="text-[var(--success)] inline-flex items-center"
                            title={dl.checksum_note}
                            aria-label="MD5 checksum available"
                          >
                            <ShieldCheck size={12} />
                          </span>
                        )}
                        {dl.url && (
                          <a
                            href={dl.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-xs text-accent hover:underline flex items-center gap-0.5"
                          >
                            Open <ExternalLink size={11} />
                          </a>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </article>
            ))}
          </section>
        )}

        {ids.length > 0 && (
          <section className="card p-5 mb-5">
            <div className="section-label mb-3">Bulk download script</div>
            <p className="text-xs text-ink-muted mb-3">
              Generates a manifest covering every catalogued asset for the IDs above, filtered to the
              file types you pick.
            </p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
              <div>
                <div className="text-xs text-ink-muted mb-2 font-medium">
                  File types
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {FILE_TYPES.map((t) => (
                    <button
                      key={t.id}
                      onClick={() => tog(t.id)}
                      className={`px-2.5 py-1 text-xs rounded-md border font-medium transition-colors ${
                        fileTypes.includes(t.id)
                          ? 'bg-accent-bg border-accent-border text-accent'
                          : 'bg-white border-line text-ink-muted'
                      }`}
                    >
                      {t.label}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <div className="text-xs text-ink-muted mb-2 font-medium">
                  Format
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {FORMATS.map((f) => (
                    <button
                      key={f.v}
                      onClick={() => setFmt(f.v)}
                      title={f.desc}
                      className={`px-3 py-1 text-xs rounded-md border font-medium transition-colors ${
                        fmt === f.v
                          ? 'bg-accent-bg border-accent-border text-accent'
                          : 'bg-white border-line text-ink-muted'
                      }`}
                    >
                      {f.l}
                    </button>
                  ))}
                </div>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2.5">
              <button
                onClick={generateScript}
                disabled={!fileTypes.length || !ids.length}
                className="btn btn-success text-sm disabled:opacity-40"
              >
                <Download size={14} /> Generate {fmt.toUpperCase()}
              </button>
              <button
                onClick={runEstimate}
                disabled={!fileTypes.length || !ids.length || estimating}
                className="btn btn-secondary text-sm inline-flex items-center gap-1 disabled:opacity-40"
                title="Resolve the exact file list and total size before downloading"
              >
                {estimating ? <Loader2 size={13} className="animate-spin" /> : <HardDrive size={13} />}{' '}
                Estimate size
              </button>
            </div>

            {estimate && (
              <div className="mt-4 card p-4 bg-canvas-subtle border-line-subtle">
                <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 mb-2">
                  <span className="text-lg font-semibold text-ink">
                    {estimate.total_size_human || 'unknown size'}
                  </span>
                  <span className="text-xs text-ink-muted">
                    {estimate.file_count.toLocaleString()} file{estimate.file_count === 1 ? '' : 's'} ·{' '}
                    {estimate.dataset_count} dataset{estimate.dataset_count === 1 ? '' : 's'}
                  </span>
                  {estimate.size_is_partial && (
                    <span className="text-2xs text-[var(--warning)]">
                      ({estimate.sized_file_count}/{estimate.file_count} files have known sizes)
                    </span>
                  )}
                </div>
                {estimate.by_source.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 mb-2">
                    {estimate.by_source.map((s) => (
                      <span key={s.source} className="badge badge-gray text-2xs">
                        {sourceLabel(s.source)}: {s.size_human || `${s.files} files`}
                      </span>
                    ))}
                  </div>
                )}
                {estimate.unresolved.length > 0 && (
                  <p className="text-2xs text-ink-subtle">
                    {estimate.unresolved.length} ID(s) not in the catalog:{' '}
                    <span className="font-mono">{estimate.unresolved.slice(0, 5).join(', ')}</span>
                    {estimate.unresolved.length > 5 && ` +${estimate.unresolved.length - 5} more`}
                  </p>
                )}
              </div>
            )}
          </section>
        )}

        <section className="card p-5 mb-5">
          <div className="section-label mb-3">Metadata download</div>
          <p className="text-sm text-ink-muted mb-3">
            Export unified sample metadata (tissue, disease, organism, assay, cell type, donor info).
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 text-xs">
              Up to
              <select
                value={metaLimit}
                onChange={(e) => setMetaLimit(Number(e.target.value))}
                className="input py-1 px-2 text-xs w-auto"
              >
                {METADATA_LIMITS.map((m) => (
                  <option key={m.v} value={m.v}>
                    {m.l}
                  </option>
                ))}
              </select>
              samples
            </label>
            <button
              onClick={() => downloadMeta('csv')}
              disabled={metaBusy != null}
              className="btn btn-secondary text-sm inline-flex items-center gap-1"
            >
              {metaBusy === 'csv' ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}{' '}
              CSV
            </button>
            <button
              onClick={() => downloadMeta('json')}
              disabled={metaBusy != null}
              className="btn btn-secondary text-sm inline-flex items-center gap-1"
            >
              {metaBusy === 'json' ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}{' '}
              JSON
            </button>
          </div>
        </section>

        <details className="card p-5 group">
          <summary className="cursor-pointer flex items-center gap-2 list-none">
            <ChevronDown
              size={14}
              className="text-ink-subtle transition-transform group-open:rotate-180"
            />
            <span className="section-label">Download tools — getting started</span>
          </summary>
          <div className="space-y-4 mt-4">
            <div>
              <h3 className="text-sm font-medium text-ink mb-1.5">
                SRA Toolkit
              </h3>
              <pre className="code-block text-2xs">{`# conda install -c bioconda sra-tools
prefetch SRR1234567
fastq-dump --split-files --gzip SRR1234567`}</pre>
            </div>
            <div>
              <h3 className="text-sm font-medium text-ink mb-1.5">curl + wget</h3>
              <pre className="code-block text-2xs">{`wget -r -np -nH --cut-dirs=6 \\
  https://ftp.ncbi.nlm.nih.gov/geo/series/GSEnnn/GSExxxxx/suppl/`}</pre>
            </div>
            <div>
              <h3 className="text-sm font-medium text-ink mb-1.5">Python (scanpy)</h3>
              <pre className="code-block text-2xs">{`import scanpy as sc
adata = sc.read_h5ad("downloaded_file.h5ad")
print(adata)`}</pre>
            </div>
          </div>
        </details>

        <p className="text-xs text-ink-subtle mt-6">
          Looking for a particular dataset?{' '}
          <button
            type="button"
            onClick={() => navigate('/explore')}
            className="text-accent hover:underline inline-flex items-center gap-1"
          >
            <Database size={11} /> Browse Explore <ArrowRight size={11} />
          </button>
        </p>
      </div>
    </div>
  );
}
