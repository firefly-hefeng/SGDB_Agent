/**
 * Pill switcher between sample / series / project / cell-type explore pages.
 *
 * Carries the current location.search across so a shared filter
 * (q, source_database, organism) survives the switch. Each page
 * picks up only the params it knows about.
 *
 * Single-row segmented control (3 short labels fit inline): a tinted track with
 * a raised white active pill, the modern iOS/Linear pattern. Labels are i18n.
 */

import { NavLink, useLocation } from 'react-router-dom';
import { useT } from '../../lib/i18n';

const TABS: { to: string; key: string; label: string }[] = [
  { to: '/explore', key: 'tabs.sample', label: 'Sample' },
  { to: '/series', key: 'tabs.series', label: 'Series' },
  { to: '/projects', key: 'tabs.project', label: 'Project' },
];

export function TargetLevelTabs() {
  const location = useLocation();
  const search = location.search || '';
  const { t } = useT();

  return (
    <div className="inline-flex gap-0.5 p-0.5 rounded-lg border border-line bg-canvas-subtle">
      {TABS.map((tab) => (
        <NavLink
          key={tab.to}
          to={`${tab.to}${search}`}
          end
          className={({ isActive }) =>
            `px-3 py-1 text-xs font-medium rounded-md whitespace-nowrap transition-all duration-150 ${
              isActive
                ? 'bg-white text-accent shadow-sm ring-1 ring-line'
                : 'text-ink-muted hover:text-ink'
            }`
          }
        >
          {t(tab.key, tab.label)}
        </NavLink>
      ))}
    </div>
  );
}
