import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, MessageSquare, SlidersHorizontal } from 'lucide-react';
import { useT } from '../../lib/i18n';

interface Props {
  textSearch: string; nlQuery: string;
  onTextSearchChange: (t: string) => void; onNlQueryChange: (t: string) => void;
}

export function SearchBar({ textSearch, nlQuery, onTextSearchChange, onNlQueryChange }: Props) {
  const navigate = useNavigate();
  const { t } = useT();
  const [mode, setMode] = useState<'keyword' | 'nl'>(nlQuery ? 'nl' : 'keyword');
  const [val, setVal] = useState(mode === 'nl' ? nlQuery : textSearch);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (mode === 'nl' && val.trim()) navigate(`/search?q=${encodeURIComponent(val.trim())}`);
    else onTextSearchChange(val.trim());
  };

  const switchMode = (m: 'keyword' | 'nl') => {
    setMode(m);
    setVal('');
    if (m === 'keyword') onNlQueryChange('');
    else onTextSearchChange('');
  };

  return (
    <form onSubmit={submit} className="flex gap-2 mb-3">
      <div className="relative flex-1">
        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-subtle pointer-events-none" />
        <input type="text" value={val} onChange={(e) => setVal(e.target.value)}
          placeholder={mode === 'nl' ? t('searchbar.nl.placeholder', 'Ask in natural language...') : t('searchbar.keyword.placeholder', 'Search by keyword...')}
          className="w-full pl-9 pr-3 py-2 text-sm bg-white border border-line rounded-md focus:outline-none focus:border-accent focus:ring-2 focus:ring-[var(--accent-bg)]" />
      </div>
      <button type="submit" className="btn btn-primary text-sm">{t('searchbar.submit', 'Search')}</button>
      <div className="flex border border-line rounded-md overflow-hidden bg-white">
        <button type="button" onClick={() => switchMode('keyword')} title={t('searchbar.mode.keyword', 'Keyword')}
          className={`px-2.5 py-2 transition-colors ${mode === 'keyword' ? 'bg-canvas-muted text-ink' : 'text-ink-subtle hover:text-ink-muted'}`}>
          <SlidersHorizontal size={14} />
        </button>
        <div className="w-px bg-[var(--border)]" />
        <button type="button" onClick={() => switchMode('nl')} title={t('searchbar.mode.ai', 'AI')}
          className={`px-2.5 py-2 transition-colors ${mode === 'nl' ? 'bg-canvas-muted text-ink' : 'text-ink-subtle hover:text-ink-muted'}`}>
          <MessageSquare size={14} />
        </button>
      </div>
    </form>
  );
}
