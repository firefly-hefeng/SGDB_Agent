/**
 * Public data-availability release metadata.
 *
 * After depositing the catalog bundle (scripts/export_catalog_release.py →
 * scripts/upload_release_zenodo.py + upload_release_hf.py), paste the resulting
 * DOI + Hugging Face URL here. While they're empty the UI shows a clear
 * "deposition pending" state instead of dead links.
 */
export interface DataReleaseTable {
  name: string;
  rows: number;
  desc: string;
}

export const DATA_RELEASE = {
  /** Published Zenodo record (CC-BY-4.0, He Feng, Nanjing University). */
  zenodoDoi: '10.5281/zenodo.20850066',
  zenodoUrl: 'https://doi.org/10.5281/zenodo.20850066',
  /** Hugging Face dataset (live). */
  hfUrl: 'https://huggingface.co/datasets/nju-hefeng/singligent-catalog',
  /** Content fingerprint the release + all evaluations pin to. */
  snapshot: 'f88b2025eda755b1',
  license: 'CC-BY-4.0',
  /** Curated tiers in the bundle (Parquet + gzipped CSV; full SQLite DB also included). */
  tables: [
    { name: 'unified_samples', rows: 943732, desc: 'Sample tier — cell-level metadata' },
    { name: 'unified_projects', rows: 16376, desc: 'Project tier — study-level groupings' },
    { name: 'unified_series', rows: 14110, desc: 'Series tier — assay-level + file pointers' },
    { name: 'unified_celltypes', rows: 378029, desc: 'Cell-type annotations (Cell Ontology)' },
  ] as DataReleaseTable[],
} as const;

/** True once at least one public mirror (Zenodo DOI or HF) is set. */
export const dataReleasePublished = (): boolean =>
  Boolean(DATA_RELEASE.zenodoUrl || DATA_RELEASE.hfUrl);
