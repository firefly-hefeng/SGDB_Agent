import type { ReactNode } from 'react';

/**
 * Branded eyebrow — accent label with a short accent rule. Shared so every page
 * header (canonical or hand-rolled dense ones) reads in the same register.
 */
export function Eyebrow({ children, icon }: { children: ReactNode; icon?: ReactNode }) {
  return (
    <p className="flex items-center gap-2 text-2xs uppercase tracking-wider text-accent mb-1.5 font-semibold">
      {icon ?? <span className="w-4 h-px bg-accent/60" aria-hidden="true" />}
      {children}
    </p>
  );
}

interface Props {
  eyebrow?: string;
  eyebrowIcon?: ReactNode;
  title: string;
  description?: string;
  actions?: ReactNode;
  /** Render compactly (less vertical padding) for inner pages. */
  compact?: boolean;
}

/**
 * Canonical page header — eyebrow / h1 / supporting blurb / right-aligned
 * actions, on the shared `.page-header-band` chrome (brand wash + gradient
 * hairline). Used by every top-level page for one consistent visual hierarchy.
 */
export function PageHeader({ eyebrow, eyebrowIcon, title, description, actions, compact = false }: Props) {
  return (
    <header className={`page-header-band overflow-hidden px-6 ${compact ? 'pt-6 pb-4' : 'pt-8 pb-5'} bg-canvas`}>
      <div className="relative max-w-[1280px] mx-auto flex items-start justify-between gap-4">
        <div className="min-w-0">
          {eyebrow && <Eyebrow icon={eyebrowIcon}>{eyebrow}</Eyebrow>}
          <h1 className={`${compact ? 'text-2xl' : 'text-3xl'} font-semibold tracking-tight text-ink leading-tight`}>
            {title}
          </h1>
          {description && (
            <p className="text-sm text-ink-muted mt-2 max-w-[60rem] leading-relaxed">
              {description}
            </p>
          )}
        </div>
        {actions && <div className="flex items-center gap-2 shrink-0 pt-1">{actions}</div>}
      </div>
    </header>
  );
}
