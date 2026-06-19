#!/usr/bin/env python3
"""Upload the catalog release bundle to a Hugging Face *dataset* repo.

Creates (if needed) and pushes the bundle to hf.co/datasets/<repo>. HF is
git-LFS backed with a fast CDN — good for browsable + programmatic access
(`load_dataset` / direct parquet URLs).

Prereqs:
  - `huggingface-cli login`  (or set HF_TOKEN)
  - pip install huggingface_hub   (present)

Usage:
  python scripts/upload_release_hf.py --repo <user-or-org>/sceqtl-catalog \
      --bundle /home/hf/sceqtl_catalog_release
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from huggingface_hub import HfApi, create_repo


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="e.g. yourname/sceqtl-catalog")
    ap.add_argument("--bundle", default="/home/hf/sceqtl_catalog_release")
    ap.add_argument("--private", action="store_true")
    args = ap.parse_args()

    bundle = Path(args.bundle)
    if not bundle.is_dir() or not any(bundle.iterdir()):
        print(f"ERROR: empty/missing bundle dir {bundle}", file=sys.stderr)
        return 2

    print(f"Ensuring dataset repo {args.repo} …")
    create_repo(args.repo, repo_type="dataset", private=args.private, exist_ok=True)

    api = HfApi()
    print(f"Uploading {bundle} → datasets/{args.repo} (this may take a while for the 1.6 GB DB) …")
    api.upload_folder(
        repo_id=args.repo,
        repo_type="dataset",
        folder_path=str(bundle),
        commit_message="Add curated human scRNA-seq metadata catalog (tables + full DB)",
    )
    url = f"https://huggingface.co/datasets/{args.repo}"
    print(f"\nDone → {url}")
    print("Paste this URL into web/src/config/dataRelease.ts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
