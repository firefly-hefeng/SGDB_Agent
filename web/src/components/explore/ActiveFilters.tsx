import { X } from 'lucide-react';
import { useT } from '../../lib/i18n';

interface Props {
  filters: Record<string, string[]>;
  onRemove: (f: string, v: string) => void;
  onClearAll: () => void;
}

const CFG: Record<string, { label: string; labelKey: string; cls: string }> = {
  tissues: { label: 'Tissue', labelKey: 'activefilters.tissue', cls: 'badge-green' },
  diseases: { label: 'Disease', labelKey: 'activefilters.disease', cls: 'badge-red' },
  assays: { label: 'Assay', labelKey: 'activefilters.assay', cls: 'badge-purple' },
  organisms: { label: 'Organism', labelKey: 'activefilters.organism', cls: 'badge-blue' },
  source_databases: { label: 'DB', labelKey: 'activefilters.db', cls: 'badge-amber' },
  cell_types: { label: 'Cell', labelKey: 'activefilters.cell', cls: 'badge-teal' },
};

export function ActiveFilters({ filters, onRemove, onClearAll }: Props) {
  const { t } = useT();
  const tags: { f: string; v: string }[] = [];
  for (const [f, vs] of Object.entries(filters)) for (const v of vs) tags.push({ f, v });
  if (!tags.length) return null;

  return (
    <div className="flex flex-wrap items-center gap-1.5 mb-3">
      {tags.map(({ f, v }) => {
        const c = CFG[f] || { label: f, labelKey: '', cls: 'badge-gray' };
        const label = c.labelKey ? t(c.labelKey, c.label) : c.label;
        return (
          <span key={`${f}-${v}`} className={`badge ${c.cls} inline-flex items-center gap-1`}>
            <span className="opacity-60 text-2xs">{label}:</span>{v}
            <button onClick={() => onRemove(f, v)} aria-label={`${t('activefilters.remove.aria', 'Remove filter')}: ${label} ${v}`} className="opacity-40 hover:opacity-100 -mr-0.5"><X size={11} /></button>
          </span>
        );
      })}
      <button onClick={onClearAll} className="text-xs text-accent hover:underline ml-1">{t('activefilters.clearall', 'Clear all')}</button>
    </div>
  );
}
