import { useEffect, useState, useCallback } from 'react';
import { Link } from 'react-router-dom';
import {
  Database, Radio, Layers, FolderTree, ListTree, Microscope, AlertCircle,
  ArrowRight, ExternalLink, SearchCode, Download, BarChart3, Sparkles, X,
  Check, Images,
} from 'lucide-react';
import { getDashboardStats } from '../services/api';
import { listDiscoverySources } from '../services/discovery';
import { PageHeader } from '../components/ui/PageHeader';
import { DataAvailability } from '../components/ui/DataAvailability';
import { fmt } from '../lib/format';
import { useT } from '../lib/i18n';
import { ABOUT_SECTIONS } from '../content/aboutContent';
import type { Bi } from '../content/aboutContent';
import type { DashboardStats } from '../types/api';
import type { DiscoverySourcesResponse } from '../types/discovery';

const ICONS: Record<string, typeof Layers> = {
  Layers, Database, SearchCode, Radio, Download, BarChart3, Sparkles,
};

const FIG = (name: string) => `${import.meta.env.BASE_URL}about/${name}`;

// Additional thesis figures shown in the dense gallery (beyond the in-section ones).
const GALLERY = [
  ['arch_pipeline.png', 'Full-stack request pipeline'],
  ['data_collector.png', 'Metadata classification & collection'],
  ['data_etl.png', 'Five-stage harmonization ETL'],
  ['nlsql_understanding.png', 'Query understanding & intent'],
  ['nlsql_ontology.png', 'Five-step ontology expansion'],
  ['nlsql_sql.png', 'Three-candidate SQL generation'],
  ['api_dispatch.png', 'Concurrent federated dispatch'],
  ['api_intent.png', 'Bilingual intent parser'],
  ['download_matrix.png', 'Download-source capability matrix'],
] as const;

/**
 * About — a documentation portal for Singligent: a concise project overview, a
 * live at-a-glance of the catalog, then figure-rich sections distilled from the
 * system design (architecture, data engineering, the two agents, downloads,
 * evaluation, value), a figure gallery, the live discovery sources, and the
 * open-data / lab provenance. Every catalog number is fetched live.
 */
export default function AboutPage() {
  const { t, lang } = useT();
  const bi = useCallback((b: Bi) => (lang === 'zh' ? b.zh : b.en), [lang]);
  const [dash, setDash] = useState<DashboardStats | null>(null);
  const [sources, setSources] = useState<DiscoverySourcesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lightbox, setLightbox] = useState<{ src: string; cap: string } | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([getDashboardStats(), listDiscoverySources()])
      .then(([d, s]) => { if (!cancelled) { setDash(d); setSources(s); } })
      .catch((e) => { if (!cancelled) setError(String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!lightbox) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setLightbox(null); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [lightbox]);

  const bySource = dash?.by_source ?? [];
  const sampleSources = bySource.filter((s) => s.samples > 0);

  const glance = [
    { v: dash?.total_samples, l: t('about.tier.samples', 'Samples') },
    { v: dash?.total_projects, l: t('about.tier.projects', 'Projects') },
    { v: dash?.total_donors, l: t('about.glance.donors', 'Donors') },
    { v: dash?.total_celltypes, l: t('about.tier.celltypes', 'Cell types') },
    { v: dash?.total_sources, l: t('about.glance.sources', 'Sources') },
  ];

  const Figure = ({ name, caption, eager = false }: { name: string; caption: string; eager?: boolean }) => (
    <figure className="mt-4">
      <button
        type="button"
        onClick={() => setLightbox({ src: FIG(name), cap: caption })}
        className="block w-full rounded-lg border border-line bg-white overflow-hidden card-hover cursor-zoom-in"
        aria-label={`${t('about.fig.enlarge', 'Enlarge figure')}: ${caption}`}
      >
        <img src={FIG(name)} alt={caption} loading={eager ? 'eager' : 'lazy'} className="w-full h-auto" />
      </button>
      <figcaption className="mt-2 text-2xs text-ink-subtle leading-relaxed flex gap-1.5">
        <span className="text-accent font-semibold shrink-0">{t('about.fig.label', 'Figure')}</span>
        <span>{caption}</span>
      </figcaption>
    </figure>
  );

  return (
    <div className="flex-1 overflow-y-auto bg-canvas-subtle">
      <PageHeader
        eyebrow={t('about.eyebrow', 'About the system')}
        title={t('about.title', 'A dual-agent portal for single-cell metadata')}
        description={t('about.desc',
          'How Singligent is built — its architecture, the harmonized catalog behind it, the two agents that drive search and live discovery, reproducible downloads, and how the system is evaluated. Every catalog figure on this page is fetched live.')}
      />

      <div className="max-w-[1280px] mx-auto px-6 py-7 space-y-10">
        {error && (
          <div role="alert" className="flex items-start gap-2 text-sm text-[var(--error)] bg-[color-mix(in_srgb,var(--error)_8%,white)] border border-[color-mix(in_srgb,var(--error)_25%,white)] rounded-md px-3 py-2">
            <AlertCircle size={14} className="mt-0.5 shrink-0" />
            <span>{t('about.error', 'Could not load live data coverage.')} {error}</span>
          </div>
        )}

        {/* ── Overview: pitch + the system-at-a-glance figure + live stat strip ── */}
        <section>
          <p className="text-base text-ink-muted leading-relaxed max-w-[60rem]">
            {t('about.overview.lede',
              'Singligent unifies mainstream human single-cell RNA-seq metadata and pairs it with two complementary AI agents: a natural-language → SQL agent over a curated, harmonized catalog, and an api-routing agent that fans one query out live across public archives. The result is a single place to discover, refine, and reproducibly acquire single-cell datasets — in plain English or 中文.')}
          </p>
          <Figure name="overview.png" eager
            caption={t('about.fig.overview', 'System architecture and catalog at scale — the dual-agent infrastructure (Discover → Select → Acquire), the harmonized data resource, and its biological & disease coverage.')} />

          <div className="mt-5 grid grid-cols-2 md:grid-cols-5 gap-3">
            {glance.map((g) => (
              <div key={g.l} className="card px-4 py-3 text-center">
                <div className="text-2xl font-semibold text-ink tabular-nums leading-none mb-1">
                  {loading ? <span className="opacity-40">…</span> : fmt(g.v)}
                </div>
                <div className="text-2xs uppercase tracking-wider text-ink-subtle">{g.l}</div>
              </div>
            ))}
          </div>
        </section>

        {/* ── Documentation sections (distilled from the system design) ── */}
        <div className="space-y-12">
          <div className="flex items-center gap-2 text-2xs uppercase tracking-wider text-accent font-semibold">
            <span className="w-4 h-px bg-accent/60" /> {t('about.docs.label', 'How the system works')}
          </div>
          {/* On-this-page TOC — scrolls the inner container to each section */}
          <nav aria-label={t('about.toc.aria', 'On this page')} className="flex flex-wrap gap-1.5 -mt-8">
            {ABOUT_SECTIONS.map((s) => (
              <button
                key={s.key}
                type="button"
                onClick={() => document.getElementById(`about-${s.key}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
                className="text-2xs font-medium px-2.5 py-1 rounded-full border border-line bg-white text-ink-muted hover:text-accent hover:border-accent-border transition-colors"
              >
                {bi(s.title)}
              </button>
            ))}
          </nav>
          {ABOUT_SECTIONS.map((s) => {
            const Icon = ICONS[s.icon] ?? Layers;
            return (
              <section key={s.key} className="scroll-mt-20" id={`about-${s.key}`}>
                <div className="flex items-start gap-3 mb-2">
                  <span className="mt-0.5 inline-flex items-center justify-center w-8 h-8 rounded-lg bg-accent-bg text-accent shrink-0">
                    <Icon size={17} />
                  </span>
                  <div className="min-w-0">
                    <h2 className="text-xl font-semibold tracking-tight text-ink">{bi(s.title)}</h2>
                  </div>
                </div>
                <p className="text-sm text-ink-muted leading-relaxed max-w-[60rem] mb-4">{bi(s.lede)}</p>
                <ul className="grid sm:grid-cols-2 gap-x-6 gap-y-2 max-w-[68rem]">
                  {s.points.map((p, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm text-ink-muted leading-snug">
                      <Check size={14} className="mt-0.5 shrink-0 text-accent" />
                      <span>{bi(p)}</span>
                    </li>
                  ))}
                </ul>
                {s.figure && <Figure name={s.figure} caption={bi(s.caption)} />}
              </section>
            );
          })}
        </div>

        {/* ── Figure gallery (dense previews) ── */}
        <section>
          <div className="flex items-center gap-2 mb-3">
            <Images size={16} className="text-accent" />
            <h2 className="text-lg font-semibold tracking-tight text-ink">{t('about.gallery.title', 'Design figure gallery')}</h2>
          </div>
          <p className="text-sm text-ink-muted max-w-[60rem] mb-4">
            {t('about.gallery.sub', 'Additional design figures — click any to enlarge.')}
          </p>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-3 gap-3">
            {GALLERY.map(([name, cap]) => (
              <button key={name} type="button" onClick={() => setLightbox({ src: FIG(name), cap })}
                className="group rounded-lg border border-line bg-white overflow-hidden card-hover cursor-zoom-in text-left">
                <div className="aspect-[16/10] overflow-hidden bg-canvas-subtle">
                  <img src={FIG(name)} alt={cap} loading="lazy"
                    className="w-full h-full object-cover object-top group-hover:scale-[1.02] transition-transform" />
                </div>
                <div className="px-2.5 py-1.5 text-2xs text-ink-muted truncate">{cap}</div>
              </button>
            ))}
          </div>
        </section>

        {/* ── Data availability / bulk download ── */}
        <DataAvailability />

        {/* ── Live discovery sources ── */}
        <section>
          <div className="flex items-center gap-2 mb-1">
            <Radio size={16} className="text-accent" />
            <h2 className="text-lg font-semibold tracking-tight text-ink">{t('about.live.title', 'Live discovery databases')}</h2>
            {sources && <span className="badge badge-gray tabular-nums">{sources.sources.length}</span>}
          </div>
          <p className="text-sm text-ink-muted max-w-[60rem] mb-4">
            {t('about.live.sub', 'Queried in parallel on demand by the api-routing agent. SRA and the Single-Cell Expression Atlas are live-only — not part of the curated catalog.')}
          </p>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {(sources?.sources ?? []).map((src) => {
              const curated = sampleSources.some((cs) => cs.name.toLowerCase() === src.id.toLowerCase());
              return (
                <div key={src.id} className="card p-4">
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <h4 className="text-sm font-semibold text-ink">{src.name}</h4>
                    <span className={`badge ${curated ? 'badge-emerald' : 'badge-amber'} text-2xs`}>
                      {curated ? t('about.src.both', 'curated + live') : t('about.src.live', 'live-only')}
                    </span>
                  </div>
                  <p className="text-2xs text-ink-subtle mb-1.5">{src.full_name}</p>
                  <p className="text-xs text-ink-muted leading-snug">{src.description}</p>
                  <a href={`https://${src.host}`} target="_blank" rel="noreferrer"
                    className="mt-2 inline-flex items-center gap-0.5 text-2xs text-accent hover:underline">
                    {src.host}<ExternalLink size={9} />
                  </a>
                </div>
              );
            })}
          </div>
        </section>

        {/* ── Curated tiers (live) ── */}
        <section>
          <div className="flex items-center gap-2 mb-1">
            <Database size={16} className="text-accent" />
            <h2 className="text-lg font-semibold tracking-tight text-ink">{t('about.tiers.title', 'Curated record tiers')}</h2>
          </div>
          <p className="text-sm text-ink-muted max-w-[60rem] mb-4">
            {t('about.tiers.sub', 'The catalog is browsable at four record levels — counts are live; fine-grained cell-type composition is CellxGene-only.')}
          </p>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            {[
              { icon: Layers, label: t('about.tier.samples', 'Samples'), value: dash?.total_samples, to: '/explore' },
              { icon: FolderTree, label: t('about.tier.projects', 'Projects'), value: dash?.total_projects, to: '/projects' },
              { icon: ListTree, label: t('about.tier.series', 'Series'), value: dash?.total_series, to: '/series' },
              { icon: Microscope, label: t('about.tier.celltypes', 'Cell types'), value: dash?.total_celltypes, note: t('about.celltypes.note', 'CellxGene-only composition.') },
            ].map((tier) => {
              const Icon = tier.icon;
              const inner = (
                <>
                  <div className="flex items-center justify-between mb-2">
                    <Icon size={16} className="text-accent" />
                    {tier.to && <ArrowRight size={13} className="text-ink-subtle group-hover:translate-x-0.5 transition-transform" />}
                  </div>
                  <p className="text-2xl font-semibold text-ink tabular-nums leading-none mb-1">
                    {loading ? <span className="opacity-40">…</span> : fmt(tier.value)}
                  </p>
                  <p className="text-2xs uppercase tracking-wider text-ink-subtle">{tier.label}</p>
                  {tier.note && <p className="text-2xs text-ink-muted mt-1">{tier.note}</p>}
                </>
              );
              return tier.to
                ? <Link key={tier.label} to={tier.to} className="card card-hover p-4 group block">{inner}</Link>
                : <div key={tier.label} className="card p-4 block">{inner}</div>;
            })}
          </div>
        </section>

        {/* ── Project & lab ── */}
        <section className="border-t border-line pt-6 text-sm text-ink-muted">
          <p>
            {t('about.project', 'Singligent is built and maintained at Nanjing University. Public portal:')}{' '}
            <a href="https://biobigdata.nju.edu.cn/singligent/" className="text-accent hover:underline" target="_blank" rel="noreferrer">biobigdata.nju.edu.cn/singligent</a>
            {' · '}{t('about.lab', 'Lab')}:{' '}
            <a href="https://compbio.nju.edu.cn/" className="text-accent hover:underline" target="_blank" rel="noreferrer">compbio.nju.edu.cn</a>.
          </p>
        </section>
      </div>

      {/* ── Lightbox ── */}
      {lightbox && (
        <div
          role="dialog" aria-modal="true" aria-label={lightbox.cap}
          className="fixed inset-0 z-50 bg-ink/80 backdrop-blur-sm flex flex-col items-center justify-center p-4 sm:p-8 animate-fade-in"
          onClick={() => setLightbox(null)}
        >
          <button
            type="button"
            className="absolute top-4 right-4 text-white/80 hover:text-white p-2 rounded-full bg-white/10"
            aria-label={t('common.close', 'Close')}
            onClick={() => setLightbox(null)}
          >
            <X size={20} />
          </button>
          <img src={lightbox.src} alt={lightbox.cap}
            className="max-w-full max-h-[82vh] object-contain rounded-lg shadow-2xl bg-white"
            onClick={(e) => e.stopPropagation()} />
          <p className="mt-3 text-xs text-white/80 max-w-[60rem] text-center leading-relaxed">{lightbox.cap}</p>
        </div>
      )}
    </div>
  );
}
