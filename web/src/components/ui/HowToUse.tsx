import { useId, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { Info, ChevronDown, ArrowUpRight } from 'lucide-react';
import { useT } from '../../lib/i18n';

export interface HowToExample {
  /** Short, copy-pasteable label, e.g. `tissue=lung disease=COVID-19`. */
  label: string;
  /** Optional in-app route (renders a Link) — e.g. `/explore?tissue=lung`. */
  to?: string;
  /** Optional external URL (renders an anchor). Takes precedence over `to`. */
  href?: string;
  /**
   * Optional click handler (renders a button). Used by pages with local-state
   * search boxes (Advanced, Discover) to drop the example into the input.
   */
  onPick?: () => void;
  /** Optional one-line explanation shown beneath the example. */
  hint?: string;
}

interface Props {
  /** What this surface is for / when to reach for it vs. the others. */
  body: ReactNode;
  /** 2-3 concrete, real example queries / IDs. */
  examples?: HowToExample[];
  /** Open by default (e.g. on a landing-style page). Defaults to collapsed. */
  defaultOpen?: boolean;
  /** Override the trigger label (already-translated). */
  label?: string;
  className?: string;
}

/**
 * Collapsible "How to use / Examples" affordance (Phase 39).
 *
 * Surfaces a per-module usage intro plus concrete, real example queries so the
 * portal is self-explanatory. Copy is passed in already-translated by the caller
 * (pages use `t()`); the chrome strings here are translated via the shared `t()`.
 */
export function HowToUse({ body, examples, defaultOpen = false, label, className }: Props) {
  const { t } = useT();
  const [open, setOpen] = useState(defaultOpen);
  const panelId = useId();

  return (
    <div
      className={`rounded-md border border-accent-border bg-accent-bg/60 ${className ?? ''}`}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={panelId}
        className="w-full flex items-center gap-2 px-3 py-2 text-left text-xs font-medium text-accent hover:bg-accent-bg rounded-md transition-colors"
      >
        <Info size={13} className="shrink-0" />
        <span className="flex-1">{label ?? t('howto.trigger', 'How to use / Examples')}</span>
        <ChevronDown
          size={14}
          className={`shrink-0 transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>

      {open && (
        <div id={panelId} className="px-3 pb-3 pt-0.5 border-t border-accent-border/60">
          <div className="text-xs text-ink-muted leading-relaxed mt-2 max-w-[760px]">
            {body}
          </div>

          {examples && examples.length > 0 && (
            <div className="mt-2.5">
              <p className="text-2xs uppercase tracking-wider text-ink-subtle font-medium mb-1.5">
                {t('howto.examples', 'Try these')}
              </p>
              <ul className="flex flex-col gap-1.5">
                {examples.map((ex, i) => (
                  <li key={i} className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                    <ExampleChip ex={ex} />
                    {ex.hint && (
                      <span className="text-2xs text-ink-subtle">— {ex.hint}</span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ExampleChip({ ex }: { ex: HowToExample }) {
  const cls =
    'inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-white border border-accent-border ' +
    'font-mono text-2xs text-accent hover:bg-accent-subtle transition-colors';

  if (ex.href) {
    return (
      <a href={ex.href} target="_blank" rel="noreferrer" className={cls}>
        {ex.label}
        <ArrowUpRight size={10} className="opacity-70" />
      </a>
    );
  }
  if (ex.to) {
    return (
      <Link to={ex.to} className={cls}>
        {ex.label}
        <ArrowUpRight size={10} className="opacity-70" />
      </Link>
    );
  }
  if (ex.onPick) {
    return (
      <button type="button" onClick={ex.onPick} className={cls}>
        {ex.label}
      </button>
    );
  }
  return (
    <span className="inline-flex items-center px-1.5 py-0.5 rounded bg-white border border-line font-mono text-2xs text-ink-muted">
      {ex.label}
    </span>
  );
}
