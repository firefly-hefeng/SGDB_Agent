#!/usr/bin/env python3
"""Build the public *data-availability* bundle for the curated metadata catalog.

Produces an upload-ready release directory containing, for each of the four
curated record tiers, a Parquet (compact, typed) + gzipped-CSV (universal)
export; the full SQLite snapshot; a data dictionary; a README; a LICENSE; and
SHA-256 checksums pinned to the snapshot fingerprint. Nothing here PUBLISHES —
it only stages files locally for you to deposit on Zenodo / Hugging Face.

Usage:
    python scripts/export_catalog_release.py \
        --db /home/hf/sceqtl_db/human_metadata.db \
        --out /home/hf/sceqtl_catalog_release \
        [--no-db-copy]

The bundle is the harmonized METADATA (sample/project/series/cell-type
descriptions) — NOT the raw sequencing data, which lives at the source archives
(the portal resolves exact per-dataset download links to those).
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

TABLES = ["unified_samples", "unified_projects", "unified_series", "unified_celltypes"]
TIER_DESC = {
    "unified_samples": "Sample tier — cell-level metadata (one row per sample).",
    "unified_projects": "Project tier — study-level groupings.",
    "unified_series": "Series tier — assay-level records with file pointers.",
    "unified_celltypes": "Cell-type annotations — per-sample standardized (Cell Ontology) labels with counts.",
}
LICENSE_CC_BY = "Creative Commons Attribution 4.0 International (CC-BY-4.0)"


def _content_fingerprint(db: str) -> str:
    """Canonical snapshot fingerprint — MUST match the one the evals pin to
    (tests/benchmark_v2.oracle.snapshot_hash → f88b2025eda755b1). Import the
    real function so the release bundle, the docs and the benchmarks all agree
    (E6 reproducibility). Fall back to a local recompute only if the import
    fails (and warn, since that would diverge)."""
    try:
        import sys as _sys
        _root = str(Path(__file__).resolve().parents[1])
        if _root not in _sys.path:
            _sys.path.insert(0, _root)
        from tests.benchmark_v2.oracle import snapshot_hash  # type: ignore
        return snapshot_hash(db)
    except Exception as e:  # noqa: BLE001
        print(f"  WARN: could not import canonical snapshot_hash ({e}); "
              "using local recompute — verify it matches the eval fingerprint.")
        h = hashlib.sha256()
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        h.update(str(Path(db).stat().st_size).encode())
        for (name,) in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ):
            try:
                n = con.execute(f"SELECT COUNT(*) FROM '{name}'").fetchone()[0]
            except sqlite3.Error:
                n = -1
            h.update(f"{name}:{n}".encode())
        con.close()
        return h.hexdigest()[:16]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def export_tables(db: str, out: Path) -> list[tuple[str, int, int]]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    stats = []
    for t in TABLES:
        print(f"  exporting {t} …", flush=True)
        df = pd.read_sql_query(f"SELECT * FROM {t}", con)
        df.to_parquet(out / f"{t}.parquet", compression="zstd", index=False)
        with gzip.open(out / f"{t}.csv.gz", "wt", newline="", encoding="utf-8") as gz:
            df.to_csv(gz, index=False)
        stats.append((t, len(df), len(df.columns)))
        print(f"    {t}: {len(df):,} rows × {len(df.columns)} cols", flush=True)
    con.close()
    return stats


def data_dictionary(db: str, out: Path, stats) -> None:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    lines = ["# Data dictionary\n",
             "Auto-generated column inventory per table (name · SQLite type · "
             "non-null % · distinct count). See the manuscript/methods for "
             "harmonization + ontology-alignment details.\n"]
    for t, nrows, _ in stats:
        lines.append(f"\n## `{t}` — {TIER_DESC.get(t, '')}  ({nrows:,} rows)\n")
        lines.append("| column | type | non-null % | distinct |")
        lines.append("|---|---|---:|---:|")
        cols = list(con.execute(f"PRAGMA table_info({t})"))
        for _, name, ctype, *_rest in cols:
            try:
                nn = con.execute(
                    f"SELECT COUNT(*) FROM {t} WHERE \"{name}\" IS NOT NULL AND \"{name}\"!=''"
                ).fetchone()[0]
                nd = con.execute(f"SELECT COUNT(DISTINCT \"{name}\") FROM {t}").fetchone()[0]
            except sqlite3.Error:
                nn = nd = -1
            pct = f"{100*nn/nrows:.1f}" if nrows else "—"
            lines.append(f"| {name} | {ctype or 'TEXT'} | {pct} | {nd:,} |")
    con.close()
    (out / "DATA_DICTIONARY.md").write_text("\n".join(lines), encoding="utf-8")


def write_readme(out: Path, fp: str, stats, ts: str, include_db: bool) -> None:
    rows = "\n".join(
        f"- `{t}.parquet` / `{t}.csv.gz` — {TIER_DESC[t]} ({n:,} rows × {c} cols)"
        for t, n, c in stats
    )
    db_line = ("- `human_metadata.db` — the complete relational SQLite snapshot "
               "(all tables + views).\n" if include_db else "")
    (out / "README.md").write_text(f"""# Singligent — curated human single-cell RNA-seq metadata catalog

Harmonized, ontology-aligned, **deduplicated metadata** for **{stats[0][1]:,} human
scRNA-seq samples** aggregated from **8 archives** (GEO, EGA, NCBI, EBI BioStudies,
CellxGene, PsychAD, HTAN, HCA), exposed at four record levels. Produced by
**Singligent** (Nanjing University). Snapshot content fingerprint: **`{fp}`** · built {ts}.

- Portal: https://biobigdata.nju.edu.cn/singligent/
- Lab: https://compbio.nju.edu.cn/

## ⚠️ What this is — and is not
This bundle is the **METADATA** that describes *what* each dataset is (tissue,
disease, cell type, donor, assay, provenance). It is **NOT** the raw sequencing
data: count matrices / FASTQ / BAM remain at the source archives. The Singligent
portal resolves exact, per-dataset download links (with sizes + checksums) to
those originals.

## Files
{rows}
{db_line}- `DATA_DICTIONARY.md` — per-table column inventory.
- `CHECKSUMS.sha256` — SHA-256 of every file.
- `LICENSE.txt` — {LICENSE_CC_BY}.

## Load
```python
import pandas as pd
samples = pd.read_parquet("unified_samples.parquet")
# or CSV: pd.read_csv("unified_samples.csv.gz")
# or the full DB:  sqlite3.connect("human_metadata.db")
```

## License & attribution
The **compilation** (harmonization, ontology alignment, dedup, schema) is released
under **{LICENSE_CC_BY}** — please cite (see below). Records are derived from the
source archives, which retain their own terms; cite the original studies when
using specific datasets.

**EGA**: only controlled-access *metadata* is included here; access to EGA
sequencing data requires Data Access Committee (DAC) approval at ega-archive.org.

## Citation
> He Feng. Singligent: a dual-agent portal for natural-language discovery of human
> single-cell RNA-seq metadata. Nanjing University, 2026. DOI: see the Zenodo record.

## Reproducibility
All portal evaluations pin to snapshot fingerprint `{fp}`. Verify with:
`python scripts/export_catalog_release.py` reports the same fingerprint, and
`CHECKSUMS.sha256` covers every file in this bundle.
""", encoding="utf-8")


def write_license(out: Path) -> None:
    (out / "LICENSE.txt").write_text(
        f"{LICENSE_CC_BY}\n\n"
        "You are free to share and adapt this metadata compilation for any purpose, "
        "provided you give appropriate credit (cite Singligent, He Feng, Nanjing "
        "University / the Zenodo DOI) and "
        "indicate changes. Full text: https://creativecommons.org/licenses/by/4.0/\n\n"
        "Source records are derived from public archives (GEO, EGA, NCBI, EBI, "
        "CellxGene, PsychAD, HTAN, HCA), which retain their own terms; cite the "
        "original studies for specific datasets. EGA: metadata-only; data access "
        "requires DAC approval.\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="/home/hf/sceqtl_db/human_metadata.db")
    ap.add_argument("--out", default="/home/hf/sceqtl_catalog_release")
    ap.add_argument("--no-db-copy", action="store_true",
                    help="skip copying the 1.6 GB SQLite file into the bundle")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fp = _content_fingerprint(args.db)
    print(f"Snapshot fingerprint: {fp}\nStaging → {out}")

    stats = export_tables(args.db, out)
    data_dictionary(args.db, out, stats)
    if not args.no_db_copy:
        print("  copying full SQLite DB (≈1.6 GB) …", flush=True)
        shutil.copy2(args.db, out / "human_metadata.db")
    write_readme(out, fp, stats, ts, include_db=not args.no_db_copy)
    write_license(out)

    # checksums last (covers everything else)
    cks = []
    for p in sorted(out.iterdir()):
        if p.name == "CHECKSUMS.sha256" or p.is_dir():
            continue
        cks.append(f"{_sha256(p)}  {p.name}  ({p.stat().st_size:,} bytes)")
    (out / "CHECKSUMS.sha256").write_text("\n".join(cks) + "\n", encoding="utf-8")

    total = sum(p.stat().st_size for p in out.iterdir() if p.is_file())
    print(f"\nDone. Bundle = {total/1e9:.2f} GB in {out}")
    for line in cks:
        print("  " + line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
