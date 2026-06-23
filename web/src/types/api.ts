/* API response types matching backend schemas */

export interface Suggestion {
  type: string;
  text: string;
  action_query: string;
  reason: string;
}

export interface ProvenanceInfo {
  original_query: string;
  parsed_intent: string;
  // Phase 38: structured filters the agent extracted (tissues, diseases,
  // cell_types, assays, …) — lets the UI show "what I understood".
  parsed_filters?: Record<string, unknown>;
  ontology_expansions: OntologyExpansion[];
  sql_executed: string;
  sql_method: string;
  strategy_level: string;
  fusion_stats: {
    raw_count?: number;
    fused_count?: number;
    dedup_rate?: number;
  };
  data_sources: string[];
  execution_time_ms: number;
  // Phase 27: full step-by-step execution trace surfaced from the agent.
  reasoning_trace?: ReasoningTrace | null;
}

/* Phase 27 — step-by-step agent execution trace (see src/core/reasoning.py). */
export interface ReasoningStep {
  stage: string;           // parse | ontology | sql_gen | execute | correct | fuse | synthesize | ...
  title: string;
  status: 'ok' | 'warn' | 'error' | 'corrected' | 'skipped';
  duration_ms: number;
  input?: Record<string, unknown>;
  output?: Record<string, unknown>;
  rationale?: string;
  confidence?: number;
  step_id: string;
  correction_of?: string | null;
}

export interface ReasoningTrace {
  trace_id: string;
  steps: ReasoningStep[];
  summary: {
    step_count: number;
    correction_count: number;
    fallback_count: number;
    error_count: number;
    total_duration_ms: number;
    stages_completed: string[];
    final_confidence: number;
  };
}

export interface OntologyExpansion {
  original: string;
  ontology_id: string;
  label: string;
  db_values_count: number;
  total_samples: number;
}

export interface StatsResponse {
  total_projects: number;
  total_series: number;
  total_samples: number;
  total_celltypes: number;
  source_databases: { name: string; project_count: number; sample_count: number }[];
  databases?: { name: string; project_count: number; sample_count: number }[];
  top_tissues: { value: string; count: number }[];
  top_diseases: { value: string; count: number }[];
}

/* Explore API types */

export interface FacetBucket {
  value: string;
  count: number;
}

export interface ExploreRecord {
  sample_pk: number;
  sample_id: string;
  tissue: string | null;
  disease: string | null;
  cell_type: string | null;
  organism: string | null;
  sex: string | null;
  n_cells: number | null;
  assay: string | null;
  source_database: string;
  series_id: string | null;
  series_title: string | null;
  has_h5ad: boolean;
  project_id: string | null;
  project_title: string | null;
  pmid: string | null;
  // Standardized fields
  tissue_standard: string | null;
  tissue_system: string | null;
  disease_standard: string | null;
  disease_category: string | null;
  organism_common: string | null;
  sex_normalized: string | null;
  sample_type: string | null;
  n_cell_types: number | null;
}

export interface ExploreResponse {
  results: ExploreRecord[];
  total_count: number;
  offset: number;
  limit: number;
  facets: Record<string, FacetBucket[]>;
}

/* Dataset detail types */

export interface DownloadOption {
  file_type: string;
  label: string;
  url: string | null;
  instructions: string;
  source: string;
  /* Phase 36 — deep (ENA/GEO) resolution adds exact sizes + checksums. */
  file_size_human?: string | null;
  checksum_note?: string | null;
  bytes?: number | null;
  aspera_url?: string | null;
  md5?: string | null;
  run?: string | null;
}

export interface DownloadEstimate {
  dataset_count: number;
  file_count: number;
  sized_file_count: number;
  total_bytes: number | null;
  total_size_human: string | null;
  size_is_partial: boolean;
  by_source: { source: string; files: number; bytes: number | null; size_human: string | null }[];
  unresolved: string[];
  unmatched_count: number;
  available_types: string[];
}

export interface DatasetDetailResponse {
  entity_id: string;
  entity_type: string;
  title: string | null;
  description: string | null;
  organism: string | null;
  source_database: string;
  project: Record<string, unknown> | null;
  series: Record<string, unknown>[];
  samples: Record<string, unknown>[];
  sample_count: number;
  cross_links: { linked_id: string; linked_database: string; linked_title: string | null; relationship_type: string }[];
  downloads: DownloadOption[];
  pmid: string | null;
  doi: string | null;
}

/* Dashboard stats */

export interface DashboardStats {
  total_projects: number;
  total_series: number;
  total_samples: number;
  total_celltypes: number;
  total_cross_links: number;
  total_sources: number;
  total_donors?: number;
  by_source: { name: string; projects: number; series: number; samples: number }[];
  by_tissue: { value: string; count: number }[];
  by_disease: { value: string; count: number }[];
  by_assay: { value: string; count: number }[];
  by_organism: { value: string; count: number }[];
  by_sex: { value: string; count: number }[];
  submissions_by_year: { year: string; count: number }[];
  h5ad_available: number;
  rds_available: number;
  with_pmid: number;
  with_doi: number;
  // New standardized breakdowns
  by_tissue_system: { value: string; count: number }[];
  by_disease_category: { value: string; count: number }[];
  by_sample_type: { value: string; count: number }[];
}

/* Advanced Search types */

export interface ParsedCondition {
  field: string;
  operator: string;
  values: string[];
  display_label: string;
  source: 'nl_parse' | 'user_edit' | 'facet_select';
  confidence: number;
}

export interface AdvancedSearchRequest {
  nl_query?: string;
  conditions: ParsedCondition[];
  session_id: string;
  limit: number;
  offset: number;
  sort_by: string;
  sort_dir: string;
}

export interface ChartSpec {
  type: string;             // bar | pie | …
  title: string;
  data: Record<string, number> | unknown[];
}

export interface AdvancedSearchResponse {
  conditions: ParsedCondition[];
  results: ExploreRecord[];
  total_count: number;
  offset: number;
  limit: number;
  facets: Record<string, FacetBucket[]>;
  summary: string;
  provenance: ProvenanceInfo;
  suggestions: Suggestion[];
  // Phase 33: aggregation output for "count by …" STATISTICS queries.
  charts?: ChartSpec[];
  aggregation?: Record<string, unknown>[];
  error: string | null;
}

/* Project / Series search (Phase 15B) */

export interface ProjectSearchRequest {
  text_search?: string;
  source_databases?: string[];
  organisms?: string[];
  has_pmid?: boolean | null;
  has_doi?: boolean | null;
  published_after?: string | null;
  published_before?: string | null;
  min_sample_count?: number | null;
  min_total_cells?: number | null;
  // Phase 40: new facet filters wired from the projects sidebar.
  data_availability?: string;   // "open" | "controlled"
  years?: string[];             // e.g. ["2024", "2025"]
  offset?: number;
  limit?: number;
  sort_by?: string;
  sort_dir?: string;
}

export interface ProjectRecord {
  project_pk: number;
  project_id: string;
  project_id_type: string | null;
  source_database: string;
  title: string | null;
  description: string | null;
  organism: string | null;
  pmid: string | null;
  doi: string | null;
  journal: string | null;
  publication_date: string | null;
  citation_count: number | null;
  sample_count: number | null;
  total_cells: number | null;
  access_url: string | null;
  data_availability: string | null;
}

export interface ProjectSearchResponse {
  results: ProjectRecord[];
  total_count: number;
  offset: number;
  limit: number;
  facets: Record<string, FacetBucket[]>;
  elapsed_ms: number;
}

export interface SeriesSearchRequest {
  text_search?: string;
  source_databases?: string[];
  organisms?: string[];
  assays?: string[];
  // Phase 40: new assay-modality facet filter wired from the series sidebar.
  assay_modalities?: string[];  // e.g. ["scRNA_seq", "multiome"]
  has_h5ad?: boolean | null;
  has_rds?: boolean | null;
  min_cell_count?: number | null;
  offset?: number;
  limit?: number;
  sort_by?: string;
  sort_dir?: string;
}

export interface SeriesRecord {
  series_pk: number;
  series_id: string;
  source_database: string;
  project_id: string | null;
  title: string | null;
  organism: string | null;
  assay: string | null;
  platform: string | null;
  cell_count: number | null;
  sample_count: number | null;
  has_h5ad: boolean;
  has_rds: boolean;
  asset_h5ad_url: string | null;
  asset_rds_url: string | null;
  citation_count: number | null;
  published_at: string | null;
}

export interface SeriesSearchResponse {
  results: SeriesRecord[];
  total_count: number;
  offset: number;
  limit: number;
  facets: Record<string, FacetBucket[]>;
  elapsed_ms: number;
}

export interface SourceTallyRow {
  source_database: string;
  project_count: number;
  series_count: number;
  sample_count: number;
  samples_reported_in_projects: number;
  cells_reported_in_projects: number;
}

export interface ProjectsStatsBySource {
  sources: SourceTallyRow[];
  total_sources: number;
}

/* Workspace (Phase 15D) */

export interface WorkspaceMeta {
  id: number;
  name: string;
  description: string | null;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
  item_count: number;
}

export interface WorkspaceItem {
  id: number;
  workspace_id: number;
  item_type: 'sample' | 'series' | 'project';
  item_pk: number | null;
  item_id: string;
  source_database: string | null;
  title: string | null;
  metadata: Record<string, unknown> | null;
  note: string | null;
  added_at: string;
}

export interface WorkspaceWithItems {
  workspace: WorkspaceMeta;
  items: WorkspaceItem[];
}

export interface AddItemsResult {
  added: number;
  skipped: number;
}

/* Cell-type browse tier (Phase 39) */

export interface CellTypeRow {
  cell_type: string;
  ontology_term_id: string | null;
  n_samples: number;
  n_projects: number;
  n_series: number;
  n_sources: number;
}

export interface CellTypeCoverage {
  basis: string;
  samples_annotated: number;
  samples_total: number;
  annotated_pct: number;
  distinct_types: number;
  composition_note: string;
}

export interface CellTypeSearchResponse {
  cell_types: CellTypeRow[];
  total: number;
  offset: number;
  limit: number;
  coverage: CellTypeCoverage;
}

export interface CellTypeProjectRow {
  project_id: string;
  title: string | null;
  source_database: string;
  n_samples: number;
}

export interface CellTypeProjectsResponse {
  cell_type: string;
  projects: CellTypeProjectRow[];
  /** Note: total_projects / total_samples reflect rows up to `limit` only. */
  total_projects: number;
  total_samples: number;
}

export type CellTypeSort = 'n_samples' | 'n_projects' | 'n_series' | 'cell_type';
