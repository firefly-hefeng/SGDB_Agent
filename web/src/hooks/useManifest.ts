import { useEffect, useSyncExternalStore } from 'react';
import {
  manifestGet,
  manifestSubscribe,
  type Manifest,
} from '../lib/manifest';

/**
 * React subscription to the localStorage-backed manifest store.
 * Returns the live manifest object and a memoised count.
 */
export function useManifest(): { manifest: Manifest; count: number } {
  // useSyncExternalStore gives us tearing-free reads on a localStorage store
  // that's also broadcast across tabs.
  const manifest = useSyncExternalStore(
    manifestSubscribe,
    manifestGet,
    manifestGet,
  );

  // Encourage the cache to be primed once on mount.
  useEffect(() => {
    // no-op; useSyncExternalStore already triggered a read
  }, []);

  return { manifest, count: manifest.entries.length };
}
