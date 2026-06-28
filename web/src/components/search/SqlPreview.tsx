import { useState } from 'react';
import { ChevronDown, ChevronRight, Database, Clock, Layers } from 'lucide-react';
import type { ProvenanceInfo } from '../../types/api';

const SQL_KEYWORDS = /\b(SELECT|FROM|WHERE|AND|OR|NOT|IN|LIKE|JOIN|LEFT|RIGHT|INNER|OUTER|ON|GROUP|BY|ORDER|ASC|DESC|LIMIT|OFFSET|COUNT|SUM|AVG|MIN|MAX|DISTINCT|AS|UNION|ALL|HAVING|BETWEEN|IS|NULL|EXISTS|CASE|WHEN|THEN|ELSE|END|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|TABLE|INDEX|VIEW)\b/gi;
const SQL_STRINGS = /('[^']*')/g;
const SQL_NUMBERS = /\b(\d+(?:\.\d+)?)\b/g;

function highlightSql(sql: string): string {
  // Escape HTML first
  let s = sql.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  // Highlight strings (green)
  s = s.replace(SQL_STRINGS, '<span style="color:#86efac">$1</span>');
  // Highlight keywords (blue)
  s = s.replace(SQL_KEYWORDS, (m) => `<span style="color:#7dd3fc;font-weight:600">${m.toUpperCase()}</span>`);
  // Highlight numbers (orange)
  s = s.replace(SQL_NUMBERS, '<span style="color:#fdba74">$1</span>');
  return s;
}

interface Props {
  provenance: ProvenanceInfo | null;
  summary: string;
}

export function SqlPreview({ provenance, summary }: Props) {
  const [open, setOpen] = useState(false);

  if (!provenance) return null;

  const execTime = provenance.execution_time_ms;
  const intent = provenance.parsed_intent || null;
  const method = provenance.sql_method || null;
  const sql = provenance.sql_executed || null;
  const sources = provenance.data_sources || [];
  const expansions = provenance.ontology_expansions || [];

  return (
    <div className="border border-line-subtle rounded-lg mt-3 bg-canvas-subtle/50">
      <button onClick={() => setOpen(!open)}
        className="flex items-center gap-2 w-full px-3 py-2 text-xs text-ink-muted hover:text-ink transition-colors">
        {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        <Database size={12} />
        <span>Query Details</span>
        {execTime != null && (
          <span className="ml-auto flex items-center gap-1 text-2xs text-ink-subtle">
            <Clock size={10} />
            {execTime.toFixed(0)}ms
          </span>
        )}
      </button>

      {open && (
        <div className="px-3 pb-3 space-y-2 text-xs border-t border-line-subtle">
          {summary && (
            <div className="pt-2 text-ink-muted">{summary}</div>
          )}

          {intent && (
            <div className="flex gap-2">
              <span className="text-ink-subtle shrink-0">Intent:</span>
              <span className="text-ink-muted">{intent}</span>
            </div>
          )}

          {method && (
            <div className="flex gap-2">
              <span className="text-ink-subtle shrink-0">Method:</span>
              <span className="badge badge-gray text-2xs">{method}</span>
            </div>
          )}

          {sources.length > 0 && (
            <div className="flex gap-2 items-start">
              <Layers size={12} className="text-ink-subtle mt-0.5 shrink-0" />
              <div className="flex flex-wrap gap-1">
                {sources.map((s) => (
                  <span key={s} className="badge badge-gray text-2xs">{s}</span>
                ))}
              </div>
            </div>
          )}

          {expansions.length > 0 && (
            <div>
              <span className="text-ink-subtle">Ontology expansions:</span>
              <div className="mt-1 space-y-0.5">
                {expansions.map((e, i) => (
                  <div key={i} className="text-2xs text-ink-muted">
                    &ldquo;{e.original}&rdquo; &rarr; {e.label || e.ontology_id} ({e.db_values_count} matched, {e.total_samples} samples)
                  </div>
                ))}
              </div>
            </div>
          )}

          {sql && (
            <div>
              <span className="text-ink-subtle">SQL:</span>
              <pre className="mt-1 p-3 bg-ink rounded-lg text-2xs overflow-x-auto whitespace-pre-wrap break-all font-mono leading-relaxed"
                dangerouslySetInnerHTML={{ __html: highlightSql(sql) }} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
