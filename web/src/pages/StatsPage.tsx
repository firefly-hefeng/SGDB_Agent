import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  LineChart,
  Line,
  CartesianGrid,
  Legend,
} from 'recharts';
import { getDashboardStats } from '../services/api';
import type { DashboardStats } from '../types/api';
import { PageHeader } from '../components/ui/PageHeader';
import { HowToUse } from '../components/ui/HowToUse';
import { fmt, prettyLabel } from '../lib/format';
import { toast } from '../lib/toastApi';
import { useT } from '../lib/i18n';

/**
 * Chart-friendly palette derived from the design tokens. Single accent +
 * three muted partners; no full-saturation rainbow.
 */
const PALETTE = [
  '#1B6FA8', // accent
  '#067647', // success
  '#B45309', // warning
  '#5B21B6', // violet-800
  '#0E7490', // cyan-700
  '#9F1239', // rose-700
  '#155E75', // sky-800
  '#3F6212', // lime-700
  '#7C2D12', // orange-800
  '#1E3A8A', // blue-900
  '#4D7C0F', // lime-600
  '#831843', // pink-800
  '#365314', // lime-900
  '#0F766E', // teal-700
  '#7F1D1D', // red-900
];

/** Shared chart tooltip + axis styling. */
const TT_PROPS = {
  contentStyle: {
    background: '#fff',
    border: '1px solid var(--border)',
    borderRadius: 6,
    boxShadow: '0 4px 12px rgba(15, 23, 42, 0.06)',
    fontSize: 12,
    padding: '8px 12px',
  },
  labelStyle: { color: 'var(--text-primary)', fontWeight: 600 },
  cursor: { fill: 'rgba(27, 111, 168, 0.06)' },
};
const AXIS_TICK = { fill: 'var(--text-secondary)', fontSize: 11 };
const TICK_LINE = { stroke: 'var(--border)' };

const LEGEND_PROPS = {
  layout: 'vertical' as const,
  align: 'right' as const,
  verticalAlign: 'middle' as const,
  iconType: 'circle' as const,
  wrapperStyle: { fontSize: 11, lineHeight: '14px', paddingLeft: 12, maxWidth: 160 },
};


export default function StatsPage() {
  const nav = useNavigate();
  const { t } = useT();
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getDashboardStats()
      .then(setStats)
      .catch((e) => {
        setError(String(e));
        toast(`${t('stats.load_failed', 'Failed to load statistics:')} ${e}`, 'error');
      })
      .finally(() => setLoading(false));
    // t is stable for the lifetime of the language; load once on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (loading) {
    return (
      <div className="flex-1 overflow-y-auto bg-canvas-subtle">
        <PageHeader
          eyebrow={t('stats.eyebrow', 'Database statistics')}
          title={t('stats.title', 'A live snapshot of the unified catalog')}
          description={t('stats.desc', 'Sample counts, source coverage, tissue and disease distributions, recent submissions. Click any chart bar to filter Explore by that facet.')}
        />
        <div className="max-w-[1280px] mx-auto px-6 py-6">
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-6">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="skeleton h-[72px] rounded-md" />
            ))}
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="skeleton h-[280px] rounded-md" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (error || !stats) {
    return (
      <div className="flex-1 overflow-y-auto bg-canvas-subtle">
        <PageHeader
          eyebrow={t('stats.eyebrow', 'Database statistics')}
          title={t('stats.title', 'A live snapshot of the unified catalog')}
        />
        <div className="max-w-[1280px] mx-auto px-6 py-10 text-center text-ink-muted">
          <p className="text-base font-medium mb-1">{t('stats.unavailable', 'Statistics unavailable')}</p>
          <p className="text-sm text-ink-subtle">{error || t('stats.nodata', 'No data returned.')}</p>
        </div>
      </div>
    );
  }

  const headlineCards = [
    { l: t('stats.card.samples', 'Samples'), v: stats.total_samples },
    { l: t('stats.card.projects', 'Projects'), v: stats.total_projects },
    { l: t('stats.card.series', 'Series'), v: stats.total_series },
    { l: t('stats.card.celltypes', 'Cell types'), v: stats.total_celltypes },
    { l: t('stats.card.crosslinks', 'Cross-links'), v: stats.total_cross_links },
  ];


  return (
    <div className="flex-1 overflow-y-auto bg-canvas-subtle">
      <PageHeader
        eyebrow={t('stats.eyebrow', 'Database statistics')}
        title={t('stats.title', 'A live snapshot of the unified catalog')}
        description={t('stats.desc', 'Sample counts, source coverage, tissue and disease distributions, recent submissions. Click any chart bar to filter Explore by that facet.')}
      />

      <div className="max-w-[1280px] mx-auto px-6 py-6">
        <HowToUse
          className="mb-5"
          body={t('intro.stats.body',
            'A live snapshot of the curated catalog. Click any chart bar to filter Explore by that facet.')}
          examples={[
            { label: t('stats.quick.by_database', 'Samples by database'), to: '/about', hint: t('stats.quick.by_database.hint', 'see the curated-vs-live breakdown') },
            { label: t('stats.quick.top_tissues', 'Top tissues → Explore'), to: '/explore?tissue=lung' },
          ]}
        />

        {/* Headline cards */}
        <section className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-6">
          {headlineCards.map(({ l, v }) => (
            <article
              key={l}
              className="card px-4 py-3 text-center hover:border-line-strong transition-colors"
            >
              <div className="text-2xl font-semibold text-ink tabular-nums leading-none mb-1">
                {fmt(v)}
              </div>
              <div className="text-2xs uppercase tracking-wider text-ink-subtle">{l}</div>
            </article>
          ))}
        </section>

        {/* Catalog Atlas — publication-grade overview of the live catalog */}
        <section className="mb-6">
          <div className="flex items-center gap-2 mb-1">
            <span className="w-4 h-px bg-accent/60" />
            <h2 className="text-2xs uppercase tracking-wider text-accent font-semibold">
              {t('stats.atlas.label', 'Catalog atlas')}
            </h2>
          </div>
          <p className="text-sm text-ink-muted max-w-[60rem] mb-3">
            {t('stats.atlas.sub', 'A publication-grade snapshot of the live catalog — source contribution, biological & disease coverage, assay mix, growth over time, and literature linkage. Explore the same data interactively below.')}
          </p>
          <figure className="card p-3 sm:p-4 bg-white">
            <a href={`${import.meta.env.BASE_URL}stats/atlas.png`} target="_blank" rel="noreferrer"
               className="block rounded-md overflow-hidden cursor-zoom-in" title={t('stats.atlas.view', 'Open full size')}>
              <img src={`${import.meta.env.BASE_URL}stats/atlas.png`} alt={t('stats.atlas.alt', 'Catalog atlas: multi-panel overview of the Singligent single-cell catalog')}
                   loading="lazy" className="w-full h-auto" />
            </a>
          </figure>
        </section>

        <div className="flex items-center gap-2 mb-3">
          <span className="w-4 h-px bg-accent/60" />
          <h2 className="text-2xs uppercase tracking-wider text-accent font-semibold">
            {t('stats.interactive.label', 'Interactive explorer')}
          </h2>
        </div>
        <section className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <ChartCard title={t('stats.chart.by_source', 'Samples by database')} hint={t('stats.chart.by_source.hint', 'Click a bar to filter Explore.')}>
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={stats.by_source} layout="vertical" margin={{ left: 70 }}>
                <XAxis type="number" tick={AXIS_TICK} axisLine={false} tickLine={false} />
                <YAxis
                  type="category"
                  dataKey="name"
                  tick={AXIS_TICK}
                  tickFormatter={prettyLabel}
                  interval={0}
                  width={65}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip {...TT_PROPS} labelFormatter={prettyLabel} />
                <Bar
                  isAnimationActive={false}
                  dataKey="samples"
                  fill={PALETTE[0]}
                  radius={[0, 3, 3, 0]}
                  cursor="pointer"
                  onClick={(d) =>
                    nav(`/explore?source_database=${encodeURIComponent(String(d.name))}`)
                  }
                />
              </BarChart>
            </ResponsiveContainer>
          </ChartCard>

          {stats.by_tissue_system?.length > 0 && (() => {
            const tissueSystemData = stats.by_tissue_system.slice(0, 20);
            return (
            <ChartCard title={t('stats.chart.tissue_system', 'Tissue system distribution')}>
              <ResponsiveContainer width="100%" height={Math.max(260, tissueSystemData.length * 28)}>
                <BarChart
                  data={tissueSystemData}
                  layout="vertical"
                  margin={{ left: 120 }}
                >
                  <XAxis type="number" tick={AXIS_TICK} axisLine={false} tickLine={false} />
                  <YAxis
                    type="category"
                    dataKey="value"
                    tick={AXIS_TICK}
                    tickFormatter={prettyLabel}
                    interval={0}
                    width={118}
                    axisLine={false}
                    tickLine={false}
                  />
                  <Tooltip {...TT_PROPS} labelFormatter={prettyLabel} />
                  <Bar
                    isAnimationActive={false}
                    dataKey="count"
                    fill={PALETTE[1]}
                    radius={[0, 3, 3, 0]}
                    cursor="pointer"
                    onClick={(d) =>
                      nav(`/explore?tissue_system=${encodeURIComponent(String(d.value))}`)
                    }
                  />
                </BarChart>
              </ResponsiveContainer>
            </ChartCard>
            );
          })()}

          {(() => {
            const tissueData = stats.by_tissue.slice(0, 20);
            return (
            <ChartCard title={t('stats.chart.top_tissues', 'Top 20 tissues')}>
              <ResponsiveContainer width="100%" height={Math.max(260, tissueData.length * 28)}>
                <BarChart
                  data={tissueData}
                  layout="vertical"
                  margin={{ left: 90 }}
                >
                  <XAxis type="number" tick={AXIS_TICK} axisLine={false} tickLine={false} />
                  <YAxis
                    type="category"
                    dataKey="value"
                    tick={AXIS_TICK}
                    tickFormatter={prettyLabel}
                    interval={0}
                    width={85}
                    axisLine={false}
                    tickLine={false}
                  />
                  <Tooltip {...TT_PROPS} labelFormatter={prettyLabel} />
                  <Bar
                    isAnimationActive={false}
                    dataKey="count"
                    fill={PALETTE[0]}
                    radius={[0, 3, 3, 0]}
                    cursor="pointer"
                    onClick={(d) => nav(`/explore?tissue=${encodeURIComponent(String(d.value))}`)}
                  />
                </BarChart>
              </ResponsiveContainer>
            </ChartCard>
            );
          })()}

          {stats.by_disease_category?.length > 0 && (() => {
            const diseaseCatData = [...stats.by_disease_category]
              .sort((a, b) => b.count - a.count)
              .slice(0, 12);
            return (
            <ChartCard title={t('stats.chart.disease_category', 'Disease category distribution')}>
              <ResponsiveContainer width="100%" height={Math.max(260, diseaseCatData.length * 28)}>
                <BarChart
                  data={diseaseCatData}
                  layout="vertical"
                  margin={{ left: 110 }}
                >
                  <XAxis type="number" tick={AXIS_TICK} axisLine={false} tickLine={false} />
                  <YAxis
                    type="category"
                    dataKey="value"
                    tick={AXIS_TICK}
                    tickFormatter={prettyLabel}
                    interval={0}
                    width={105}
                    axisLine={false}
                    tickLine={false}
                  />
                  <Tooltip {...TT_PROPS} labelFormatter={prettyLabel} />
                  <Bar
                    isAnimationActive={false}
                    dataKey="count"
                    fill={PALETTE[2]}
                    radius={[0, 3, 3, 0]}
                  />
                </BarChart>
              </ResponsiveContainer>
            </ChartCard>
            );
          })()}

          {(() => {
            const diseaseData = stats.by_disease.slice(0, 20);
            return (
          <ChartCard title={t('stats.chart.top_diseases', 'Top 20 diseases')}>
            <ResponsiveContainer width="100%" height={Math.max(260, diseaseData.length * 28)}>
              <BarChart
                data={diseaseData}
                layout="vertical"
                margin={{ left: 150 }}
              >
                <XAxis type="number" tick={AXIS_TICK} axisLine={false} tickLine={false} />
                <YAxis
                  type="category"
                  dataKey="value"
                  tick={AXIS_TICK}
                  tickFormatter={prettyLabel}
                  interval={0}
                  width={150}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip {...TT_PROPS} labelFormatter={prettyLabel} />
                <Bar
                  isAnimationActive={false}
                  dataKey="count"
                  fill={PALETTE[2]}
                  radius={[0, 3, 3, 0]}
                  cursor="pointer"
                  onClick={(d) => nav(`/explore?disease=${encodeURIComponent(String(d.value))}`)}
                />
              </BarChart>
            </ResponsiveContainer>
          </ChartCard>
            );
          })()}

          {stats.by_sample_type?.length > 0 && (
            <ChartCard title={t('stats.chart.sample_type', 'Sample type distribution')}>
              <ResponsiveContainer width="100%" height={260}>
                <PieChart>
                  <Pie
                    isAnimationActive={false}
                    data={stats.by_sample_type}
                    dataKey="count"
                    nameKey="value"
                    cx="50%"
                    cy="50%"
                    outerRadius={90}
                    innerRadius={36}
                    paddingAngle={1}
                    labelLine={false}
                    strokeWidth={0}
                  >
                    {stats.by_sample_type.map((_, i) => (
                      <Cell key={i} fill={PALETTE[i % PALETTE.length]} />
                    ))}
                  </Pie>
                  <Tooltip {...TT_PROPS} formatter={(value, name) => [value, prettyLabel(name)]} />
                  <Legend {...LEGEND_PROPS} formatter={prettyLabel} />
                </PieChart>
              </ResponsiveContainer>
            </ChartCard>
          )}

          <ChartCard title={t('stats.chart.assay', 'Assay distribution (annotated samples only)')}>
            <ResponsiveContainer width="100%" height={260}>
              <PieChart>
                <Pie
                  isAnimationActive={false}
                  data={stats.by_assay.slice(0, 10)}
                  dataKey="count"
                  nameKey="value"
                  cx="50%"
                  cy="50%"
                  outerRadius={90}
                  innerRadius={36}
                  paddingAngle={1}
                  labelLine={false}
                  strokeWidth={0}
                >
                  {stats.by_assay.slice(0, 10).map((_, i) => (
                    <Cell key={i} fill={PALETTE[i % PALETTE.length]} />
                  ))}
                </Pie>
                <Tooltip {...TT_PROPS} formatter={(value, name) => [value, prettyLabel(name)]} />
                <Legend {...LEGEND_PROPS} formatter={prettyLabel} />
              </PieChart>
            </ResponsiveContainer>
          </ChartCard>

          {stats.submissions_by_year.length > 0 && (
            <ChartCard title={t('stats.chart.by_year', 'Submissions by year')}>
              <ResponsiveContainer width="100%" height={260}>
                <LineChart data={stats.submissions_by_year} margin={{ left: 10, right: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border-light)" />
                  <XAxis dataKey="year" tick={AXIS_TICK} axisLine={false} tickLine={TICK_LINE} />
                  <YAxis tick={AXIS_TICK} axisLine={false} tickLine={TICK_LINE} />
                  <Tooltip {...TT_PROPS} />
                  <Line
                    isAnimationActive={false}
                    type="monotone"
                    dataKey="count"
                    stroke="var(--accent)"
                    strokeWidth={2}
                    dot={{ r: 3, fill: 'var(--accent)', strokeWidth: 0 }}
                    activeDot={{ r: 4 }}
                  />
                </LineChart>
              </ResponsiveContainer>
            </ChartCard>
          )}

        </section>
      </div>
    </div>
  );
}

function ChartCard({
  title,
  hint,
  ariaLabel,
  children,
}: {
  title: string;
  hint?: string;
  ariaLabel?: string;
  children: React.ReactNode;
}) {
  const { t } = useT();
  return (
    <article className="card p-5">
      <header className="mb-3">
        <h2 className="text-sm font-semibold text-ink leading-none">{title}</h2>
        {hint && <p className="text-2xs text-ink-subtle mt-1">{hint}</p>}
      </header>
      {/* WCAG 1.1.1: the SVG chart needs an accessible name (a11y) */}
      <div role="img" aria-label={ariaLabel || `${title} ${t('stats.chart.aria_suffix', '(chart)')}`}>
        {children}
      </div>
    </article>
  );
}
