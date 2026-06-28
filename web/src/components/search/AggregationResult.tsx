import { useMemo } from 'react';
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, Cell,
} from 'recharts';
import { BarChart3 } from 'lucide-react';
import { useT } from '../../lib/i18n';

interface Props {
  rows: Record<string, unknown>[];
  summary?: string;
}

const COLORS = ['#2563eb', '#0ea5e9', '#14b8a6', '#22c55e', '#eab308', '#f97316', '#ef4444', '#a855f7', '#ec4899', '#64748b'];

/**
 * AggregationResult — Phase 33. Renders the group→count breakdown for
 * "count by …" STATISTICS queries (a bar chart + a table), so aggregation
 * queries in Advanced Search show real numbers instead of empty sample rows.
 */
export function AggregationResult({ rows, summary }: Props) {
  const { t } = useT();
  const { labelKey, data, total } = useMemo(() => {
    if (!rows.length) return { labelKey: '', data: [] as { name: string; value: number }[], total: 0 };
    // The label is the first key that isn't a numeric measure.
    const keys = Object.keys(rows[0]);
    const lk = keys.find((k) => !['count', 'total_cells', 'n_cells', 'value'].includes(k)) || keys[0];
    const d = rows
      .map((r) => ({
        // A NULL/empty group key is common (e.g. ~half the catalog has no
        // standardized tissue); label it explicitly rather than as a bare dash
        // so the breakdown isn't mistaken for a real category.
        name: r[lk] == null || r[lk] === '' ? t('agg.unspecified', '(unspecified)') : String(r[lk]),
        value: Number(r.count ?? r.value ?? 0),
        cells: Number(r.total_cells ?? 0),
      }))
      .sort((a, b) => b.value - a.value);
    const tot = d.reduce((s, x) => s + x.value, 0);
    return { labelKey: lk, data: d, total: tot };
  }, [rows, t]);

  if (!rows.length) return null;

  return (
    <div className="card p-4 mb-3">
      <div className="flex items-center gap-2 mb-3">
        <BarChart3 size={15} className="text-accent" />
        <h3 className="text-sm font-semibold text-ink">
          {t('agg.heading_1', 'Aggregation —')} {data.length} {t('agg.groups_by', 'groups by')} <span className="font-mono">{labelKey}</span>
        </h3>
        <span className="ml-auto text-2xs text-ink-subtle tabular-nums">
          {total.toLocaleString()} {t('agg.total', 'total')}
        </span>
      </div>
      {summary && <p className="text-xs text-ink-muted mb-3">{summary}</p>}

      <div
        style={{ width: '100%', height: Math.min(Math.max(data.length * 26, 120), 520) }}
        role="img"
        aria-label={
          `${t('agg.chart.aria_1', 'Bar chart: sample counts by')} ${labelKey}, ${data.length} ${t('agg.chart.aria_groups', 'groups.')} ` +
          (data.length
            ? `${t('agg.chart.aria_top', 'Top groups —')} ${data
                .slice(0, 5)
                .map((d) => `${d.name}: ${d.value.toLocaleString()}`)
                .join('; ')}.`
            : '')
        }
      >
        <ResponsiveContainer>
          <BarChart data={data} layout="vertical" margin={{ left: 8, right: 24, top: 4, bottom: 4 }}>
            <XAxis type="number" tick={{ fontSize: 11 }} />
            <YAxis
              type="category" dataKey="name" width={140}
              tick={{ fontSize: 11 }} interval={0}
            />
            <Tooltip
              formatter={(v: unknown) => [Number(v).toLocaleString(), t('common.samples', 'samples')] as [string, string]}
              contentStyle={{ fontSize: 12 }}
            />
            <Bar dataKey="value" radius={[0, 3, 3, 0]} isAnimationActive={false}>
              {data.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      <table className="w-full mt-3 text-xs">
        <caption className="sr-only">
          {`${t('agg.table.caption_1', 'Data table for the bar chart above: sample counts by')} ${labelKey}, ${data.length} ${t('agg.table.caption_2', 'groups.')}`}
        </caption>
        <thead>
          <tr className="text-2xs text-ink-subtle uppercase tracking-wide border-b border-line">
            <th className="text-left py-1.5 font-medium">{labelKey}</th>
            <th className="text-right py-1.5 font-medium">{t('agg.samples', 'Samples')}</th>
            <th className="text-right py-1.5 font-medium">% </th>
          </tr>
        </thead>
        <tbody>
          {data.map((d) => (
            <tr key={d.name} className="border-b border-line-subtle">
              <td className="py-1.5 text-ink">{d.name}</td>
              <td className="py-1.5 text-right tabular-nums text-ink-muted">{d.value.toLocaleString()}</td>
              <td className="py-1.5 text-right tabular-nums text-ink-subtle">
                {total ? ((d.value / total) * 100).toFixed(1) : '0'}%
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
