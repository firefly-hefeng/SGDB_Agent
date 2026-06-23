/* Type contracts for /scdbAPI/collections/*. */

export interface CollectionProject {
  project_id: string;
  source_database: string;
  sample_count: number;
}

export interface FeaturedCollection {
  slug: string;
  title: string;
  blurb: string;
  sample_count: number;
  project_count: number;
  projects: CollectionProject[];
  /** Filter map suitable for serialising into the Explore page URL. */
  query: Record<string, string[]>;
}

export interface FeaturedCollectionsResponse {
  collections: FeaturedCollection[];
  elapsed_ms: number;
}

export interface TrendingProject {
  project_id: string;
  source_database: string;
  title: string | null;
  organism: string | null;
  sample_count: number | null;
  total_cells: number | null;
  publication_date: string | null;
  pmid: string | null;
}

export interface TrendingResponse {
  projects: TrendingProject[];
  elapsed_ms: number;
}
