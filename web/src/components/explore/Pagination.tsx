import { ChevronLeft, ChevronRight } from 'lucide-react';
import { useT } from '../../lib/i18n';

interface Props { page: number; totalCount: number; limit: number; onPageChange: (p: number) => void; }

export function Pagination({ page, totalCount, limit, onPageChange }: Props) {
  const { t } = useT();
  const pages = Math.max(1, Math.ceil(totalCount / limit));
  if (totalCount === 0) return null;

  const btns: (number | string)[] = [];
  if (pages <= 7) { for (let i = 1; i <= pages; i++) btns.push(i); }
  else {
    btns.push(1);
    if (page > 3) btns.push('...');
    for (let i = Math.max(2, page - 1); i <= Math.min(pages - 1, page + 1); i++) btns.push(i);
    if (page < pages - 2) btns.push('...');
    btns.push(pages);
  }

  return (
    <nav className="flex items-center justify-between py-3" aria-label={t('pagination.aria', 'Pagination')}>
      <span className="text-xs text-ink-subtle tabular-nums">
        {((page - 1) * limit + 1).toLocaleString()}–{Math.min(page * limit, totalCount).toLocaleString()} {t('pagination.of', 'of')} {totalCount.toLocaleString()}
      </span>
      <div className="flex items-center gap-0.5">
        <button
          onClick={() => onPageChange(page - 1)}
          disabled={page <= 1}
          aria-label={t('pagination.prev.aria', 'Previous page')}
          className="btn-ghost p-1 disabled:opacity-20 disabled:cursor-not-allowed"
        >
          <ChevronLeft size={16} className="text-ink-muted" />
        </button>
        {btns.map((p, i) =>
          typeof p === 'string' ? (
            <span key={`gap-${i}`} className="px-1 text-ink-subtle text-xs" aria-hidden="true">
              …
            </span>
          ) : (
            <button
              key={`page-${p}`}
              onClick={() => onPageChange(p)}
              aria-label={`${t('pagination.goto.aria', 'Go to page')} ${p}`}
              aria-current={p === page ? 'page' : undefined}
              className={`min-w-[26px] h-[26px] text-xs rounded font-medium transition-colors ${
                p === page
                  ? 'bg-accent text-white'
                  : 'text-ink-muted hover:bg-canvas-muted'
              }`}
            >
              {p}
            </button>
          ),
        )}
        <button
          onClick={() => onPageChange(page + 1)}
          disabled={page >= pages}
          aria-label={t('pagination.next.aria', 'Next page')}
          className="btn-ghost p-1 disabled:opacity-20 disabled:cursor-not-allowed"
        >
          <ChevronRight size={16} className="text-ink-muted" />
        </button>
      </div>
    </nav>
  );
}
