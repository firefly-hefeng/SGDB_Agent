import type {
  FeaturedCollectionsResponse,
  TrendingResponse,
} from '../types/collections';

const BASE_URL: string =
  (import.meta.env.VITE_API_BASE as string | undefined) ?? '/singligent/scdbAPI';

export async function fetchFeaturedCollections(): Promise<FeaturedCollectionsResponse> {
  const res = await fetch(`${BASE_URL}/collections/featured`);
  if (!res.ok) throw new Error(`Failed to load featured collections: ${res.status}`);
  return res.json();
}

export async function fetchTrending(limit = 10): Promise<TrendingResponse> {
  const res = await fetch(`${BASE_URL}/collections/trending?limit=${limit}`);
  if (!res.ok) throw new Error(`Failed to load trending: ${res.status}`);
  return res.json();
}
