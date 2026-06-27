import { useEffect, useState } from 'react';
import { NavLink, useNavigate, useLocation } from 'react-router-dom';
import {
  Search,
  Menu,
  X,
  Home,
  Compass,
  BarChart3,
  Sparkles,
  Download,
  Bookmark,
  Radio,
  Languages,
  Info,
} from 'lucide-react';
import { useManifest } from '../../hooks/useManifest';
import { ManifestPanel } from '../manifest/ManifestPanel';
import { ProvenanceBadge } from './ProvenanceBadge';
import { useT } from '../../lib/i18n';

interface NavItem {
  id: string;
  to: string;
  label: string;
  i18nKey: string;
  icon: React.ElementType;
  end?: boolean;
}

const NAV_ITEMS: NavItem[] = [
  { id: 'home', to: '/', label: 'Home', i18nKey: 'nav.home', icon: Home, end: true },
  { id: 'explore', to: '/explore', label: 'Explore', i18nKey: 'nav.explore', icon: Compass, end: false },
  { id: 'discover', to: '/discover', label: 'Discover', i18nKey: 'nav.discover', icon: Radio, end: false },
  { id: 'stats', to: '/stats', label: 'Statistics', i18nKey: 'nav.stats', icon: BarChart3, end: false },
  { id: 'search', to: '/search', label: 'Advanced', i18nKey: 'nav.advanced', icon: Sparkles, end: false },
  { id: 'workspace', to: '/workspace', label: 'Workspace', i18nKey: 'nav.workspace', icon: Bookmark, end: false },
  { id: 'downloads', to: '/downloads', label: 'Downloads', i18nKey: 'nav.downloads', icon: Download, end: false },
  { id: 'about', to: '/about', label: 'About', i18nKey: 'nav.about', icon: Info, end: false },
];

// Pulled from Vite's `define` at build time; declared in vite.config.ts.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const APP_VERSION: string = (typeof __APP_VERSION__ !== 'undefined' ? __APP_VERSION__ : '0.0.0') as any;

export function TopNav() {
  const navigate = useNavigate();
  const location = useLocation();
  const [query, setQuery] = useState('');
  const [mobileOpen, setMobileOpen] = useState(false);
  const [isScrolled, setIsScrolled] = useState(false);
  const [manifestOpen, setManifestOpen] = useState(false);
  const { count: manifestCount } = useManifest();
  const { t, lang, setLang } = useT();

  const isHomePage = location.pathname === '/';
  const useDarkSurface = isHomePage && !isScrolled;

  // Close the mobile drawer on every route change. setMobileOpen here is
  // intentional — it's the cleanup mechanism for a navigation side-effect.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (location.pathname) setMobileOpen(false);
  }, [location.pathname]);

  // The home page scrolls an inner overflow container (#home-scroll), not the
  // window — so listen on that element when present (else fall back to window),
  // and re-attach on navigation. Without this the transparent→solid nav never
  // triggered on the landing page.
  useEffect(() => {
    const scroller = document.getElementById('home-scroll');
    const getY = () => (scroller ? scroller.scrollTop : window.scrollY);
    const handleScroll = () => setIsScrolled(getY() > 10);
    handleScroll();
    const target: HTMLElement | Window = scroller ?? window;
    target.addEventListener('scroll', handleScroll, { passive: true });
    return () => target.removeEventListener('scroll', handleScroll);
  }, [location.pathname]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    const q = query.trim();
    if (!q) return;
    // Simple heuristic: looks like an accession id → deep-link; otherwise
    // keyword search via Explore. Long natural-language queries can still
    // be routed manually to Advanced or Discover.
    const isAccession = /^(GSE|GSM|GPL|SRR|SRP|SRS|SRX|PRJ|E-(MTAB|GEOD|PROT|TABM)|SCEA|HCA|CXG|CZI)[A-Z0-9-]+$/i.test(q);
    if (isAccession) {
      navigate(`/explore/${encodeURIComponent(q)}`);
    } else {
      navigate(`/explore?q=${encodeURIComponent(q)}`);
    }
    setQuery('');
  };

  return (
    <>
      <header
        className={`fixed top-0 left-0 right-0 z-40 transition-all duration-300 ${
          useDarkSurface
            ? 'bg-transparent'
            : isHomePage
              ? 'bg-[var(--nav-bg)]/95 backdrop-blur-xl shadow-sm'
              : 'bg-white/95 backdrop-blur-xl shadow-sm border-b border-line'
        }`}
      >
        {/* Nav is intentionally wider than the 1280 content column: it carries more
            horizontal elements (7 nav items + search + manifest + lang + badge) and
            EN labels are wider than 中文 — at 1280 the Downloads item overflowed into
            the search box. 1536 gives EN comfortable slack with no overlap. */}
        <div className="max-w-[1536px] mx-auto px-6">
          <nav className="flex items-center justify-between h-16 gap-3">
            <NavLink to="/" className="flex items-center gap-2.5 shrink-0 group">
              <BrandMark dark={useDarkSurface || isHomePage} />
              <span
                className={`text-lg font-bold tracking-tight transition-colors ${
                  useDarkSurface || isHomePage ? 'text-white' : 'text-ink'
                }`}
              >
                Singligent
              </span>
              <span
                className={`text-2xs px-1.5 py-0.5 rounded-full font-medium ${
                  useDarkSurface
                    ? 'bg-white/20 text-white/90'
                    : isHomePage
                      ? 'bg-accent/20 text-[var(--nav-accent)]'
                      : 'bg-accent-subtle text-accent'
                }`}
                title={`Build ${APP_VERSION}`}
              >
                v{APP_VERSION}
              </span>
            </NavLink>

            <div className="hidden lg:flex items-center gap-0.5 min-w-0">
              {NAV_ITEMS.map((item) => {
                const Icon = item.icon;
                const isActive = item.end
                  ? location.pathname === item.to
                  : location.pathname.startsWith(item.to);
                return (
                  <NavLink
                    key={item.id}
                    to={item.to}
                    end={item.end}
                    className={`px-2 py-2 text-sm font-medium rounded-md whitespace-nowrap transition-all duration-150 ${
                      useDarkSurface || isHomePage
                        ? isActive
                          ? 'text-white bg-white/15'
                          : 'text-white/75 hover:text-white hover:bg-white/10'
                        : isActive
                          ? 'text-accent bg-accent-subtle'
                          : 'text-ink-muted hover:text-ink hover:bg-canvas-subtle'
                    }`}
                  >
                    <span className="flex items-center gap-1.5 whitespace-nowrap">
                      <Icon className="w-4 h-4 shrink-0" />
                      {t(item.i18nKey, item.label)}
                    </span>
                  </NavLink>
                );
              })}
            </div>

            <div className="flex-1" />

            <form onSubmit={handleSearch} className="hidden xl:block w-[200px]">
              <div className="relative">
                <Search
                  className={`absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 ${
                    useDarkSurface || isHomePage ? 'text-white/40' : 'text-ink-subtle'
                  }`}
                />
                <input
                  type="text"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder={t('nav.search.placeholder', 'Search ID or keyword…')}
                  aria-label={t('nav.search.aria', 'Quick search')}
                  className={`w-full pl-9 pr-3 py-1.5 text-sm rounded-md transition-all focus:outline-none ${
                    useDarkSurface || isHomePage
                      ? 'bg-white/10 border border-white/10 text-white placeholder:text-white/40 focus:bg-white/15 focus:border-[var(--nav-accent)]/40'
                      : 'bg-canvas-subtle border border-line text-ink placeholder:text-ink-subtle focus:bg-white focus:border-accent'
                  }`}
                />
              </div>
            </form>

            <button
              onClick={() => setManifestOpen(true)}
              className={`hidden lg:inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs whitespace-nowrap transition-colors ${
                useDarkSurface || isHomePage
                  ? 'bg-white/10 text-white/80 hover:bg-white/15 hover:text-white'
                  : manifestCount > 0
                    ? 'bg-accent-subtle text-accent hover:bg-accent-bg'
                    : 'text-ink-muted hover:bg-canvas-subtle'
              }`}
              aria-label={t('nav.manifest', 'Manifest')}
            >
              <Download size={13} className="shrink-0" />
              {t('nav.manifest', 'Manifest')}
              {manifestCount > 0 && (
                <span className="tabular-nums font-medium">({manifestCount})</span>
              )}
            </button>

            {/* Phase 37: EN / 中文 language toggle — the agent understands both. */}
            <button
              onClick={() => setLang(lang === 'zh' ? 'en' : 'zh')}
              className={`hidden lg:inline-flex items-center gap-1 px-2 py-1.5 rounded-md text-xs font-medium transition-colors ${
                useDarkSurface || isHomePage
                  ? 'text-white/75 hover:bg-white/15 hover:text-white'
                  : 'text-ink-muted hover:bg-canvas-subtle hover:text-ink'
              }`}
              aria-label={t('lang.toggle.aria', 'Switch language')}
              title={t('lang.toggle.aria', 'Switch language')}
            >
              <Languages size={13} />
              {lang === 'zh' ? 'EN' : '中'}
            </button>

            <div className="hidden xl:flex shrink-0">
              <ProvenanceBadge dark={useDarkSurface || isHomePage} />
            </div>

            <button
              onClick={() => setMobileOpen(!mobileOpen)}
              className={`lg:hidden p-2 rounded-md transition-colors ${
                useDarkSurface || isHomePage
                  ? 'text-white hover:bg-white/10'
                  : 'text-ink-muted hover:bg-canvas-subtle'
              }`}
              aria-label="Toggle navigation menu"
              aria-expanded={mobileOpen}
            >
              {mobileOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
            </button>
          </nav>
        </div>
      </header>

      {/* Mobile / tablet menu (below lg) */}
      <div
        className={`lg:hidden fixed top-16 left-0 right-0 z-40 bg-white border-b border-line shadow-lg transition-all duration-300 ${
          mobileOpen ? 'opacity-100 visible' : 'opacity-0 invisible pointer-events-none'
        }`}
      >
        <div className="px-4 py-4 space-y-1">
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            const isActive = item.end
              ? location.pathname === item.to
              : location.pathname.startsWith(item.to);
            return (
              <NavLink
                key={item.id}
                to={item.to}
                end={item.end}
                className={`flex items-center gap-3 px-4 py-2.5 rounded-md text-sm font-medium transition-colors ${
                  isActive
                    ? 'text-accent bg-accent-subtle'
                    : 'text-ink-muted hover:text-ink hover:bg-canvas-subtle'
                }`}
              >
                <Icon className="w-4 h-4" />
                {t(item.i18nKey, item.label)}
              </NavLink>
            );
          })}
          <button
            onClick={() => {
              setMobileOpen(false);
              setManifestOpen(true);
            }}
            className="w-full flex items-center gap-3 px-4 py-2.5 rounded-md text-sm font-medium text-ink-muted hover:bg-canvas-subtle"
          >
            <Download className="w-4 h-4" />
            {t('nav.manifest', 'Manifest')} {manifestCount > 0 && <span className="tabular-nums">({manifestCount})</span>}
          </button>
          <button
            onClick={() => setLang(lang === 'zh' ? 'en' : 'zh')}
            className="w-full flex items-center gap-3 px-4 py-2.5 rounded-md text-sm font-medium text-ink-muted hover:bg-canvas-subtle"
          >
            <Languages className="w-4 h-4" />
            {lang === 'zh' ? 'English' : '中文'}
          </button>
          <div className="pt-3 mt-3 border-t border-line-subtle">
            <form onSubmit={handleSearch} className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-ink-subtle" />
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search ID or keyword…"
                className="w-full pl-9 pr-3 py-2 text-sm bg-canvas-subtle border border-line rounded-md text-ink placeholder:text-ink-subtle focus:outline-none focus:bg-white focus:border-accent"
              />
            </form>
          </div>
        </div>
      </div>

      <ManifestPanel open={manifestOpen} onClose={() => setManifestOpen(false)} />
    </>
  );
}

// Singligent mark: a hexagonal cell membrane enclosing a small data network
// (single-cell biology × intelligence). Crisp SVG, theme-adaptive (dark nav vs
// light). Matches the brand logomark in /public/brand/logo.png.
function BrandMark({ dark }: { dark: boolean }) {
  const ring = dark ? '#38bdf8' : 'var(--accent)';
  const line = dark ? 'rgba(125,211,252,0.5)' : 'rgba(27,111,168,0.42)';
  const node = dark ? '#7dd3fc' : '#1B6FA8';
  const N = [
    [16, 8.5], [23.2, 12.8], [21, 21.2], [11, 21.2], [8.8, 12.8],
  ] as const;
  return (
    <div className="relative w-8 h-8 flex items-center justify-center">
      <svg viewBox="0 0 32 32" className="w-7 h-7" fill="none" aria-hidden="true">
        <path
          d="M16 3 L27.3 9.5 L27.3 22.5 L16 29 L4.7 22.5 L4.7 9.5 Z"
          stroke={ring} strokeWidth="2" strokeLinejoin="round"
        />
        <g stroke={line} strokeWidth="1.3" strokeLinecap="round">
          {N.map(([x, y], i) => <line key={`c${i}`} x1="16" y1="16" x2={x} y2={y} />)}
          {N.map(([x, y], i) => {
            const [x2, y2] = N[(i + 1) % N.length];
            return <line key={`r${i}`} x1={x} y1={y} x2={x2} y2={y2} />;
          })}
        </g>
        {N.map(([x, y], i) => <circle key={`n${i}`} cx={x} cy={y} r="1.6" fill={node} />)}
        <circle cx="16" cy="16" r="2.4" fill={ring} />
      </svg>
    </div>
  );
}
