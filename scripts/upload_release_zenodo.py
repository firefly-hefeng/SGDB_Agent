#!/usr/bin/env python3
"""Upload the catalog release bundle to Zenodo as a DRAFT deposition.

Creates a draft (does NOT auto-publish), uploads every file in the bundle, and
sets the metadata. You review + click Publish on the Zenodo web UI (and get the
DOI), then paste the DOI into web/src/config/dataRelease.ts.

Prereqs:
  - A Zenodo account + a personal access token with `deposit:write`/`deposit:actions`.
  - export ZENODO_TOKEN=...        (use https://sandbox.zenodo.org first to test:
    export ZENODO_SANDBOX=1)
  - pip install requests

Usage:
  python scripts/upload_release_zenodo.py --bundle /home/hf/sceqtl_catalog_release
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import requests

META = {
    "metadata": {
        "upload_type": "dataset",
        "title": "Singligent: curated human single-cell RNA-seq metadata catalog",
        "description": (
            "Harmonized, ontology-aligned, deduplicated METADATA for 943,732 human "
            "scRNA-seq samples aggregated from 8 archives (GEO, EGA, NCBI, EBI "
            "BioStudies, CellxGene, PsychAD, HTAN, HCA), exposed at four record "
            "levels (samples, projects, series, cell types). Produced by Singligent "
            "(Nanjing University; portal https://biobigdata.nju.edu.cn/singligent/ , "
            "lab https://compbio.nju.edu.cn/ ). This is the metadata compilation only "
            "&mdash; raw sequencing data remain at the source archives (EGA: "
            "metadata-only; data access requires DAC approval). Tables are provided "
            "as Parquet + gzipped CSV, plus the full SQLite snapshot, a data "
            "dictionary and SHA-256 checksums. See README.md."
        ),
        "access_right": "open",
        "license": "cc-by-4.0",
        "keywords": ["single-cell RNA-seq", "scRNA-seq", "metadata", "GEO", "EGA",
                     "CellxGene", "ontology", "harmonization", "data catalog",
                     "Singligent"],
        "creators": [{"name": "He, Feng", "affiliation": "Nanjing University"}],
        "version": "1.0",
    }
}


def base_url() -> str:
    return ("https://sandbox.zenodo.org" if os.environ.get("ZENODO_SANDBOX")
            else "https://zenodo.org")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", default="/home/hf/sceqtl_catalog_release")
    ap.add_argument("--publish", action="store_true",
                    help="publish immediately (mint DOI) — IRREVERSIBLE")
    args = ap.parse_args()
    token = os.environ.get("ZENODO_TOKEN")
    if not token:
        print("ERROR: set ZENODO_TOKEN (and optionally ZENODO_SANDBOX=1 to test).", file=sys.stderr)
        return 2
    bundle = Path(args.bundle)
    files = sorted(p for p in bundle.iterdir() if p.is_file())
    if not files:
        print(f"ERROR: no files in {bundle}", file=sys.stderr)
        return 2

    base, params = base_url(), {"access_token": token}
    print(f"Creating draft deposition on {base} …")
    r = requests.post(f"{base}/api/deposit/depositions", params=params, json={}, timeout=60)
    r.raise_for_status()
    dep = r.json()
    dep_id, bucket = dep["id"], dep["links"]["bucket"]
    print(f"  deposition id={dep_id}")

    for p in files:
        print(f"  uploading {p.name} ({p.stat().st_size/1e6:.1f} MB) …", flush=True)
        with open(p, "rb") as fh:
            ru = requests.put(f"{bucket}/{p.name}", data=fh, params=params, timeout=None)
        ru.raise_for_status()

    print("  setting metadata …")
    rm = requests.put(f"{base}/api/deposit/depositions/{dep_id}",
                      params=params, data=json.dumps(META),
                      headers={"Content-Type": "application/json"}, timeout=60)
    rm.raise_for_status()
    prereserved = (rm.json().get("metadata", {}).get("prereserve_doi", {}) or {}).get("doi")
    if prereserved:
        print(f"  reserved DOI: {prereserved}")

    if args.publish:
        print("  PUBLISHING (irreversible) …")
        rp = requests.post(f"{base}/api/deposit/depositions/{dep_id}/actions/publish",
                           params=params, timeout=120)
        rp.raise_for_status()
        pub = rp.json()
        doi = pub.get("doi") or (pub.get("metadata", {}) or {}).get("doi")
        rec = (pub.get("links", {}) or {}).get("record_html") or f"{base}/records/{pub.get('record_id', dep_id)}"
        print(f"\nPUBLISHED ✅  DOI: {doi}\n  Record: {rec}")
        print("Paste this DOI into web/src/config/dataRelease.ts.")
    else:
        edit_url = f"{base}/deposit/{dep_id}"
        print(f"\nDRAFT ready (NOT published). Review, then Publish:\n  {edit_url}")
        print("Re-run with --publish to mint the DOI.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
