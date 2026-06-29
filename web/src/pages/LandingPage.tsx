import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, Radio, Database, Code2, Github, Sparkles } from 'lucide-react';
import { useStats } from '../hooks/useStats';
import { useReveal } from '../hooks/useReveal';
import { fetchFeaturedCollections } from '../services/collections';
import { fmt, sourceLabel } from '../lib/format';
import { useT } from '../lib/i18n';
import type { FeaturedCollection } from '../types/collections';

const APP_VERSION: string =
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (typeof __APP_VERSION__ !== 'undefined' ? __APP_VERSION__ : '0.0.0') as any;

export default function LandingPage() {
  const { dashboard, stats, loading } = useStats();
  const { t, lang } = useT();
  const [collections, setCollections] = useState<FeaturedCollection[]>([]);
  const [collectionsLoading, setCollectionsLoading] = useState(true);

  useEffect(() => {
    fetchFeaturedCollections()
      .then((r) => setCollections(r.collections.filter((c) => c.sample_count > 0)))
      .catch(() => setCollections([]))
      .finally(() => setCollectionsLoading(false));
  }, []);

  // Reveal-on-scroll for tagged sections/cards; re-scan once async data lands.
  useReveal([dashboard, collections.length]);

  // Derive source-count from live data so the hint never drifts from reality.
  const liveSourceCount =
    dashboard?.total_sources ?? stats?.source_databases?.length ?? null;

  const headlineStats = [
    {
      label: 'Samples',
      value: dashboard?.total_samples ?? stats?.total_samples ?? null,
      hint: liveSourceCount
        ? `Across ${liveSourceCount} sources, deduplicated.`
        : 'Deduplicated across all source databases.',
    },
    {
      label: 'Donors',
      value: dashboard?.total_donors ?? null,
      hint: 'Distinct individuals, where donor IDs are annotated.',
    },
    {
      label: 'Projects',
      value: dashboard?.total_projects ?? stats?.total_projects ?? null,
      hint: 'Studies catalogued.',
    },
    {
      label: 'Sources',
      value:
        dashboard?.total_sources ??
        stats?.source_databases?.length ??
        null,
      hint: 'GEO, CellxGene, HCA, EBI…',
    },
    {
      label: 'Cell types',
      value: dashboard?.total_celltypes ?? stats?.total_celltypes ?? null,
      hint: 'Ontology-aligned (CL).',
    },
  ];

  const sourceTiles: { name: string; key: string; tagline: string; samples?: number }[] =
    (dashboard?.by_source ?? []).slice(0, 12).map((s) => ({
      name: s.name,
      key: s.name.toLowerCase(),
      tagline: `${fmt(s.samples)} samples · ${fmt(s.projects)} projects`,
      samples: s.samples,
    }));

  // The catalog's four record levels — counts live, per-tier source counts are
  // structural. Samples/Projects/Series are browsable pages; cell types are a
  // standardized data dimension shown here (browse them via the Samples cell-type
  // facet — there is no separate cell-type page).
  const recordTypes: {
    to?: string; labelKey: string; label: string; taglineKey: string; value: number | null; sources: number;
  }[] = [
    { to: '/explore', labelKey: 'about.tier.samples', label: 'Samples', taglineKey: 'landing.org.rt.samples', value: dashboard?.total_samples ?? null, sources: 8 },
    { to: '/projects', labelKey: 'about.tier.projects', label: 'Projects', taglineKey: 'landing.org.rt.projects', value: dashboard?.total_projects ?? null, sources: 5 },
    { to: '/series', labelKey: 'about.tier.series', label: 'Series', taglineKey: 'landing.org.rt.series', value: dashboard?.total_series ?? null, sources: 3 },
    { labelKey: 'nav.celltypes', label: 'Cell types', taglineKey: 'landing.org.rt.celltypes', value: dashboard?.total_celltypes ?? null, sources: 1 },
  ];

  // Projects & Series are tier-views inside Explore (reached via the target-level
  // tabs), not standalone destinations — so they're omitted from the page guide.
  const pagesGuide: { to: string; labelKey: string; label: string; guideKey: string }[] = [
    { to: '/explore', labelKey: 'nav.explore', label: 'Explore', guideKey: 'guide.explore' },
    { to: '/search', labelKey: 'nav.advanced', label: 'Advanced', guideKey: 'guide.advanced' },
    { to: '/discover', labelKey: 'nav.discover', label: 'Discover', guideKey: 'guide.discover' },
    { to: '/downloads', labelKey: 'nav.downloads', label: 'Downloads', guideKey: 'guide.downloads' },
    { to: '/workspace', labelKey: 'nav.workspace', label: 'Workspace', guideKey: 'guide.workspace' },
    { to: '/stats', labelKey: 'nav.stats', label: 'Statistics', guideKey: 'guide.stats' },
    { to: '/about', labelKey: 'nav.about', label: 'About data', guideKey: 'guide.about' },
  ];

  return (
    <div id="home-scroll" className="flex-1 overflow-y-auto">
      {/* Hero band */}
      <section className="relative bg-ink text-white pb-12 pt-24 md:pt-32 md:pb-20 px-6 overflow-hidden">
        {/* Scientific hero illustration (single cells + data network) behind the
            headline; a left-to-right gradient keeps the title fully legible. */}
        <div className="absolute inset-0 z-0 pointer-events-none" aria-hidden="true">
          <img
            src={`${import.meta.env.BASE_URL}brand/hero.jpg`}
            alt=""
            className="absolute inset-0 w-full h-full object-cover object-right opacity-80 hero-fade-in"
          />
          <div className="absolute inset-0 bg-gradient-to-r from-ink via-ink/85 to-ink/30" />
          <div className="absolute inset-0 hero-glow opacity-20" />
        </div>
        <div className="relative z-10 max-w-[1280px] mx-auto">
          <span className="inline-flex items-center gap-1.5 text-2xs uppercase tracking-wider text-white/60 mb-4 bg-white/5 border border-white/10 rounded-full px-2.5 py-1">
            <span className="w-1.5 h-1.5 rounded-full bg-[var(--success)]" /> v{APP_VERSION} · publication-grade
          </span>
          <h1 className="text-4xl md:text-5xl lg:text-6xl font-semibold tracking-tight leading-[1.1] mb-3 max-w-[840px]">
            {t('landing.hero.title', 'A unified portal for single-cell RNA-seq metadata.')}
          </h1>
          <p className="text-lg text-white/70 max-w-[640px] mb-7 leading-relaxed">
            {dashboard?.total_samples ? (
              <>
                {lang === 'zh' ? '检索 ' : 'Search across '}
                <span className="font-medium text-white">{fmt(dashboard.total_samples)}</span>{' '}
                {t('landing.hero.sub.b',
                  'curated scRNA-seq samples — then run parallel live queries against six public databases when you need the very latest submissions.')}
              </>
            ) : (
              t('landing.hero.sub.a',
                'Search a curated catalogue of human single-cell studies — by tissue, disease, assay, donor or free-text, in plain English or 中文.')
            )}
          </p>
          <div className="flex flex-wrap items-center gap-3 mb-12">
            <Link
              to="/explore"
              className="btn btn-accent text-sm px-4 py-2.5 inline-flex items-center gap-1.5"
            >
              {t('landing.cta.explore', 'Explore the catalog')} <ArrowRight size={14} />
            </Link>
            <Link
              to="/discover"
              className="btn text-sm px-4 py-2.5 inline-flex items-center gap-1.5 bg-white/10 hover:bg-white/15 text-white border border-white/10"
            >
              <Radio size={14} /> {t('landing.cta.discovery', 'Live discovery')}
            </Link>
            <Link to="/search" className="text-sm text-white/70 hover:text-white">
              {t('landing.cta.nl', 'Try a natural-language query →')}
            </Link>
          </div>

          {/* Big-numbers */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3 md:gap-6">
            {headlineStats.map((s, i) => (
              <div
                key={s.label}
                className="bg-white/[0.04] border border-white/[0.08] rounded-lg px-4 py-3 backdrop-blur-sm transition-colors duration-200 hover:bg-white/[0.07] hover:border-white/15"
              >
                <p className="text-2xs uppercase tracking-wider text-white/65 mb-1">{s.label}</p>
                <p className={`text-3xl font-semibold tabular-nums ${i === 0 ? 'text-[var(--accent-2)]' : 'text-white'}`}>
                  {loading && s.value == null ? <span className="opacity-50">…</span> : fmt(s.value)}
                </p>
                <p className="text-2xs text-white/70 mt-0.5 leading-snug min-h-[2.4em]">{s.hint}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* How this portal is organized — system composition + per-page guide */}
      <section className="px-6 py-12 bg-white border-b border-line">
        <div className="max-w-[1280px] mx-auto">
          <h2 className="text-xl font-semibold tracking-tight text-ink text-center">
            {t('landing.org.title', 'How this portal is organized')}
          </h2>
          <p className="text-sm text-ink-muted mt-1.5 max-w-[820px] mx-auto text-center leading-relaxed">
            {t('landing.org.sub', 'Two complementary agents over one dataset. A curated, deduplicated catalog you browse and query instantly, plus a live federation that reaches public archives on demand. The catalog is browsable at three record levels — samples, projects and series.')}
          </p>

          <div className="grid md:grid-cols-2 gap-4 mt-6">
            {/* Curated catalog tier */}
            <div className="card p-5" data-reveal>
              <div className="flex items-center gap-2 mb-1.5">
                <Database size={16} className="text-accent" />
                <h3 className="text-base font-semibold text-ink">
                  {t('landing.org.curated.title', 'Curated catalog — NL→SQL agent')}
                </h3>
              </div>
              <p className="text-xs text-ink-muted leading-relaxed mb-3">
                {t('landing.org.curated.body', 'Harmonized & ontology-aligned locally for instant faceted + natural-language search. Browsable at three record levels (counts live):')}
              </p>
              <div className="grid grid-cols-2 gap-2">
                {recordTypes.map((rt) => {
                  const inner = (
                    <>
                      <div className="text-lg font-semibold text-ink tabular-nums leading-none">
                        {rt.value == null ? <span className="opacity-40">…</span> : fmt(rt.value)}
                      </div>
                      <div className="text-2xs font-medium text-ink mt-0.5">{t(rt.labelKey, rt.label)}</div>
                      <div className="text-2xs text-ink-subtle">
                        {t(rt.taglineKey, '')} · {rt.sources} {t('landing.org.sources_n', 'sources')}
                      </div>
                    </>
                  );
                  // Cell types: a data dimension shown here but with no separate page
                  // (browse via the Samples cell-type facet) → non-link card.
                  return rt.to ? (
                    <Link key={rt.label} to={rt.to} className="rounded-md border border-line-subtle bg-canvas-subtle p-2.5 hover:border-accent hover:bg-accent-bg/40 transition-colors group">
                      {inner}
                    </Link>
                  ) : (
                    <div key={rt.label} className="rounded-md border border-line-subtle bg-canvas-subtle p-2.5">
                      {inner}
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Live discovery tier */}
            <div className="card p-5 rd-2" data-reveal>
              <div className="flex items-center gap-2 mb-1.5">
                <Radio size={16} className="text-accent" />
                <h3 className="text-base font-semibold text-ink">
                  {t('landing.org.live.title', 'Live discovery — federation agent')}
                </h3>
              </div>
              <p className="text-xs text-ink-muted leading-relaxed mb-3">
                {t('landing.org.live.body', 'One query fanned out in parallel to six public archives, with mirror detection and cross-source dedup — for the newest submissions or sources not yet ingested (SRA, SCEA).')}
              </p>
              <div className="flex flex-wrap gap-1.5">
                {['GEO', 'SRA', 'EBI BioStudies', 'SCEA', 'CellxGene', 'HCA'].map((db) => (
                  <span key={db} className="badge badge-gray font-mono text-2xs">{db}</span>
                ))}
              </div>
              <Link to="/discover" className="mt-3 text-xs text-accent inline-flex items-center gap-1 hover:gap-1.5 transition-all">
                {t('landing.cta.discovery', 'Live discovery')} <ArrowRight size={12} />
              </Link>
            </div>
          </div>

          {/* Per-page guide */}
          <h3 className="text-sm font-semibold text-ink mt-8 mb-3">
            {t('landing.guide.title', 'What each page does')}
          </h3>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-2">
            {pagesGuide.map((p) => (
              <Link key={p.to} to={p.to} className="flex items-start gap-2 rounded-md border border-line-subtle p-2.5 hover:border-accent hover:bg-accent-bg/30 transition-colors">
                <ArrowRight size={13} className="text-accent shrink-0 mt-0.5" />
                <div className="min-w-0">
                  <div className="text-xs font-semibold text-ink">{t(p.labelKey, p.label)}</div>
                  <div className="text-2xs text-ink-muted leading-snug">{t(p.guideKey, '')}</div>
                </div>
              </Link>
            ))}
          </div>
        </div>
      </section>

      {/* Source tiles */}
      {sourceTiles.length > 0 && (
        <section className="px-6 py-12 bg-white border-b border-line">
          <div className="max-w-[1280px] mx-auto">
            <header className="flex items-end justify-between mb-6 gap-3">
              <div>
                <h2 className="text-xl font-semibold tracking-tight text-[var(--text)]">
                  {t('landing.sources.title', 'Source databases')}
                </h2>
                <p className="text-sm text-ink-muted mt-1">
                  {t('landing.sources.sub', 'Browse by where the data came from. Counts are live.')}
                </p>
              </div>
              <Link
                to="/about"
                className="text-sm text-accent hover:underline inline-flex items-center gap-1"
              >
                {t('nav.about', 'About data')} <ArrowRight size={12} />
              </Link>
            </header>
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-2">
              {sourceTiles.map((s, i) => (
                <Link
                  key={s.key}
                  to={`/explore?source_database=${encodeURIComponent(s.name)}`}
                  data-reveal
                  className={`card card-hover p-3 group rd-${(i % 4) + 1}`}
                >
                  <div className="flex items-center justify-between mb-1.5">
                    <Database
                      size={16}
                      className="text-accent group-hover:scale-110 transition-transform"
                    />
                    <span className="badge badge-gray font-mono text-2xs">{sourceLabel(s.name)}</span>
                  </div>
                  <p className="text-xs font-semibold text-[var(--text)] tabular-nums">
                    {fmt(s.samples)}
                  </p>
                  <p className="text-2xs text-ink-subtle line-clamp-1">
                    {s.tagline}
                  </p>
                </Link>
              ))}
            </div>
          </div>
        </section>
      )}

      {/* Featured collections */}
      {(collectionsLoading || collections.length > 0) && (
        <section className="px-6 py-12 bg-canvas">
          <div className="max-w-[1280px] mx-auto">
            <header className="flex items-end justify-between mb-6 gap-3">
              <div>
                <p className="text-2xs uppercase tracking-wider text-ink-subtle font-medium mb-1">
                  {t('landing.featured.sub', 'Curated, ready-to-explore subsets.')}
                </p>
                <h2 className="text-xl font-semibold tracking-tight text-ink">
                  {t('landing.featured.title', 'Featured collections')}
                </h2>
                <p className="text-sm text-ink-muted mt-1">
                  Hand-picked cross-source bundles. Counts are live; click into Explore to refine.
                </p>
              </div>
            </header>
            {collectionsLoading ? (
              <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-3">
                {Array.from({ length: 6 }).map((_, i) => (
                  <div key={i} className="skeleton h-[140px] rounded-md" />
                ))}
              </div>
            ) : (
              <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-3">
                {collections.map((c) => (
                  <CollectionCard key={c.slug} collection={c} />
                ))}
              </div>
            )}
          </div>
        </section>
      )}

      {/* What you can do */}
      <section className="px-6 py-12 bg-canvas-subtle">
        <div className="max-w-[1280px] mx-auto">
          <h2 className="text-xl font-semibold tracking-tight text-ink mb-6">
            {t('landing.do.title', 'What you can do here')}
          </h2>
          <div className="grid md:grid-cols-3 gap-4" data-reveal>
            <FeatureCard
              to="/explore"
              icon={<Database size={16} className="text-accent" />}
              title={t('landing.do.explore.title', 'Explore the catalog')}
              body={
                liveSourceCount && lang === 'en'
                  ? `Faceted browse across ${liveSourceCount} unified sources. Filter by tissue, disease, assay, sample type, cell count.`
                  : t('landing.do.explore.body',
                      'Faceted browse across the unified sources. Filter by tissue, disease, assay, sample type, cell count.')
              }
              cta={t('landing.open', 'Open')}
            />
            <FeatureCard
              to="/search"
              icon={<Code2 size={16} className="text-accent" />}
              title={t('landing.do.nl.title', 'Natural-language search')}
              body={t('landing.do.nl.body',
                'Ask in plain English or 中文. The agent parses your intent, expands ontologies, and runs SQL across the unified DB.')}
              cta={t('landing.open', 'Open')}
            />
            <FeatureCard
              to="/discover"
              icon={<Radio size={16} className="text-accent" />}
              title={t('landing.do.discover.title', 'Live cross-DB discovery')}
              body={t('landing.do.discover.body',
                'Stream results from GEO, SRA, EBI BioStudies, Single-Cell Expression Atlas, CellxGene and HCA in parallel. Mirrors and dedup included.')}
              cta={t('landing.open', 'Open')}
            />
          </div>
        </div>
      </section>

      {/* Programmatic access */}
      <section className="px-6 py-12 bg-white border-t border-line">
        <div className="max-w-[1280px] mx-auto">
          <header className="mb-4">
            <p className="text-2xs uppercase tracking-wider text-ink-subtle mb-1">
              For developers
            </p>
            <h2 className="text-xl font-semibold tracking-tight text-[var(--text)]">
              Programmatic access
            </h2>
            <p className="text-sm text-ink-muted mt-1">
              Every page-level interaction is also a REST endpoint. The Discover endpoint streams
              SSE for low-latency UX.
            </p>
          </header>
          <div className="grid md:grid-cols-2 gap-3">
            <pre className="code-block text-2xs leading-relaxed overflow-x-auto whitespace-pre">{`# Python — Explore the curated catalog
import requests
r = requests.post(
    "http://localhost:8000/scdbAPI/explore",
    json={"tissues": ["liver"], "diseases": ["cancer"]},
)
print(r.json()["total_count"])`}</pre>
            <pre className="code-block text-2xs leading-relaxed overflow-x-auto whitespace-pre">{`# Bash — Live cross-database discovery (SSE)
curl -N -X POST http://localhost:8000/scdbAPI/discover/stream \\
  -H "Content-Type: application/json" \\
  -d '{"query":"Alzheimer hippocampus scRNA-seq"}'`}</pre>
          </div>
          <p className="text-xs text-ink-subtle mt-3">
            Full API map at <code>/docs</code> and <code>/redoc</code> on the server.
          </p>
        </div>
      </section>

      {/* Footer */}
      <footer className="bg-[var(--text)] text-white/80 px-6 py-10">
        <div className="max-w-[1280px] mx-auto">
          <div className="grid sm:grid-cols-2 md:grid-cols-4 gap-6 text-xs mb-8">
            <div>
              <h3 className="font-semibold text-white mb-2 text-sm">{t('footer.browse', 'Browse')}</h3>
              <ul className="space-y-1.5 text-white/60">
                <li><Link to="/explore" className="hover:text-white">{t('nav.explore', 'Samples')}</Link></li>
                <li><Link to="/projects" className="hover:text-white">Projects</Link></li>
                <li><Link to="/series" className="hover:text-white">Series</Link></li>
                <li><Link to="/stats" className="hover:text-white">{t('nav.stats', 'Statistics')}</Link></li>
              </ul>
            </div>
            <div>
              <h3 className="font-semibold text-white mb-2 text-sm">{t('footer.tools', 'Tools')}</h3>
              <ul className="space-y-1.5 text-white/60">
                <li><Link to="/search" className="hover:text-white">Advanced search</Link></li>
                <li><Link to="/discover" className="hover:text-white">Live discovery</Link></li>
                <li><Link to="/downloads" className="hover:text-white">Downloads / manifest</Link></li>
                <li><Link to="/workspace" className="hover:text-white">Workspaces</Link></li>
              </ul>
            </div>
            <div>
              <h3 className="font-semibold text-white mb-2 text-sm">{t('footer.docs', 'Docs')}</h3>
              <ul className="space-y-1.5 text-white/60">
                <li><Link to="/about" className="hover:text-white">{t('nav.about', 'About the data')}</Link></li>
                <li><a href="/docs" className="hover:text-white">REST API reference</a></li>
                <li><a href="/scdbAPI/health" className="hover:text-white">Service health</a></li>
                <li><a href="/scdbAPI/discover/sources" className="hover:text-white">Discovery sources</a></li>
              </ul>
            </div>
            <div>
              <h3 className="font-semibold text-white mb-2 text-sm">{t('footer.about', 'About')}</h3>
              <ul className="space-y-1.5 text-white/60">
                <li>
                  <a
                    href="https://github.com/firefly-hefeng/SGDB_Agent"
                    className="hover:text-white inline-flex items-center gap-1"
                    target="_blank"
                    rel="noreferrer"
                  >
                    <Github size={11} /> firefly-hefeng/SGDB_Agent
                  </a>
                </li>
                <li>
                  <a href="https://compbio.nju.edu.cn/" className="hover:text-white" target="_blank" rel="noreferrer">
                    {t('footer.lab', 'Lab — compbio.nju.edu.cn')}
                  </a>
                </li>
                <li>
                  <a href="https://huggingface.co/datasets/nju-hefeng/singligent-catalog" className="hover:text-white" target="_blank" rel="noreferrer">
                    {t('footer.opendata', 'Open data (Hugging Face)')}
                  </a>
                </li>
                <li>Build v{APP_VERSION}</li>
              </ul>
            </div>
          </div>
          <div className="pt-5 border-t border-white/10 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2 text-2xs text-white/40">
            <span>© {new Date().getFullYear()} Singligent · Nanjing University</span>
            <span>{t('footer.tagline', 'Built for biologists, by biologists.')}</span>
          </div>
        </div>
      </footer>
    </div>
  );
}

function CollectionCard({ collection }: { collection: FeaturedCollection }) {
  // R2-4: land on the collection's EXACT curated subset by passing its slug,
  // which the Explore API resolves to the same filter the card counted —
  // instead of flattening to a coarse `q=` keyword (or, for filter-only
  // themes, an empty query → unfiltered Explore).
  const exploreHref = `/explore?collection=${encodeURIComponent(collection.slug)}`;

  return (
    <Link
      to={exploreHref}
      state={{ collectionTitle: collection.title }}
      className="card card-hover p-4 group block"
      aria-label={`Explore the ${collection.title} collection`}
    >
      <div className="flex items-start justify-between gap-2 mb-1.5">
        <div className="flex items-center gap-1.5 min-w-0">
          <Sparkles size={14} className="text-accent shrink-0" />
          <h3 className="text-sm font-semibold text-ink leading-tight truncate">
            {collection.title}
          </h3>
        </div>
        <span className="text-2xs text-ink-subtle tabular-nums shrink-0">
          {fmt(collection.sample_count)}
        </span>
      </div>
      <p className="text-xs text-ink-muted leading-relaxed line-clamp-2 mb-2">
        {collection.blurb}
      </p>
      <div className="flex items-center gap-1 flex-wrap">
        {collection.projects.slice(0, 3).map((p) => (
          <span
            key={`${p.source_database}-${p.project_id}`}
            className="text-2xs font-mono px-1.5 py-0.5 rounded bg-canvas-muted text-ink-muted"
          >
            {p.project_id}
          </span>
        ))}
        {collection.project_count > 3 && (
          <span className="text-2xs text-ink-subtle">
            +{collection.project_count - 3} more
          </span>
        )}
      </div>
      <span className="mt-2 text-xs text-accent inline-flex items-center gap-1 group-hover:gap-1.5 transition-all">
        Open <ArrowRight size={11} />
      </span>
    </Link>
  );
}

function FeatureCard({
  to,
  icon,
  title,
  body,
  cta = 'Open',
}: {
  to: string;
  icon: React.ReactNode;
  title: string;
  body: string;
  cta?: string;
}) {
  return (
    <Link to={to} className="card card-hover p-5 group block">
      <div className="flex items-center gap-2 mb-2.5">
        <div className="w-7 h-7 rounded-md bg-accent-subtle flex items-center justify-center">
          {icon}
        </div>
        <h3 className="text-base font-semibold text-[var(--text)]">{title}</h3>
      </div>
      <p className="text-xs text-ink-muted leading-relaxed mb-2">{body}</p>
      <span className="text-xs text-accent inline-flex items-center gap-1 group-hover:gap-1.5 transition-all">
        {cta} <ArrowRight size={12} />
      </span>
    </Link>
  );
}
