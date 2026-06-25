/**
 * Tiny workspace cache so the SaveButton popovers don't refetch the
 * list on every open. The cache is module-scoped (single-page app)
 * and invalidates on workspaceCreate.
 */

import { useEffect, useState } from 'react';
import { workspaceList, workspaceCreate } from '../services/api';
import type { WorkspaceMeta } from '../types/api';

let _cache: WorkspaceMeta[] | null = null;
let _inflight: Promise<WorkspaceMeta[]> | null = null;
const _listeners = new Set<(ws: WorkspaceMeta[]) => void>();

async function fetchActive(): Promise<WorkspaceMeta[]> {
  if (_cache) return _cache;
  if (_inflight) return _inflight;
  _inflight = workspaceList(false)
    .then((r) => {
      _cache = r.workspaces;
      _listeners.forEach((cb) => cb(_cache!));
      return _cache;
    })
    .finally(() => { _inflight = null; });
  return _inflight;
}

export function invalidateWorkspaceCache() {
  _cache = null;
}

export function useWorkspaces() {
  const [workspaces, setWorkspaces] = useState<WorkspaceMeta[] | null>(_cache);
  const [loading, setLoading] = useState(_cache === null);

  // Data-loading effect. The setState calls before the fetch are
  // intentional — they show the cached snapshot (if any) or the
  // skeleton state before the network round-trip.
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (_cache) {
      setWorkspaces(_cache);
      setLoading(false);
      return;
    }
    setLoading(true);
    fetchActive()
      .then(setWorkspaces)
      .catch(() => setWorkspaces([]))
      .finally(() => setLoading(false));
    const cb = (ws: WorkspaceMeta[]) => setWorkspaces(ws);
    _listeners.add(cb);
    return () => { _listeners.delete(cb); };
  }, []);
  /* eslint-enable react-hooks/set-state-in-effect */

  const refresh = async () => {
    invalidateWorkspaceCache();
    const fresh = await fetchActive();
    setWorkspaces(fresh);
  };

  const createOne = async (name: string) => {
    const ws = await workspaceCreate(name);
    invalidateWorkspaceCache();
    await fetchActive();
    return ws;
  };

  return { workspaces, loading, refresh, createOne };
}
