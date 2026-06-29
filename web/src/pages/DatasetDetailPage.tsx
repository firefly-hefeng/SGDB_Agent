import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { ArrowLeft, Download, ExternalLink, Link2, Copy, Check, ChevronDown, ChevronUp, Loader2, HardDrive, ShieldCheck, Zap } from 'lucide-react';
import { getDatasetDetail, getDownloads } from '../services/api';
import type { DatasetDetailResponse, DownloadOption } from '../types/api';
import { manifestAdd } from '../lib/manifest';
import { toast } from '../lib/toastApi';
import { sourceLabel } from '../lib/format';
import { ProvenanceBadge } from '../components/layout/ProvenanceBadge';
import { useT } from '../lib/i18n';

export default function DatasetDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { t } = useT();
  const [data, setData] = useState<DatasetDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Phase 36: on-demand deep resolution (exact files + sizes + MD5 from ENA/GEO).
  const [deepDls, setDeepDls] = useState<DownloadOption[] | null>(null);
  const [deepTotal, setDeepTotal] = useState<string | null>(null);
  const [deepLoading, setDeepLoading] = useState(false);

  useEffect(() => {
    if (!id) return;
    // Reset to skeleton + clear any prior deep-resolved files before the fetch.
    setLoading(true);
    setDeepDls(null);
    setDeepTotal(null);
    getDatasetDetail(id).then(setData).catch((e) => setError(e.message)).finally(() => setLoading(false));
  }, [id]);

  const resolveExact = async () => {
    if (!data) return;
    setDeepLoading(true);
    try {
      const resp = await getDownloads(data.entity_id, true);
      setDeepDls(resp.downloads as DownloadOption[]);
      setDeepTotal(resp.total_size_human ?? null);
      toast(`Resolved ${resp.downloads.length} exact file${resp.downloads.length === 1 ? '' : 's'}`);
    } catch (e) {
      toast(`Could not resolve exact files: ${e instanceof Error ? e.message : e}`, 'error');
    } finally {
      setDeepLoading(false);
    }
  };

  if (loading) return (
    <div className="flex-1 overflow-y-auto"><div className="max-w-[960px] mx-auto px-6 py-8">
      <div className="skeleton w-24 h-4 mb-5 rounded" /><div className="skeleton w-56 h-7 mb-3 rounded" /><div className="skeleton w-72 h-4 mb-8 rounded" />
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5"><div className="lg:col-span-2 space-y-5"><div className="skeleton h-40 rounded-lg" /><div className="skeleton h-52 rounded-lg" /></div><div className="skeleton h-52 rounded-lg" /></div>
    </div></div>
  );

  if (error || !data) return (
    <div className="flex-1 flex flex-col items-center justify-center gap-3 text-ink-subtle px-6 text-center">
      <p className="font-medium text-ink-muted">{t('dataset.notfound.title', 'Not in the curated catalog')}</p>
      <p className="text-sm max-w-md">
        {t('dataset.notfound.hint', 'This identifier was not found in the curated human catalog. It may exist in a live public archive — search for it with the Discover agent.')}
        {' '}<span className="font-mono text-ink-muted">{error || id}</span>
      </p>
      <div className="flex items-center gap-3 mt-1">
        <Link to={id ? `/discover?q=${encodeURIComponent(id)}` : '/discover'} className="btn text-sm inline-flex items-center gap-1">
          {t('dataset.notfound.discover', 'Search Discover')} <ExternalLink size={13} />
        </Link>
        <Link to="/explore" className="text-sm text-accent hover:underline flex items-center gap-1"><ArrowLeft size={13} /> {t('common.back', 'Back')}</Link>
      </div>
    </div>
  );

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-[960px] mx-auto px-6 py-8">
        <div className="flex items-center justify-between mb-5 gap-2">
          <Link to="/explore" className="inline-flex items-center gap-1 text-sm text-ink-subtle hover:text-accent transition-colors">
            <ArrowLeft size={13} /> Back to Explore
          </Link>
          <ProvenanceBadge />
        </div>
        <header className="page-header-band bg-canvas -mx-6 px-6 pb-5 mb-6">
          <div className="flex flex-wrap gap-1.5 mb-2">
            <span className="badge badge-sky font-mono">{data.entity_id}</span>
            <span className="badge badge-gray">{sourceLabel(data.source_database)}</span>
            <span className="badge badge-gray">{data.entity_type}</span>
          </div>
          <h1 className="text-xl font-semibold tracking-[-0.01em] mb-2">{data.title || data.entity_id}</h1>
          {data.description && <Description text={data.description} />}
        </header>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
          <div className="lg:col-span-2 space-y-5">
            <section className="card p-5">
              <h2 className="text-sm font-semibold text-ink mb-3">Metadata</h2>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-6 gap-y-3 text-sm">
                <Meta label="Organism" value={data.organism} />
                <Meta label="Source" value={sourceLabel(data.source_database)} />
                <Meta label="Samples" value={data.sample_count?.toLocaleString()} />
                <Meta label="Series" value={String(data.series?.length || 0)} />
                {data.pmid && <Meta label="PMID" value={data.pmid} link={`https://pubmed.ncbi.nlm.nih.gov/${data.pmid}`} />}
                {data.doi && <Meta label="DOI" value={data.doi} link={`https://doi.org/${data.doi}`} />}
              </div>
            </section>

            {data.samples.length > 0 && (
              <section className="card p-5">
                <h2 className="text-sm font-semibold text-ink mb-3">Samples <span className="badge badge-gray ml-1">{data.sample_count}</span></h2>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead><tr className="thead-row">
                      {['Sample ID', 'Tissue', 'Disease', 'Cell Type', 'Cells'].map((h, i) => (
                        <th key={h} className={`px-3 py-2 text-2xs font-semibold text-ink-muted uppercase tracking-[0.04em] ${i === 4 ? 'text-right' : 'text-left'}`}>{h}</th>
                      ))}
                    </tr></thead>
                    <tbody>
                      {data.samples.slice(0, 50).map((s, i) => (
                        <tr key={i} className={`border-b border-line-subtle ${i % 2 ? 'bg-canvas-subtle' : ''}`}>
                          <td className="px-3 py-1.5 font-mono text-accent">{s.sample_id as string || '—'}</td>
                          <td className="px-3 py-1.5 text-ink-muted">{s.tissue as string || '—'}</td>
                          <td className="px-3 py-1.5 text-ink-muted">{s.disease as string || '—'}</td>
                          <td className="px-3 py-1.5 text-ink-muted">{s.cell_type as string || '—'}</td>
                          <td className="px-3 py-1.5 text-ink-muted text-right tabular-nums">{s.n_cells != null ? Number(s.n_cells).toLocaleString() : '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {data.sample_count > 50 && <p className="text-2xs text-ink-subtle mt-2">Showing 50 of {data.sample_count.toLocaleString()}</p>}
                </div>
              </section>
            )}

            {data.cross_links.length > 0 && (
              <section className="card p-5">
                <h2 className="text-sm font-semibold text-ink mb-3 flex items-center gap-1.5"><Link2 size={13} className="text-ink-subtle" /> Cross-Database Links</h2>
                <div className="space-y-1">
                  {data.cross_links.map((lk, i) => (
                    <Link key={i} to={`/explore/${encodeURIComponent(lk.linked_id)}`} className="flex items-center gap-2.5 p-2 rounded-md hover:bg-canvas-subtle transition-colors">
                      <span className="badge badge-sky font-mono">{lk.linked_id}</span>
                      <span className="badge badge-gray">{lk.linked_database}</span>
                      <span className="text-2xs text-ink-subtle ml-auto">{lk.relationship_type}</span>
                    </Link>
                  ))}
                </div>
              </section>
            )}
          </div>

          <div><section className="card p-5 sticky top-16">
            <h2 className="text-sm font-semibold text-ink mb-3 flex items-center justify-between gap-1.5">
              <span className="flex items-center gap-1.5"><Download size={13} className="text-ink-subtle" /> Downloads</span>
              {deepTotal && <span className="text-2xs font-normal text-ink-muted inline-flex items-center gap-1"><HardDrive size={11} /> {deepTotal}</span>}
            </h2>
            {(() => {
              const dls = deepDls ?? data.downloads;
              return (
                <>
                  {!dls.length ? <p className="text-sm text-ink-subtle">No options available.</p>
                  : <div className="space-y-2 max-h-[480px] overflow-y-auto">{dls.map((dl, i) => <DlItem key={i} item={dl} entityId={data.entity_id} sourceDb={data.source_database} title={data.title} />)}</div>}
                  {!deepDls && (
                    <button
                      onClick={resolveExact}
                      disabled={deepLoading}
                      className="mt-3 w-full btn btn-secondary text-xs inline-flex items-center justify-center gap-1.5 disabled:opacity-40"
                      title="Query ENA / GEO for the exact file list with sizes and MD5 checksums"
                    >
                      {deepLoading ? <Loader2 size={12} className="animate-spin" /> : <Zap size={12} className="text-accent" />}
                      Resolve exact files (sizes + checksums)
                    </button>
                  )}
                  {dls.length > 0 && (
                    <button
                      onClick={() => {
                        const added = manifestAdd(
                          dls
                            .filter((d) => d.url)
                            .map((d) => ({
                              id: data.entity_id,
                              source_db: data.source_database,
                              source_url: d.url ?? '',
                              download_url: d.url ?? null,
                              file_type: d.file_type,
                              // size_estimate is a numeric byte count (ManifestPanel
                              // SUMS it); pass the exact bytes from deep resolution,
                              // not the human-readable string ("2.4 GB").
                              size_estimate: d.bytes ?? null,
                              title: data.title,
                            })),
                        );
                        toast(`Added ${added} file${added === 1 ? '' : 's'} to manifest`);
                      }}
                      className="mt-2 w-full btn btn-accent text-xs"
                    >
                      Add all to manifest
                    </button>
                  )}
                </>
              );
            })()}
          </section></div>
        </div>
      </div>
    </div>
  );
}

function Meta({ label, value, link }: { label: string; value?: string | null; link?: string }) {
  if (!value) return null;
  return <div>
    <div className="section-label mb-0.5">{label}</div>
    {link ? <a href={link} target="_blank" rel="noopener noreferrer" className="text-accent hover:underline flex items-center gap-1">{value}<ExternalLink size={11} /></a> : <div className="text-ink">{value}</div>}
  </div>;
}

function Description({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false);
  const truncated = text.length > 500;
  const shown = expanded || !truncated ? text : text.slice(0, 500).trimEnd() + '…';
  return (
    <div className="max-w-[640px]">
      <p className="text-base text-ink-muted leading-relaxed whitespace-pre-line">
        {shown}
      </p>
      {truncated && (
        <button
          onClick={() => setExpanded((v) => !v)}
          className="mt-1 text-xs text-accent hover:underline inline-flex items-center gap-0.5"
        >
          {expanded ? (
            <>
              <ChevronUp size={11} /> Show less
            </>
          ) : (
            <>
              <ChevronDown size={11} /> Show more ({text.length - 500} chars)
            </>
          )}
        </button>
      )}
    </div>
  );
}

function DlItem({
  item,
  entityId,
  sourceDb,
  title,
}: {
  item: DownloadOption;
  entityId: string;
  sourceDb: string;
  title: string | null;
}) {
  const [copied, setCopied] = useState(false);
  const B: Record<string, string> = { h5ad: 'badge-purple', rds: 'badge-green', fastq: 'badge-blue', bam: 'badge-sky', supplementary: 'badge-amber', matrix: 'badge-orange' };
  const copy = (t: string) => { navigator.clipboard.writeText(t); setCopied(true); setTimeout(() => setCopied(false), 2000); };
  const addOne = () => {
    if (!item.url) return;
    manifestAdd([
      {
        id: entityId,
        source_db: sourceDb,
        source_url: item.url,
        download_url: item.url,
        file_type: item.file_type,
        size_estimate: null,
        title,
      },
    ]);
    toast(`Added ${entityId} (${item.file_type}) to manifest`);
  };

  return <div className="p-3 bg-canvas-subtle rounded-lg border border-line-subtle">
    <div className="flex items-center gap-2 mb-1.5">
      <span className={`badge ${B[item.file_type] || 'badge-gray'}`}>{item.file_type.toUpperCase()}</span>
      <span className="text-sm text-ink flex-1 truncate" title={item.label}>{item.label}</span>
      {item.file_size_human && <span className="text-2xs text-ink-subtle font-mono whitespace-nowrap">{item.file_size_human}</span>}
      {item.checksum_note && <span className="text-[var(--success)]" title={item.checksum_note} aria-label="MD5 checksum available"><ShieldCheck size={12} /></span>}
    </div>
    {item.instructions && <p className="text-2xs text-ink-subtle mb-2 line-clamp-1">{item.instructions.split('\n')[0]}</p>}
    <div className="flex gap-1.5 flex-wrap">
      {item.url && (
        <a
          href={item.url}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={`Open ${item.label} in new tab`}
          className="btn btn-primary text-2xs py-1 px-2.5 rounded"
        >
          <ExternalLink size={11} /> Open
        </a>
      )}
      {item.url && (
        <button
          onClick={() => copy(item.url!)}
          aria-label={`Copy URL for ${item.label}`}
          className="btn btn-secondary text-2xs py-1 px-2.5 rounded"
        >
          {copied ? (
            <>
              <Check size={11} className="text-[var(--success)]" /> Copied
            </>
          ) : (
            <>
              <Copy size={11} /> Copy
            </>
          )}
        </button>
      )}
      {item.url && (
        <button
          onClick={addOne}
          title="Add this file to the global manifest"
          aria-label={`Add ${item.label} to manifest`}
          className="btn btn-secondary text-2xs py-1 px-2.5 rounded"
        >
          <Download size={11} /> Manifest
        </button>
      )}
    </div>
  </div>;
}
