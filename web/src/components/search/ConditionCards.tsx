import { X } from 'lucide-react';
import type { ParsedCondition } from '../../types/api';
import { useT } from '../../lib/i18n';

interface Props {
  conditions: ParsedCondition[];
  onRemove: (index: number) => void;
  onClearAll: () => void;
}

// label is resolved through t() via key/en; cls is the badge style class.
const FIELD_STYLE: Record<string, { key: string; en: string; cls: string }> = {
  tissue: { key: 'cond.tissue', en: 'Tissue', cls: 'badge-green' },
  disease: { key: 'cond.disease', en: 'Disease', cls: 'badge-red' },
  assay: { key: 'cond.assay', en: 'Assay', cls: 'badge-purple' },
  organism: { key: 'cond.organism', en: 'Organism', cls: 'badge-blue' },
  source_database: { key: 'cond.db', en: 'DB', cls: 'badge-amber' },
  cell_type: { key: 'cond.cell', en: 'Cell', cls: 'badge-teal' },
  sex: { key: 'cond.sex', en: 'Sex', cls: 'badge-pink' },
  min_cells: { key: 'cond.min_cells', en: 'Min Cells', cls: 'badge-orange' },
  has_h5ad: { key: 'cond.h5ad', en: 'H5AD', cls: 'badge-green' },
  text_search: { key: 'cond.text', en: 'Text', cls: 'badge-gray' },
  project_id: { key: 'cond.project', en: 'Project', cls: 'badge-blue' },
  sample_id: { key: 'cond.sample', en: 'Sample', cls: 'badge-blue' },
  pmid: { key: 'cond.pmid', en: 'PMID', cls: 'badge-amber' },
};

function conditionLabel(c: ParsedCondition): string {
  if (c.values.length <= 3) return c.values.join(', ');
  return `${c.values.slice(0, 2).join(', ')} +${c.values.length - 2}`;
}

export function ConditionCards({ conditions, onRemove, onClearAll }: Props) {
  const { t } = useT();
  if (!conditions.length) return null;

  return (
    <div className="flex flex-wrap items-center gap-1.5 mb-3">
      {conditions.map((c, i) => {
        const style = FIELD_STYLE[c.field];
        const label = style ? t(style.key, style.en) : c.field;
        const cls = style ? style.cls : 'badge-gray';
        return (
          <span key={`${c.field}-${i}`}
            className={`badge ${cls} inline-flex items-center gap-1 max-w-[280px]`}
            title={c.display_label || c.values.join(', ')}>
            <span className="opacity-60 text-2xs">{label}:</span>
            <span className="truncate">{conditionLabel(c)}</span>
            {c.source === 'nl_parse' && c.confidence < 0.8 && (
              <span className="opacity-40 text-2xs">?</span>
            )}
            <button onClick={() => onRemove(i)}
              className="opacity-40 hover:opacity-100 -mr-0.5 shrink-0"
              aria-label={`${t('cond.remove.aria', 'Remove filter')}: ${label}`}>
              <X size={11} />
            </button>
          </span>
        );
      })}
      <button onClick={onClearAll}
        className="text-xs text-accent hover:underline ml-1">
        {t('cond.clearall', 'Clear all')}
      </button>
    </div>
  );
}
