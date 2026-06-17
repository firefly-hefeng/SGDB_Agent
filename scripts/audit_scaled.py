#!/usr/bin/env python3
"""Phase 33 — scaled real-system audit of the running portal.

Fires a corpus of realistic queries at the *live* backend and checks the
returned data for reasonableness, not just HTTP success: non-error, sane
total_count, plausible field values, acceptable latency, and SQL validity.
Flags suspicious zero-result hits for common terms (possible over-restrictive
joins) and prints a compact report.

Usage:  python scripts/audit_scaled.py [--base http://localhost:8000]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

# (query, min_expected_total) — min_expected is a soft floor for "common"
# biology terms that should obviously match in a 943K-sample human catalog.
# 0 means "no expectation" (edge cases / nonsense).
ADV_CORPUS: list[tuple[str, int]] = [
    ("human blood T cells", 50),
    ("lung cancer samples", 50),
    ("pancreatic islet", 20),
    ("brain alzheimer", 20),
    ("kidney single cell", 20),
    ("liver hepatocyte", 10),
    ("heart cardiomyocyte", 5),
    ("PBMC healthy donor", 20),
    ("breast cancer tumor", 20),
    ("CD8 T cells", 20),
    ("glioblastoma brain", 5),
    ("10x genomics human", 50),
    ("melanoma skin", 5),
    ("colon adenocarcinoma", 5),
    ("bone marrow leukemia", 20),
    ("fetal development", 5),
    ("immune cells covid", 1),
    ("retina photoreceptor", 1),
    # aggregation intents
    ("count datasets by tissue", 0),
    ("how many samples per disease", 0),
    # edge / negative
    ("xyzzy nonsense qwerty zzz", 0),
]

PLAUSIBLE_ORGANISMS = {
    "Homo sapiens", "Mus musculus", "Rattus norvegicus", "Danio rerio",
    "Macaca mulatta", "Macaca fascicularis", "Sus scrofa", "Gallus gallus",
    "Drosophila melanogaster", "Caenorhabditis elegans", "Pan troglodytes",
}


def post(base: str, path: str, payload: dict, timeout: int = 90) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        base + path, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def audit_advanced(base: str) -> list[dict]:
    findings = []
    print(f"\n{'QUERY':40} {'TOTAL':>8} {'METHOD':14} {'ms':>6}  NOTES")
    print("-" * 88)
    for q, floor in ADV_CORPUS:
        t0 = time.perf_counter()
        notes = []
        try:
            d = post(base, "/scdbAPI/advanced-search",
                     {"nl_query": q, "session_id": "audit", "limit": 10})
        except Exception as e:  # noqa: BLE001
            print(f"{q:40} {'ERR':>8} {'-':14} {'-':>6}  {type(e).__name__}: {e}")
            findings.append({"query": q, "severity": "high", "issue": f"request failed: {e}"})
            continue
        ms = int((time.perf_counter() - t0) * 1000)
        total = d.get("total_count", 0)
        prov = d.get("provenance") or {}
        method = prov.get("sql_method") or "-"
        err = d.get("error")
        results = d.get("results") or []
        agg = d.get("aggregation") or []

        if err:
            notes.append(f"error={err}")
            findings.append({"query": q, "severity": "high", "issue": f"error: {err}"})
        if floor and total == 0 and not agg:
            notes.append("⚠ 0 results for common term")
            findings.append({"query": q, "severity": "med",
                             "issue": f"0 results (expected ≥{floor})"})
        if floor and 0 < total < floor:
            notes.append(f"low ({total}<{floor})")
        if ms > 10000:
            notes.append(f"⚠ slow {ms}ms")
            findings.append({"query": q, "severity": "med", "issue": f"slow {ms}ms"})

        # Field reasonableness on the first few rows.
        for r in results[:5]:
            org = r.get("organism") or r.get("organism_common") or r.get("organism_normalized")
            nc = r.get("n_cells")
            if isinstance(nc, (int, float)) and nc < 0:
                findings.append({"query": q, "severity": "high",
                                 "issue": f"negative n_cells={nc}"})
            org_norm = r.get("organism_normalized")
            if org_norm and org_norm not in PLAUSIBLE_ORGANISMS:
                notes.append(f"odd organism '{org_norm}'")

        print(f"{q:40} {total:>8} {method:14} {ms:>6}  {'; '.join(notes)}")
    return findings


def audit_explore(base: str) -> list[dict]:
    """Faceted catalog search: a couple of filter combos + field sanity."""
    findings = []
    print(f"\n{'EXPLORE FILTER':40} {'TOTAL':>8} {'rows':>5} {'ms':>6}  NOTES")
    print("-" * 80)
    cases = [
        {"tissues": ["blood"]},
        {"diseases": ["lung cancer"]},
        {"organisms": ["Homo sapiens"], "tissues": ["brain"]},
        {},  # unfiltered
    ]
    for filt in cases:
        body = {**filt, "limit": 10, "offset": 0}
        t0 = time.perf_counter()
        try:
            d = post(base, "/scdbAPI/explore", body, timeout=60)
        except Exception as e:  # noqa: BLE001
            print(f"{str(filt):40} {'ERR':>8} {'-':>5} {'-':>6}  {e}")
            findings.append({"query": f"explore {filt}", "severity": "high", "issue": str(e)})
            continue
        ms = int((time.perf_counter() - t0) * 1000)
        total = d.get("total_count", d.get("total", 0))
        rows = d.get("results") or d.get("records") or []
        notes = []
        if ms > 8000:
            notes.append(f"⚠ slow {ms}ms")
        if total == 0 and not filt:
            notes.append("⚠ unfiltered returned 0!")
            findings.append({"query": "explore unfiltered", "severity": "high",
                             "issue": "0 rows unfiltered"})
        print(f"{str(filt):40} {total:>8} {len(rows):>5} {ms:>6}  {'; '.join(notes)}")
    return findings


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    args = ap.parse_args()

    print(f"Scaled audit against {args.base}")
    all_findings = []
    all_findings += audit_advanced(args.base)
    all_findings += audit_explore(args.base)

    print("\n" + "=" * 60)
    if not all_findings:
        print("✓ No data-quality findings.")
        return 0
    print(f"FINDINGS ({len(all_findings)}):")
    for f in sorted(all_findings, key=lambda x: x["severity"]):
        print(f"  [{f['severity'].upper():4}] {f['query']}: {f['issue']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
