"""Build the RS v3 hard probe set (Phase 23).

Run once to materialise tests/benchmark_v2/real_scenarios/scenarios_v3_hard.json
with up-to-date oracle counts computed against the current DB.
"""
from __future__ import annotations
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT.parent / "database_development/unified_db/human_metadata.db"
OUT = ROOT / "tests/benchmark_v2/real_scenarios/scenarios_v3_hard.json"

c = sqlite3.connect(str(DB))


def gt(sql: str) -> int:
    try:
        r = c.execute(sql).fetchone()[0]
        return int(r) if r is not None else 0
    except Exception as e:
        print("ERR for", sql[:80], "->", e)
        return 0


scenarios: list[dict] = []


def add(rid, phrasing, intent, sql, filters, prio="P1",
        agg=False, hz=False, notes=None):
    expected = gt(sql)
    sc = {
        "id": rid, "researcher_phrasing": phrasing, "intent_summary": intent,
        "ground_truth_sql": sql, "must_include_filters": filters,
        "priority": prio, "expected_count": expected,
    }
    if agg:
        sc["aggregation"] = True
    if hz:
        sc["honest_zero_probe"] = True
    if notes:
        sc["notes"] = notes
    scenarios.append(sc)


# --- Paraphrase robustness ---
add("HRS-01",
    "How many human cancer datasets do we have, regardless of tissue?",
    "disease_category=neoplasm + organism=human",
    "SELECT COUNT(*) FROM unified_samples WHERE disease_category='neoplasm' "
    "AND organism_common='human'",
    ["disease=cancer", "organism=human"], "P0")

add("HRS-02",
    "samples from people with COVID",
    "disease LIKE covid or sars-cov-2",
    "SELECT COUNT(*) FROM unified_samples WHERE "
    "disease LIKE '%COVID%' OR disease LIKE '%SARS-CoV-2%' OR disease LIKE '%coronavirus%'",
    ["disease=covid"], "P0")

# Bilingual / mixed
add("HRS-03",
    "Show 阿尔茨海默 datasets in human brain",
    "tissue=brain + disease LIKE alzheimer (CN)",
    "SELECT COUNT(*) FROM unified_samples WHERE "
    "(tissue_standard='brain' OR tissue LIKE '%brain%') "
    "AND (disease LIKE '%alzheimer%' OR disease_category='neurological')",
    ["tissue=brain", "disease=alzheimer"], "P0")

add("HRS-04",
    "中文：肺癌 single-cell 数据，要求来自10x平台",
    "lung cancer + assay 10x (CN/EN mixed)",
    "SELECT COUNT(DISTINCT s.pk) FROM unified_samples s "
    "JOIN unified_series sr ON s.series_pk=sr.pk "
    "WHERE (s.tissue_standard='lung' OR s.tissue LIKE '%lung%') "
    "AND (s.disease_category='neoplasm' OR s.disease LIKE '%lung cancer%' "
    "     OR s.disease LIKE '%NSCLC%') "
    "AND (sr.assay LIKE '%10x%' OR sr.platform LIKE '%10x%')",
    ["tissue=lung", "disease=lung cancer", "assay=10x"], "P1")

# Negation / exclusion
add("HRS-05",
    "Find all liver samples that are NOT cancer.",
    "tissue=liver + NOT disease_category=neoplasm",
    "SELECT COUNT(*) FROM unified_samples WHERE tissue_standard='liver' "
    "AND (disease_category IS NULL OR disease_category != 'neoplasm')",
    ["tissue=liver", "exclude_disease=cancer"], "P0")

add("HRS-06",
    "Lung samples from human, excluding 10x assays.",
    "tissue=lung + organism=human + NOT assay=10x",
    "SELECT COUNT(DISTINCT s.pk) FROM unified_samples s "
    "LEFT JOIN unified_series sr ON s.series_pk=sr.pk "
    "WHERE s.tissue_standard='lung' AND s.organism_common='human' "
    "AND (sr.assay IS NULL OR (sr.assay NOT LIKE '%10x%' "
    "    AND (sr.platform IS NULL OR sr.platform NOT LIKE '%10x%')))",
    ["tissue=lung", "exclude_assay=10x"], "P1")

# Honest-zero / out-of-domain
add("HRS-07",
    "Show me mouse pancreas samples.",
    "honest zero — DB is human-only",
    "SELECT COUNT(*) FROM unified_samples WHERE organism_common='mouse'",
    ["organism=mouse", "honest_zero"], "P0", hz=True)

add("HRS-08",
    "Find arabidopsis single-cell RNA-seq.",
    "honest zero — non-human plant",
    "SELECT COUNT(*) FROM unified_samples WHERE organism LIKE '%arabidopsis%'",
    ["organism=arabidopsis", "honest_zero"], "P0", hz=True)

# Mixed-clause
add("HRS-09",
    "Find recent kidney datasets — anything published after 2023 with at least 1000 cells.",
    "tissue=kidney + pub_after_2023 + cell_count >= 1000",
    "SELECT COUNT(DISTINCT s.pk) FROM unified_samples s "
    "JOIN unified_projects p ON s.project_pk=p.pk "
    "JOIN unified_series sr ON s.series_pk=sr.pk "
    "WHERE s.tissue_standard='kidney' AND p.publication_date >= '2023-01-01' "
    "AND sr.cell_count >= 1000",
    ["tissue=kidney", "pub_after=2023", "min_cells=1000"], "P1")

add("HRS-10",
    "Find skin samples with melanoma that have h5ad files.",
    "tissue=skin + disease=melanoma + has_h5ad",
    "SELECT COUNT(DISTINCT s.pk) FROM unified_samples s "
    "JOIN unified_series sr ON s.series_pk=sr.pk "
    "WHERE s.tissue_standard='skin' "
    "AND (s.disease_category='neoplasm' OR s.disease LIKE '%melanoma%') "
    "AND sr.has_h5ad=1",
    ["tissue=skin", "disease=melanoma", "has_h5ad=1"], "P1")

# Cell-type compound
add("HRS-11",
    "How many cardiomyocyte samples from heart in human?",
    "cell_type LIKE cardiomyocyte + tissue=heart + organism=human",
    "SELECT COUNT(*) FROM unified_samples "
    "WHERE cell_type LIKE '%cardiomyocyte%' "
    "AND (tissue_standard='heart' OR tissue LIKE '%heart%') "
    "AND organism_common='human'",
    ["cell_type=cardiomyocyte", "tissue=heart", "organism=human"], "P1")

add("HRS-12",
    "B cells from autoimmune disease, human only.",
    "cell_type LIKE B cell + disease_cat=autoimmune + human",
    "SELECT COUNT(*) FROM unified_samples WHERE "
    "(cell_type LIKE '%B cell%' OR cell_type LIKE '%B-cell%' "
    " OR cell_type LIKE '%B lymphocyte%') "
    "AND disease_category='autoimmune' AND organism_common='human'",
    ["cell_type=B cell", "disease=autoimmune", "organism=human"], "P1")

# Aggregation
add("HRS-13",
    "Group cancer datasets by tissue to see where we have most coverage.",
    "GROUP BY tissue_standard WHERE disease_cat=neoplasm",
    "SELECT tissue_standard, COUNT(*) FROM unified_samples "
    "WHERE disease_category='neoplasm' AND tissue_standard IS NOT NULL "
    "GROUP BY tissue_standard ORDER BY 2 DESC LIMIT 30",
    ["disease=cancer", "aggregation by tissue"], "P1", agg=True)

add("HRS-14",
    "Per-source breakdown of brain neurological samples.",
    "GROUP BY source WHERE tissue=brain AND disease_cat=neurological",
    "SELECT source_database, COUNT(*) FROM unified_samples "
    "WHERE tissue_standard='brain' AND disease_category='neurological' "
    "GROUP BY source_database ORDER BY 2 DESC",
    ["tissue=brain", "disease=neurological", "aggregation by source"], "P1", agg=True)

# ID lookup
add("HRS-15",
    "Show me dataset GSE150728 in detail.",
    "lookup by series_id=GSE150728",
    "SELECT COUNT(*) FROM unified_samples WHERE series_id='GSE150728'",
    ["series_id=GSE150728"], "P0",
    notes="ID-based lookup — should be exact match, no LIKE")

# Large cohort
add("HRS-16",
    "Largest cohorts in our DB — series with >= 100000 cells.",
    "series.cell_count >= 100000",
    "SELECT COUNT(DISTINCT pk) FROM unified_series WHERE cell_count >= 100000",
    ["min_series_cells=100000"], "P1")

# Counterfactual / fuzzy temporal
add("HRS-17",
    "Old datasets — anything before 2018.",
    "pub_before_2018",
    "SELECT COUNT(DISTINCT s.pk) FROM unified_samples s "
    "JOIN unified_projects p ON s.project_pk=p.pk "
    "WHERE p.publication_date < '2018-01-01'",
    ["pub_before=2018"], "P1")

# Hard composition
add("HRS-18",
    "Find Alzheimer datasets profiling specific neurons with 10x.",
    "disease LIKE alzheimer + cell_type LIKE neuron + assay LIKE 10x",
    "SELECT COUNT(DISTINCT s.pk) FROM unified_samples s "
    "JOIN unified_series sr ON s.series_pk=sr.pk "
    "WHERE (s.disease LIKE '%alzheimer%' OR s.disease_category='neurological') "
    "AND s.cell_type LIKE '%neuron%' "
    "AND (sr.assay LIKE '%10x%' OR sr.platform LIKE '%10x%')",
    ["disease=alzheimer", "cell_type=neuron", "assay=10x"], "P1")

# Ambiguous: "cells" as threshold not cell_type
add("HRS-19",
    "Datasets with at least 50000 cells from cellxgene.",
    "series.cell_count >= 50000 + source=cellxgene",
    "SELECT COUNT(DISTINCT s.pk) FROM unified_samples s "
    "JOIN unified_series sr ON s.series_pk=sr.pk "
    "WHERE s.source_database='cellxgene' AND sr.cell_count >= 50000",
    ["source=cellxgene", "min_cells=50000"], "P1",
    notes="'cells' here is a threshold not a cell_type")

# Cross-source aggregation
add("HRS-20",
    "Compare cancer sample availability across geo, ebi, and cellxgene.",
    "GROUP BY source for disease_cat=neoplasm",
    "SELECT source_database, COUNT(*) FROM unified_samples "
    "WHERE disease_category='neoplasm' "
    "AND source_database IN ('geo','ebi','cellxgene') "
    "GROUP BY source_database ORDER BY 2 DESC",
    ["disease=cancer", "aggregation by source"], "P1", agg=True)


out = {
    "version": "3.0-hard",
    "description": (
        "RS v3 hard probes — paraphrase / negation / honest-zero / multi-clause / "
        "aggregation / ID-lookup / temporal stress cases designed to discriminate "
        "beyond the saturated RS v2."
    ),
    "db_id": "human_metadata",
    "db_fingerprint": "1d509b0b42ebafb8",
    "created_at": "2026-05-13",
    "tolerance_pct": 20.0,
    "scenarios": scenarios,
}
OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Wrote {OUT} with {len(scenarios)} probes")
for s in scenarios:
    tag = "(hz)" if s.get("honest_zero_probe") else (
        "(agg)" if s.get("aggregation") else ""
    )
    print(f"  {s['id']:<8} {s['priority']} {tag:<6} expected={s['expected_count']:>8}  "
          f"{s['researcher_phrasing'][:60]}")
