import { useState } from 'react';
import {
  ChevronDown, ChevronRight, Database, Clock, Layers, Cpu, Network,
  Filter, ListChecks, GitMerge, Sparkles, AlertTriangle, CheckCircle2,
  XCircle, CircleDashed, Wrench, Copy, Check,
} from 'lucide-react';
import type { ProvenanceInfo, ReasoningStep } from '../../types/api';
import { toast } from '../../lib/toastApi';
import { useT } from '../../lib/i18n';

/* ── SQL syntax highlighting (shared with the legacy SqlPreview) ── */
const SQL_KEYWORDS = /\b(SELECT|FROM|WHERE|AND|OR|NOT|IN|LIKE|JOIN|LEFT|RIGHT|INNER|OUTER|ON|GROUP|BY|ORDER|ASC|DESC|LIMIT|OFFSET|COUNT|SUM|AVG|MIN|MAX|DISTINCT|AS|UNION|ALL|HAVING|BETWEEN|IS|NULL|EXISTS|CASE|WHEN|THEN|ELSE|END)\b/gi;
const SQL_STRINGS = /('(?:[^']|'')*')/g;
const SQL_NUMBERS = /\b(\d+(?:\.\d+)?)\b/g;

/**
 * Pretty-print a one-line SQL string so each major clause and each top-level
 * predicate lands on its own line. The agent emits SQL as a single line;
 * without this the "key query conditions" the user actually cares about
 * (the WHERE … AND … chain) are unreadable in a horizontally-scrolling blob.
 */
function formatSql(sql: string): string {
  return sql
    .replace(/\s+\b(WHERE|GROUP BY|ORDER BY|HAVING|LIMIT|OFFSET)\b/gi, '\n$1')
    .replace(/\s+\b(AND|OR)\b\s+/gi, '\n  $1 ')
    .trim();
}

function highlightSql(sql: string): string {
  let s = sql.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  s = s.replace(SQL_STRINGS, '<span style="color:#86efac">$1</span>');
  s = s.replace(SQL_KEYWORDS, (m) => `<span style="color:#7dd3fc;font-weight:600">${m.toUpperCase()}</span>`);
  s = s.replace(SQL_NUMBERS, '<span style="color:#fdba74">$1</span>');
  return s;
}

/* ── Per-stage presentation metadata ── */
// The label is resolved through t() at render via STAGE_META[stage].key / .en.
const STAGE_META: Record<string, { key: string; en: string; icon: typeof Cpu }> = {
  parse: { key: 'trace.stage.parse', en: 'Parse query', icon: Cpu },
  reason: { key: 'trace.stage.reason', en: 'Reason', icon: Cpu },
  ontology: { key: 'trace.stage.ontology', en: 'Resolve ontology', icon: Network },
  schema: { key: 'trace.stage.schema', en: 'Schema lookup', icon: Database },
  sql_gen: { key: 'trace.stage.sql_gen', en: 'Generate SQL', icon: Filter },
  validate: { key: 'trace.stage.validate', en: 'Validate SQL', icon: ListChecks },
  execute: { key: 'trace.stage.execute', en: 'Execute SQL', icon: Database },
  correct: { key: 'trace.stage.correct', en: 'Self-correction', icon: Wrench },
  fuse: { key: 'trace.stage.fuse', en: 'Cross-DB fusion', icon: GitMerge },
  synthesize: { key: 'trace.stage.synthesize', en: 'Synthesize answer', icon: Sparkles },
};

function StatusIcon({ status }: { status: ReasoningStep['status'] }) {
  switch (status) {
    case 'ok':
      return <CheckCircle2 size={13} className="text-emerald-500 shrink-0" />;
    case 'corrected':
      return <Wrench size={13} className="text-amber-500 shrink-0" />;
    case 'warn':
      return <AlertTriangle size={13} className="text-amber-500 shrink-0" />;
    case 'error':
      return <XCircle size={13} className="text-red-500 shrink-0" />;
    default:
      return <CircleDashed size={13} className="text-ink-subtle shrink-0" />;
  }
}

function fmtMs(ms: number | undefined): string {
  if (ms == null) return '';
  if (ms < 1000) return `${ms.toFixed(0)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

/* Render the most informative key/value chips for a given stage output. */
function StageOutput({ step }: { step: ReasoningStep }) {
  const { t } = useT();
  const o = step.output || {};
  const chips: { k: string; v: string }[] = [];
  const push = (k: string, v: unknown) => {
    if (v == null || v === '' || (Array.isArray(v) && v.length === 0)) return;
    chips.push({ k, v: Array.isArray(v) ? v.join(', ') : String(v) });
  };

  switch (step.stage) {
    case 'parse':
      push('intent', o.intent);
      push('method', o.method);
      push('entities', o.entity_count);
      push('filters', o.filter_keys);
      if (o.strict_mode) push('strict', 'yes');
      push('confidence', o.confidence != null ? Number(o.confidence).toFixed(2) : null);
      break;
    case 'ontology': {
      const exp = (o.expansions as { original: string; term: string; expanded_count: number }[]) || [];
      return exp.length ? (
        <div className="mt-1 space-y-0.5">
          {exp.map((e, i) => (
            <div key={i} className="text-2xs text-ink-muted">
              &ldquo;{e.original}&rdquo; &rarr; {e.term} <span className="text-ink-subtle">({e.expanded_count} {t('trace.db_terms', 'db terms')})</span>
            </div>
          ))}
        </div>
      ) : null;
    }
    case 'sql_gen':
      push('candidates', o.candidate_count);
      push('strategies', o.methods);
      break;
    case 'execute':
      push('rows', typeof o.row_count === 'number' ? o.row_count.toLocaleString() : o.row_count);
      push('method', o.method);
      push('query time', o.exec_time_ms != null ? fmtMs(Number(o.exec_time_ms)) : null);
      break;
    case 'correct':
      push('strategy', o.strategy);
      push('rows', typeof o.row_count === 'number' ? o.row_count.toLocaleString() : o.row_count);
      push('suggestions', o.suggestion_count);
      break;
    case 'fuse':
      push('raw', typeof o.raw_count === 'number' ? o.raw_count.toLocaleString() : o.raw_count);
      push('fused', typeof o.fused_count === 'number' ? o.fused_count.toLocaleString() : o.fused_count);
      push('dedup', o.dedup_rate_pct != null ? `${o.dedup_rate_pct}%` : null);
      break;
    case 'synthesize':
      push('total', typeof o.total_count === 'number' ? o.total_count.toLocaleString() : o.total_count);
      push('shown', o.displayed_count);
      push('suggestions', o.suggestion_count);
      push('charts', o.chart_count);
      break;
    default:
      Object.entries(o).slice(0, 4).forEach(([k, v]) => push(k, v));
  }

  if (!chips.length) return null;
  return (
    <div className="mt-1 flex flex-wrap gap-1">
      {chips.map((c) => (
        <span key={c.k} className="inline-flex items-baseline gap-1 text-2xs bg-canvas-subtle border border-line-subtle rounded px-1.5 py-0.5">
          <span className="text-ink-subtle">{c.k}</span>
          <span className="text-ink-muted font-medium">{c.v}</span>
        </span>
      ))}
    </div>
  );
}

interface Props {
  provenance: ProvenanceInfo | null;
  summary: string;
  /** Start expanded (e.g. while debugging). Defaults to collapsed. */
  defaultOpen?: boolean;
}

/**
 * ExecutionTrace — Phase 27.
 *
 * The single collapsible panel that shows the *complete* advanced-search
 * execution flow: every pipeline stage with its status, duration, rationale,
 * and key outputs; the ontology expansions; and the final executed SQL.
 * Falls back to the scalar provenance fields when the agent didn't attach a
 * full trace (e.g. the structured-only fast path).
 */
export function ExecutionTrace({ provenance, summary, defaultOpen = false }: Props) {
  const { t } = useT();
  const [open, setOpen] = useState(defaultOpen);
  const [sqlOpen, setSqlOpen] = useState(false);
  const [sqlCopied, setSqlCopied] = useState(false);

  const copySql = async (raw: string) => {
    try {
      await navigator.clipboard.writeText(raw);
      setSqlCopied(true);
      toast(t('trace.toast.copied', 'SQL copied to clipboard'), 'success');
      setTimeout(() => setSqlCopied(false), 1800);
    } catch {
      toast(t('trace.toast.copy_failed', 'Copy failed — select the SQL manually'), 'error');
    }
  };

  if (!provenance) return null;

  const trace = provenance.reasoning_trace || null;
  const steps = trace?.steps || [];
  const execTime = provenance.execution_time_ms;
  const sql = provenance.sql_executed || '';
  const method = provenance.sql_method || null;
  const intent = provenance.parsed_intent || null;
  const sources = provenance.data_sources || [];
  const corrections = trace?.summary.correction_count || 0;

  return (
    <div className="border border-line-subtle rounded-lg mt-3 bg-canvas-subtle/40">
      <button
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="flex items-center gap-2 w-full px-3 py-2 text-xs text-ink-muted hover:text-ink transition-colors"
      >
        {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        <Cpu size={12} />
        <span className="font-medium">{t('trace.details', 'Execution details')}</span>
        {steps.length > 0 && (
          <span className="text-2xs text-ink-subtle">{steps.length} {t('trace.steps', 'steps')}</span>
        )}
        {corrections > 0 && (
          <span className="text-2xs px-1.5 py-0.5 rounded-full bg-amber-50 text-amber-700 border border-amber-200">
            {corrections} {corrections === 1 ? t('trace.selfcorrection', 'self-correction') : t('trace.selfcorrections', 'self-corrections')}
          </span>
        )}
        {execTime != null && (
          <span className="ml-auto flex items-center gap-1 text-2xs text-ink-subtle">
            <Clock size={10} />
            {fmtMs(execTime)}
          </span>
        )}
      </button>

      {open && (
        <div className="px-3 pb-3 border-t border-line-subtle">
          {summary && <p className="pt-2 text-xs text-ink-muted">{summary}</p>}

          {/* Top-line method / intent / sources */}
          <div className="flex flex-wrap items-center gap-1.5 pt-2">
            {intent && (
              <span className="text-2xs text-ink-muted">
                {t('trace.intent', 'intent')} <span className="badge badge-gray text-2xs">{intent}</span>
              </span>
            )}
            {method && (
              <span className="text-2xs text-ink-muted">
                {t('trace.method', 'method')} <span className="badge badge-gray text-2xs">{method}</span>
              </span>
            )}
            {sources.length > 0 && (
              <span className="inline-flex items-center gap-1 text-2xs text-ink-muted">
                <Layers size={11} className="text-ink-subtle" />
                {sources.map((s) => (
                  <span key={s} className="badge badge-gray text-2xs">{s}</span>
                ))}
              </span>
            )}
          </div>

          {/* The step-by-step timeline (real per-stage trace) */}
          {steps.length > 0 ? (
            <ol className="mt-3 space-y-2.5">
              {steps.map((step) => {
                const meta = STAGE_META[step.stage];
                const label = meta ? t(meta.key, meta.en) : step.stage;
                const Icon = meta ? meta.icon : Cpu;
                const isCorrection = step.stage === 'correct' || !!step.correction_of;
                return (
                  <li
                    key={step.step_id}
                    className={`relative pl-6 ${isCorrection ? 'ml-2' : ''}`}
                  >
                    <span className="absolute left-0 top-0.5"><StatusIcon status={step.status} /></span>
                    <div className="flex items-center gap-2 flex-wrap">
                      <Icon size={12} className="text-ink-subtle shrink-0" />
                      <span className="text-xs font-medium text-ink">{label}</span>
                      {step.duration_ms > 0 && (
                        <span className="text-2xs text-ink-subtle tabular-nums">{fmtMs(step.duration_ms)}</span>
                      )}
                      {step.status === 'corrected' && (
                        <span className="text-2xs text-amber-600">{t('trace.superseded', 'superseded')}</span>
                      )}
                    </div>
                    {step.title && step.title !== label && (
                      <p className="text-2xs text-ink-muted mt-0.5">{step.title}</p>
                    )}
                    {step.rationale && (
                      <p className="text-2xs text-ink-subtle italic mt-0.5">{step.rationale}</p>
                    )}
                    <StageOutput step={step} />
                  </li>
                );
              })}
            </ol>
          ) : (
            <p className="mt-3 text-2xs text-ink-subtle">
              {t('trace.fastpath', 'Structured fast-path (no LLM trace). Filters were applied directly.')}
            </p>
          )}

          {/* Final executed SQL — the exact statement run against the DB,
              pretty-printed so each WHERE/AND/OR predicate is on its own line. */}
          {sql && (
            <div className="mt-3">
              <div className="flex items-center justify-between gap-2">
                <button
                  onClick={() => setSqlOpen(!sqlOpen)}
                  aria-expanded={sqlOpen}
                  className="flex items-center gap-1.5 text-2xs text-ink-muted hover:text-ink"
                >
                  {sqlOpen ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
                  <Database size={11} />
                  <span className="font-medium">{t('trace.final_sql', 'Final SQL executed')}</span>
                  <span className="text-ink-subtle">({sql.length} {t('trace.chars', 'chars')})</span>
                </button>
                {sqlOpen && (
                  <button
                    onClick={() => copySql(sql)}
                    className="btn-ghost text-2xs inline-flex items-center gap-1 px-1.5 py-0.5 shrink-0"
                    aria-label={t('trace.copy.aria', 'Copy SQL to clipboard')}
                  >
                    {sqlCopied ? <Check size={10} /> : <Copy size={10} />}
                    {sqlCopied ? t('trace.copied', 'Copied') : t('trace.copy', 'Copy')}
                  </button>
                )}
              </div>
              {sqlOpen && (
                <pre
                  className="mt-1.5 p-3 bg-ink rounded-lg text-2xs overflow-x-auto whitespace-pre font-mono leading-relaxed text-slate-100"
                  dangerouslySetInnerHTML={{ __html: highlightSql(formatSql(sql)) }}
                />
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
