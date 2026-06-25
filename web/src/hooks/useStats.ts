import { useEffect, useState } from 'react';
import { getStats, getDashboardStats } from '../services/api';
import type { StatsResponse, DashboardStats } from '../types/api';

interface UseStatsResult {
  stats: StatsResponse | null;
  dashboard: DashboardStats | null;
  loading: boolean;
  error: string | null;
}

let _statsCache: StatsResponse | null = null;
let _dashboardCache: DashboardStats | null = null;
// SHARED module-level loading/error — must NOT be per-component local state, or
// only the first component to mount gets updates (later mounters would never see
// the error and could show a stuck/empty state). All consumers read these.
let _loading = false;
let _error: string | null = null;
let _loaded = false;
const _listeners = new Set<() => void>();

function emit() {
  for (const cb of _listeners) cb();
}

async function load() {
  _loading = true;
  _error = null;
  emit();
  const [s, d] = await Promise.allSettled([getStats(), getDashboardStats()]);
  if (s.status === 'fulfilled') _statsCache = s.value;
  else _error = String(s.reason);
  if (d.status === 'fulfilled') _dashboardCache = d.value;
  else if (!_error) _error = String(d.reason);
  _loading = false;
  emit();
}

/**
 * Single source of truth for headline stats numbers.
 * The cached responses + loading/error are shared across the app — no component
 * should fetch directly; all subscribe here and read the same shared state.
 */
export function useStats(): UseStatsResult {
  const [, setTick] = useState(0);

  useEffect(() => {
    const cb = () => setTick((t) => t + 1);
    _listeners.add(cb);
    if (!_loaded) {
      _loaded = true;
      void load();
    }
    return () => {
      _listeners.delete(cb);
    };
  }, []);

  return {
    stats: _statsCache,
    dashboard: _dashboardCache,
    loading: _loading && !_statsCache,
    error: _error,
  };
}
