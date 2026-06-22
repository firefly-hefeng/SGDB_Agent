import { useEffect } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { TopNav } from './components/layout/TopNav';
import { ErrorBoundary } from './components/ErrorBoundary';
import { ToastHost } from './components/ui/Toast';
import { useStats } from './hooks/useStats';
import { useT } from './lib/i18n';

const BASE_TITLE = 'Singligent';

// Map a route to a translated page-name key (+ English fallback). Static routes
// match exactly; the two detail routes are matched by prefix below.
const ROUTE_TITLES: { match: (p: string) => boolean; key: string; fallback: string }[] = [
  { match: (p) => p === '/', key: 'nav.home', fallback: 'Home' },
  { match: (p) => p === '/explore', key: 'nav.explore', fallback: 'Explore' },
  { match: (p) => p === '/projects', key: 'common.projects', fallback: 'Projects' },
  { match: (p) => p === '/series', key: 'common.series', fallback: 'Series' },
  { match: (p) => p === '/about', key: 'nav.about', fallback: 'About data' },
  { match: (p) => p === '/stats', key: 'nav.stats', fallback: 'Statistics' },
  { match: (p) => p === '/search', key: 'nav.advanced', fallback: 'Advanced search' },
  { match: (p) => p === '/downloads', key: 'nav.downloads', fallback: 'Downloads' },
  { match: (p) => p.startsWith('/workspace'), key: 'nav.workspace', fallback: 'Workspace' },
  { match: (p) => p === '/discover', key: 'nav.discover', fallback: 'Discover' },
  { match: (p) => p.startsWith('/explore/'), key: 'nav.explore', fallback: 'Dataset' },
];

function App() {
  const location = useLocation();
  const isHomePage = location.pathname === '/';
  const { lang, t } = useT();

  // Single global stats subscription so any descendant rerenders when
  // the cached stats arrive.
  useStats();

  // WCAG 3.1.1 — keep <html lang> in sync with the chosen UI language on
  // every render path (initial load + toggle), not only on toggle.
  useEffect(() => {
    document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en';
  }, [lang]);

  // WCAG 2.4.2 — a descriptive, per-route document title.
  useEffect(() => {
    const route = ROUTE_TITLES.find((r) => r.match(location.pathname));
    const page = route ? t(route.key, route.fallback) : null;
    document.title = page ? `${BASE_TITLE} — ${page}` : BASE_TITLE;
  }, [location.pathname, lang, t]);

  return (
    <ErrorBoundary>
      <div className="flex flex-col h-screen bg-canvas text-ink">
        <TopNav />
        {/* Spacer for the fixed header on non-home pages. */}
        {!isHomePage && <div className="h-16 shrink-0" />}
        <main className="flex flex-1 min-h-0 overflow-hidden">
          {/* Keyed so each route replays a brief entrance (route-enter). */}
          <div key={location.pathname} className="route-enter flex flex-1 min-h-0">
            <Outlet />
          </div>
        </main>
        <ToastHost />
      </div>
    </ErrorBoundary>
  );
}

export default App;
