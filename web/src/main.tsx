import { StrictMode, Suspense, lazy } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import './index.css';
import App from './App';
import { LanguageProvider } from './lib/i18n';

// Eager: the landing page is the most common entry, so we keep it in the
// initial bundle and lazy everything else.
import LandingPage from './pages/LandingPage';

const ExplorePage = lazy(() => import('./pages/ExplorePage'));
const ProjectsExplorePage = lazy(() => import('./pages/ProjectsExplorePage'));
const SeriesExplorePage = lazy(() => import('./pages/SeriesExplorePage'));
const DatasetDetailPage = lazy(() => import('./pages/DatasetDetailPage'));
const AboutPage = lazy(() => import('./pages/AboutPage'));
const StatsPage = lazy(() => import('./pages/StatsPage'));
const AdvancedSearchPage = lazy(() => import('./pages/AdvancedSearchPage'));
const DownloadsPage = lazy(() => import('./pages/DownloadsPage'));
const WorkspacePage = lazy(() => import('./pages/WorkspacePage'));
const DiscoverPage = lazy(() => import('./pages/DiscoverPage'));

// These small route-helper components live alongside the router config by
// design; fast-refresh's components-only rule doesn't meaningfully apply to
// an entry file that also runs createRoot. (Matches the i18n.tsx convention.)
// eslint-disable-next-line react-refresh/only-export-components
function RouteFallback() {
  return (
    <div className="flex-1 flex flex-col items-center justify-center gap-3 px-6">
      <div className="w-7 h-7 rounded-full border-2 border-accent border-t-transparent animate-spin" />
      <p className="text-xs text-ink-subtle">Loading page…</p>
    </div>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
function NotFoundPage() {
  return (
    <div className="flex-1 flex items-center justify-center px-6">
      <div className="max-w-md text-center">
        <p className="text-2xs uppercase tracking-wider text-ink-subtle mb-2">404</p>
        <h1 className="text-xl font-semibold text-ink mb-2">
          We couldn't find that page
        </h1>
        <p className="text-sm text-ink-muted mb-4">
          The URL may have moved or never existed. Try Explore, Discover, or head back home.
        </p>
        <div className="flex items-center justify-center gap-2">
          <a href="/singligent/" className="btn btn-accent text-sm">
            Home
          </a>
          <a href="/singligent/explore" className="btn btn-secondary text-sm">
            Explore catalog
          </a>
          <a href="/singligent/discover" className="btn btn-secondary text-sm">
            Live discovery
          </a>
        </div>
      </div>
    </div>
  );
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <LanguageProvider>
    <BrowserRouter basename="/singligent">
      <Routes>
        <Route element={<App />}>
          <Route index element={<LandingPage />} />
          <Route
            element={
              <Suspense fallback={<RouteFallback />}>
                <RouterShell />
              </Suspense>
            }
          >
            <Route path="explore" element={<ExplorePage />} />
            <Route path="explore/:id" element={<DatasetDetailPage />} />
            <Route path="projects" element={<ProjectsExplorePage />} />
            <Route path="series" element={<SeriesExplorePage />} />
            {/* cell-type browse page removed (redundant with Samples + its cell_type
                facet); redirect old links to Explore. Cell-type data remains via
                the /celltypes/search API and the Explore cell_type filter. */}
            <Route path="celltypes" element={<Navigate to="/explore" replace />} />
            <Route path="about" element={<AboutPage />} />
            <Route path="stats" element={<StatsPage />} />
            <Route path="search" element={<AdvancedSearchPage />} />
            <Route path="chat" element={<Navigate to="/search" replace />} />
            <Route path="downloads" element={<DownloadsPage />} />
            <Route path="workspace" element={<WorkspacePage />} />
            <Route path="workspace/:id" element={<WorkspacePage />} />
            <Route path="discover" element={<DiscoverPage />} />
            {/* legacy alias, kept for any bookmark from Phase 22-G */}
            <Route path="cross-api" element={<Navigate to="/discover" replace />} />
          </Route>
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
    </LanguageProvider>
  </StrictMode>,
);

// Inner shell used to wrap the lazy-loaded routes in a Suspense boundary
// without making the parent <App /> itself suspend (which would unmount
// the TopNav).
import { Outlet } from 'react-router-dom';
// eslint-disable-next-line react-refresh/only-export-components
function RouterShell() {
  return <Outlet />;
}
