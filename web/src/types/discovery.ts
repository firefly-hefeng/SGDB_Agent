/* Type contracts for /scdbAPI/discover/*. Mirrors src/discovery/models.py. */

export interface QueryIntent {
  disease?: string[];
  tissue?: string[];
  tech?: string[];
  species?: string[];
  keywords?: string[];
  time_hint?: string | null;
  restrict_sources?: string[] | null;
  negative_terms?: string[];
}

export interface MirrorRef {
  source_db: string;
  id: string;
  source_url: string;
}

export interface DatasetResult {
  id: string;
  title: string;
  description?: string | null;
  organism?: string | null;
  sample_count?: number | null;
  date?: string | null;
  source_db: string;
  source_url: string;
  download_url?: string | null;
  data_type?: string | null;
  mirrors?: MirrorRef[];
}

export interface DiscoveryResult {
  source: string;
  total_found: number;
  results: DatasetResult[];
  query_url?: string | null;
  error?: string | null;
  latency_ms: number;
}

export interface DiscoveryOptions {
  sources: string[];
  synthesize: boolean;
  max_results_per_source: number;
}

export interface DiscoveryRequest {
  query: string;
  options?: Partial<DiscoveryOptions>;
}

export interface DiscoveryResponse {
  query: string;
  intent: QueryIntent;
  sources: DiscoveryResult[];
  total_found: number;
  synthesized_answer?: string | null;
  total_latency_ms: number;
}

export interface DiscoverySource {
  id: string;
  name: string;
  full_name: string;
  description: string;
  host: string;
}

export interface DiscoverySourcesResponse {
  sources: DiscoverySource[];
  default_selection: string[];
}

export interface DiscoveryHealthResponse {
  status: 'ok' | 'degraded';
  adapters_available: number;
  adapters_total: number;
  adapters: Record<string, { available: boolean; latency_ms: number; error?: string }>;
}
