import { useCallback, useEffect, useReducer, useRef } from 'react';
import { discoverStream, type DiscoverStreamCallbacks } from '../services/discovery';
import type {
  DiscoveryResult,
  DiscoveryRequest,
  QueryIntent,
} from '../types/discovery';

interface State {
  intent: QueryIntent | null;
  sources: DiscoveryResult[];
  synth: string | null;
  totalFound: number;
  totalLatencyMs: number;
  status: 'idle' | 'streaming' | 'done' | 'error';
  error: string | null;
  startedAt: number | null;
}

const INITIAL: State = {
  intent: null,
  sources: [],
  synth: null,
  totalFound: 0,
  totalLatencyMs: 0,
  status: 'idle',
  error: null,
  startedAt: null,
};

type Action =
  | { type: 'start' }
  | { type: 'intent'; intent: QueryIntent }
  | { type: 'source_complete'; result: DiscoveryResult }
  | { type: 'mirrors'; by_source: Record<string, Record<string, { source_db: string; id: string; source_url: string }[]>> }
  | { type: 'synth'; markdown: string }
  | { type: 'done'; total_found: number; total_latency_ms: number }
  | { type: 'error'; message: string }
  | { type: 'reset' };

function reducer(s: State, a: Action): State {
  switch (a.type) {
    case 'reset':
      return INITIAL;
    case 'start':
      return { ...INITIAL, status: 'streaming', startedAt: performance.now() };
    case 'intent':
      return { ...s, intent: a.intent };
    case 'source_complete':
      return {
        ...s,
        sources: [...s.sources, a.result],
        totalFound: s.totalFound + (a.result.total_found || 0),
      };
    case 'mirrors': {
      const next = s.sources.map((src) => {
        const mp = a.by_source[src.source];
        if (!mp) return src;
        return {
          ...src,
          results: src.results.map((r) =>
            mp[r.id] ? { ...r, mirrors: mp[r.id] } : r,
          ),
        };
      });
      return { ...s, sources: next };
    }
    case 'synth':
      return { ...s, synth: a.markdown };
    case 'done':
      return {
        ...s,
        status: 'done',
        totalLatencyMs: a.total_latency_ms || (s.startedAt ? performance.now() - s.startedAt : 0),
      };
    case 'error':
      return { ...s, status: 'error', error: a.message };
  }
}

export function useDiscoverStream(): State & {
  start: (req: DiscoveryRequest) => void;
  abort: () => void;
  reset: () => void;
} {
  const [state, dispatch] = useReducer(reducer, INITIAL);
  const abortRef = useRef<(() => void) | null>(null);

  const start = useCallback((req: DiscoveryRequest) => {
    abortRef.current?.();
    dispatch({ type: 'start' });
    const callbacks: DiscoverStreamCallbacks = {
      onIntent: (intent) => dispatch({ type: 'intent', intent }),
      onSourceComplete: (result) => dispatch({ type: 'source_complete', result }),
      onMirrors: (m) => dispatch({ type: 'mirrors', by_source: m.by_source }),
      onSynth: (markdown) => dispatch({ type: 'synth', markdown }),
      onDone: (d) =>
        dispatch({
          type: 'done',
          total_found: d.total_found,
          total_latency_ms: d.total_latency_ms,
        }),
      onError: (e) => dispatch({ type: 'error', message: e.message ?? 'Unknown error' }),
    };
    const handle = discoverStream(req, callbacks);
    abortRef.current = handle.abort;
  }, []);

  const abort = useCallback(() => {
    abortRef.current?.();
    abortRef.current = null;
  }, []);

  const reset = useCallback(() => {
    abortRef.current?.();
    abortRef.current = null;
    dispatch({ type: 'reset' });
  }, []);

  // Abort in-flight stream on unmount.
  useEffect(() => () => abortRef.current?.(), []);

  return { ...state, start, abort, reset };
}
