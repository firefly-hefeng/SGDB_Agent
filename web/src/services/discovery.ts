/* Client for /scdbAPI/discover/*. SSE stream uses a callback API rather
 * than EventSource so we can POST and abort cleanly. */

import type {
  DiscoveryRequest,
  DiscoveryResponse,
  DiscoveryResult,
  DiscoverySourcesResponse,
  DiscoveryHealthResponse,
  QueryIntent,
} from '../types/discovery';

const BASE_URL: string =
  (import.meta.env.VITE_API_BASE as string | undefined) ?? '/singligent/scdbAPI';

export async function listDiscoverySources(): Promise<DiscoverySourcesResponse> {
  const res = await fetch(`${BASE_URL}/discover/sources`);
  if (!res.ok) throw new Error(`Failed to list sources: ${res.status}`);
  return res.json();
}

export async function discoveryHealth(): Promise<DiscoveryHealthResponse> {
  const res = await fetch(`${BASE_URL}/discover/health`);
  if (!res.ok) throw new Error(`Health check failed: ${res.status}`);
  return res.json();
}

export async function discoverSearch(req: DiscoveryRequest): Promise<DiscoveryResponse> {
  const res = await fetch(`${BASE_URL}/discover/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
  if (!res.ok) throw new Error(`Discover failed: ${res.status} ${await res.text().catch(() => '')}`);
  return res.json();
}

export interface DiscoverStreamCallbacks {
  onIntent?: (intent: QueryIntent) => void;
  onSourceComplete?: (result: DiscoveryResult) => void;
  onMirrors?: (mirrors: { by_source: Record<string, Record<string, { source_db: string; id: string; source_url: string }[]>> }) => void;
  onSynth?: (markdown: string) => void;
  onDone?: (data: { total_found: number; total_latency_ms: number; sources_count: number }) => void;
  onError?: (err: { type?: string; message: string }) => void;
}

/**
 * Stream discovery events via SSE. Returns an `abort()` function that
 * cancels the request mid-stream.
 */
export function discoverStream(
  req: DiscoveryRequest,
  cbs: DiscoverStreamCallbacks,
): { abort: () => void; done: Promise<void> } {
  const ctrl = new AbortController();
  const done = (async () => {
    let res: Response;
    try {
      res = await fetch(`${BASE_URL}/discover/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'text/event-stream',
        },
        body: JSON.stringify(req),
        signal: ctrl.signal,
      });
    } catch (e) {
      if (ctrl.signal.aborted) return;
      cbs.onError?.({ type: 'NetworkError', message: String(e) });
      return;
    }
    if (!res.ok || !res.body) {
      cbs.onError?.({ type: 'HttpError', message: `HTTP ${res.status}` });
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';

    const dispatch = (event: string, data: unknown) => {
      switch (event) {
        case 'intent':
          cbs.onIntent?.(data as QueryIntent);
          break;
        case 'source_complete':
          cbs.onSourceComplete?.(data as DiscoveryResult);
          break;
        case 'mirrors':
          cbs.onMirrors?.(
            data as { by_source: Record<string, Record<string, { source_db: string; id: string; source_url: string }[]>> },
          );
          break;
        case 'synth':
          cbs.onSynth?.((data as { markdown: string }).markdown);
          break;
        case 'done':
          cbs.onDone?.(
            data as { total_found: number; total_latency_ms: number; sources_count: number },
          );
          break;
        case 'error':
          cbs.onError?.(data as { type?: string; message: string });
          break;
      }
    };

    const parseFrame = (frame: string) => {
      let event = 'message';
      const dataLines: string[] = [];
      for (const line of frame.split('\n')) {
        if (!line || line.startsWith(':') || line.startsWith('retry:')) continue;
        if (line.startsWith('event:')) event = line.slice(6).trim();
        else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
      }
      if (!dataLines.length) return;
      try {
        const data = JSON.parse(dataLines.join('\n'));
        dispatch(event, data);
      } catch {
        // ignore malformed frames
      }
    };

    try {
      for (;;) {
        const { value, done: streamDone } = await reader.read();
        if (streamDone) break;
        buf += decoder.decode(value, { stream: true });
        let sep;
        while ((sep = buf.indexOf('\n\n')) >= 0) {
          parseFrame(buf.slice(0, sep));
          buf = buf.slice(sep + 2);
        }
      }
      if (buf.trim()) parseFrame(buf);
    } catch (e) {
      if (!ctrl.signal.aborted) {
        cbs.onError?.({ type: 'StreamError', message: String(e) });
      }
    }
  })();

  return {
    abort: () => ctrl.abort(),
    done,
  };
}
