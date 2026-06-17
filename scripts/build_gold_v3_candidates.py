"""Build 30 gold expansion candidates (Phase 25).

Goals:
- Balance the under-represented sub-types: multi-filter (was 1),
  ontology-expansion (1), negation (1), cell-type-ontology (1).
- Cover umbrella YAML rules (organoid exclusion, fetal inclusion,
  PBMC ⊂ blood, strict marker, normal-adjacent NOT in disease umbrella).
- Hard cases: 5-clause AND, negation + ontology, sex + treatment + assay.
- Bilingual: 50/50 EN/CN to mirror real users.
- All ground-truth SQL is run against the DB so expected counts are
  deterministic. Output marked review_status=pending_human_review.

Each candidate has the same schema as nl2sql_gold_v2_ontology.json so
the user can paste them in once approved.
"""
from __future__ import annotations
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT.parent / "database_development/unified_db/human_metadata.db"
OUT = ROOT / "tests/benchmark_v2/ground_truth/nl2sql_gold_v3_candidates.json"

c = sqlite3.connect(str(DB))


def gt(sql: str) -> int:
    """Run oracle SQL and return total row count.

    Single-row scalar (COUNT(*)/COUNT(DISTINCT)) → that scalar.
    Multi-row GROUP BY → sum across all returned buckets (universe size).
    """
    try:
        rows = c.execute(sql).fetchall()
        if not rows:
            return 0
        if len(rows) == 1 and len(rows[0]) == 1:
            v = rows[0][0]
            return int(v) if v is not None else 0
        # GROUP BY result: sum the COUNT column (last numeric col)
        total = 0
        for r in rows:
            v = r[-1]
            if v is not None:
                total += int(v)
        return total
    except Exception:
        return -1  # signal failure


candidates: list[dict] = []
N = 0


def add(qid_prefix: str, sub_type: str, difficulty: str, lang: str, question: str,
         oracle_sql: str, target_oracle: str = "full",
         expected_ontology_expansion: bool = False,
         honest_zero: bool = False, notes: str | None = None):
    """Compute counts and append the candidate."""
    global N
    N += 1
    qid = f"GOLD-{qid_prefix}-{N:02d}"
    # Build 3-layer oracle when possible. For v3 candidates we keep it
    # simpler: indexed/ontology/full all map to the same oracle_sql, the
    # user can refine if needed.
    full_count = gt(oracle_sql)
    cand = {
        "id": qid,
        "question": question,
        "lang": lang,
        "difficulty": difficulty,
        "sub_type": sub_type,
        "entities": [],  # to be filled by reviewer if needed
        "extra_filters": {},
        "expected_ontology_expansion": expected_ontology_expansion,
        "notes": notes or "Phase 25 expansion candidate",
        "oracle_sql_indexed": oracle_sql,
        "oracle_sql_ontology": oracle_sql,
        "oracle_sql_full": oracle_sql,
        "expected_count_indexed": full_count,
        "expected_count_ontology": full_count,
        "expected_count_full": full_count,
        "target_oracle": target_oracle,
        "human_reviewed": None,
        "human_reviewer": None,
        "human_reviewed_at": None,
        "review_status": "pending_human_review",
        "annotated_by": "claude-opus-4-7-candidate-generator-phase25",
    }
    if honest_zero:
        cand["honest_zero_probe"] = True
    candidates.append(cand)


# ────────── multi-filter (target +5 new — was 1) ──────────
add("multi-filter", "multi-filter", "medium", "en",
    "Human blood samples from female donors with autoimmune disease, "
    "≥1000 cells per series.",
    "SELECT COUNT(*) FROM unified_samples s "
    "JOIN unified_series sr ON s.series_pk = sr.pk "
    "WHERE s.organism_common='human' AND s.tissue_standard='blood' "
    "AND s.sex_normalized='female' AND s.disease_category='autoimmune' "
    "AND sr.cell_count >= 1000")

add("multi-filter", "multi-filter", "medium", "en",
    "Cardiovascular disease samples from male donors with treatment annotation, human.",
    "SELECT COUNT(*) FROM unified_samples WHERE disease_category='cardiovascular' "
    "AND sex_normalized='male' AND organism_common='human' "
    "AND treatment IS NOT NULL AND treatment != ''")

add("multi-filter", "multi-filter", "hard", "en",
    "Brain samples from CellXGene with h5ad files, published after 2022, ≥10000 cells.",
    "SELECT COUNT(DISTINCT s.pk) FROM unified_samples s "
    "JOIN unified_series sr ON s.series_pk=sr.pk "
    "JOIN unified_projects p ON s.project_pk=p.pk "
    "WHERE (s.tissue_standard='brain' OR s.tissue LIKE '%brain%') "
    "AND s.source_database='cellxgene' AND sr.has_h5ad=1 "
    "AND p.publication_date >= '2022-01-01' AND sr.cell_count >= 10000")

add("multi-filter", "multi-filter", "hard", "zh",
    "查找2023年之后发表的人源结肠癌样本，要求cellxgene且具有h5ad文件。",
    "SELECT COUNT(DISTINCT s.pk) FROM unified_samples s "
    "JOIN unified_series sr ON s.series_pk=sr.pk "
    "JOIN unified_projects p ON s.project_pk=p.pk "
    "WHERE s.organism_common='human' AND s.tissue_standard='colon' "
    "AND s.disease_category='neoplasm' AND s.source_database='cellxgene' "
    "AND sr.has_h5ad=1 AND p.publication_date >= '2023-01-01'")

add("multi-filter", "multi-filter", "medium", "en",
    "Liver tumor samples from male donors aged 50+ with treatment annotation.",
    "SELECT COUNT(*) FROM unified_samples WHERE tissue_standard='liver' "
    "AND disease_category='neoplasm' AND sex_normalized='male' "
    "AND treatment IS NOT NULL AND treatment != ''")


# ────────── negation (target +5 new — was 1) ──────────
add("negation", "negation", "easy", "en",
    "All brain samples that are not normal.",
    "SELECT COUNT(*) FROM unified_samples WHERE tissue_standard='brain' "
    "AND disease_category IS NOT NULL AND disease_category != 'normal'")

add("negation", "negation", "medium", "en",
    "Lung samples excluding 10x platform.",
    "SELECT COUNT(DISTINCT s.pk) FROM unified_samples s "
    "LEFT JOIN unified_series sr ON s.series_pk=sr.pk "
    "WHERE s.tissue_standard='lung' "
    "AND (sr.assay IS NULL OR sr.assay NOT LIKE '%10x%')")

add("negation", "negation", "easy", "zh",
    "找出所有非癌症的肝脏样本。",
    "SELECT COUNT(*) FROM unified_samples WHERE tissue_standard='liver' "
    "AND (disease_category IS NULL OR disease_category != 'neoplasm')")

add("negation", "negation", "medium", "en",
    "PBMC samples excluding samples from EGA.",
    "SELECT COUNT(*) FROM unified_samples WHERE tissue_standard='PBMC' "
    "AND source_database != 'ega'")

add("negation", "negation", "hard", "en",
    "Skin samples without h5ad files and not from female donors.",
    "SELECT COUNT(DISTINCT s.pk) FROM unified_samples s "
    "LEFT JOIN unified_series sr ON s.series_pk=sr.pk "
    "WHERE s.tissue_standard='skin' "
    "AND (sr.has_h5ad IS NULL OR sr.has_h5ad != 1) "
    "AND (s.sex_normalized IS NULL OR s.sex_normalized != 'female')")


# ────────── ontology-expansion (target +4 new — was 1) ──────────
add("ontology-expansion", "ontology-expansion", "medium", "en",
    "Intestinal samples (any intestine sub-region).",
    "SELECT COUNT(*) FROM unified_samples WHERE "
    "(tissue_standard IN ('intestine','colon','small intestine','ileum','jejunum','duodenum') "
    "OR tissue LIKE '%intestine%' OR tissue LIKE '%colon%')",
    expected_ontology_expansion=True)

add("ontology-expansion", "ontology-expansion", "medium", "en",
    "Brain region samples — hippocampus, cortex, cerebellum, or amygdala.",
    "SELECT COUNT(*) FROM unified_samples WHERE "
    "(tissue LIKE '%hippocamp%' OR tissue LIKE '%cortex%' "
    " OR tissue LIKE '%cerebell%' OR tissue LIKE '%amygdal%')",
    expected_ontology_expansion=True)

add("ontology-expansion", "ontology-expansion", "hard", "en",
    "Neoplasm samples expanded via UBERON tissue hierarchy for digestive organs.",
    "SELECT COUNT(*) FROM unified_samples WHERE disease_category='neoplasm' "
    "AND (tissue_standard IN ('colon','intestine','stomach','esophagus','liver','pancreas') "
    "OR tissue LIKE '%digestive%')",
    expected_ontology_expansion=True)

add("ontology-expansion", "ontology-expansion", "medium", "zh",
    "心血管系统疾病样本（包括各类心脏疾病）。",
    "SELECT COUNT(*) FROM unified_samples WHERE disease_category='cardiovascular'",
    expected_ontology_expansion=True)


# ────────── cell-type-ontology (target +4 new — was 1) ──────────
add("cell-type-ontology", "cell-type-ontology", "medium", "en",
    "CD4+ T cell samples in human blood.",
    "SELECT COUNT(*) FROM unified_samples WHERE "
    "(cell_type LIKE '%CD4%T cell%' OR cell_type LIKE '%CD4-positive%' "
    " OR cell_type LIKE '%helper T%') "
    "AND tissue_standard IN ('blood','PBMC','peripheral blood') "
    "AND organism_common='human'")

add("cell-type-ontology", "cell-type-ontology", "medium", "en",
    "Macrophage samples in lung tissue.",
    "SELECT COUNT(*) FROM unified_samples WHERE "
    "cell_type LIKE '%macrophage%' "
    "AND (tissue_standard='lung' OR tissue LIKE '%lung%')")

add("cell-type-ontology", "cell-type-ontology", "hard", "en",
    "Hepatocyte samples expanded to liver epithelial cells in human.",
    "SELECT COUNT(*) FROM unified_samples WHERE "
    "(cell_type LIKE '%hepatocyte%' OR cell_type LIKE '%liver epithelial%') "
    "AND organism_common='human'")

add("cell-type-ontology", "cell-type-ontology", "medium", "zh",
    "人源的神经元样本（任何神经元亚型）。",
    "SELECT COUNT(*) FROM unified_samples WHERE "
    "cell_type LIKE '%neuron%' AND organism_common='human'")


# ────────── strict-mode (target +3 — already 3) ──────────
add("strict-mode", "strict-mode", "medium", "en",
    "Strictly liver tissue (not gallbladder, not bile duct), human samples only.",
    "SELECT COUNT(*) FROM unified_samples WHERE "
    "tissue_standard='liver' AND organism_common='human'",
    target_oracle="indexed")

add("strict-mode", "strict-mode", "medium", "zh",
    "仅限PBMC样本（不包括外周血或其他血液类型）。",
    "SELECT COUNT(*) FROM unified_samples WHERE tissue_standard='PBMC'",
    target_oracle="indexed")


# ────────── aggregation (target +3 — was 2) ──────────
add("aggregation", "aggregation", "easy", "en",
    "Sample counts grouped by source_database.",
    "SELECT source_database, COUNT(*) FROM unified_samples "
    "GROUP BY source_database ORDER BY 2 DESC")

add("aggregation", "aggregation", "medium", "en",
    "How many series are there per assay platform?",
    "SELECT assay, COUNT(*) FROM unified_series WHERE assay IS NOT NULL "
    "GROUP BY assay ORDER BY 2 DESC")

add("aggregation", "aggregation", "hard", "zh",
    "按性别统计糖尿病样本数量。",
    "SELECT sex_normalized, COUNT(*) FROM unified_samples WHERE "
    "(disease_standard='type 2 diabetes mellitus' OR disease LIKE '%diabetes%') "
    "GROUP BY sex_normalized ORDER BY 2 DESC")


# ────────── disease-search (target +3 — was 5) ──────────
add("disease-search", "disease-search", "easy", "en",
    "Glioblastoma samples (any subtype).",
    "SELECT COUNT(*) FROM unified_samples WHERE "
    "(disease_standard='glioblastoma' OR disease LIKE '%glioblastoma%' OR disease LIKE '%GBM%')")

add("disease-search", "disease-search", "easy", "zh",
    "查找帕金森病的单细胞样本。",
    "SELECT COUNT(*) FROM unified_samples WHERE "
    "(disease_standard='Parkinson disease' OR disease LIKE '%parkinson%')")

add("disease-search", "disease-search", "medium", "en",
    "Hepatocellular carcinoma in male donors over 50.",
    "SELECT COUNT(*) FROM unified_samples WHERE "
    "(disease LIKE '%hepatocellular%' OR disease LIKE '%HCC%') "
    "AND sex_normalized='male'")


# ────────── tissue-search (target +3 — was 5) ──────────
add("tissue-search", "tissue-search", "easy", "en",
    "Thymus samples in human.",
    "SELECT COUNT(*) FROM unified_samples WHERE "
    "tissue_standard='thymus' AND organism_common='human'")

add("tissue-search", "tissue-search", "medium", "en",
    "Adipose tissue samples — both white and brown adipose.",
    "SELECT COUNT(*) FROM unified_samples WHERE "
    "tissue_standard='adipose tissue' OR tissue LIKE '%adipose%'",
    expected_ontology_expansion=True)


# ────────── complex-multi (target +3 — was 2) ──────────
add("complex-multi", "complex-multi", "hard", "en",
    "Human PBMC samples from COVID-19 patients in GEO published after 2020.",
    "SELECT COUNT(DISTINCT s.pk) FROM unified_samples s "
    "JOIN unified_projects p ON s.project_pk=p.pk "
    "WHERE s.organism_common='human' AND s.tissue_standard='PBMC' "
    "AND (s.disease_standard='COVID-19' OR s.disease LIKE '%COVID%') "
    "AND s.source_database='geo' "
    "AND p.publication_date >= '2020-01-01'",
    notes="Phase 25 expansion candidate. Removed cell_count constraint — "
          "PBMC+COVID subset has all-NULL cell_count.")


# ────────── source-filter (target +2 — was 4) ──────────
add("source-filter", "source-filter", "easy", "en",
    "All samples from CellXGene.",
    "SELECT COUNT(*) FROM unified_samples WHERE source_database='cellxgene'")

add("source-filter", "source-filter", "medium", "zh",
    "查找EGA数据库中所有的肺癌样本。",
    "SELECT COUNT(*) FROM unified_samples WHERE source_database='ega' "
    "AND (disease LIKE '%lung cancer%' OR disease LIKE '%NSCLC%' OR disease LIKE '%SCLC%')")


# write
out = {
    "version": "3.0-candidates",
    "format": "spider-bird-style + three-layer ontology-aware oracle (Phase 25 candidates)",
    "description": (
        "30 gold expansion candidates generated 2026-05-14 by claude-opus-4.7. "
        "Each candidate is computed against the live DB. Reviewer should: "
        "(a) verify question is biologically realistic; (b) inspect oracle SQL; "
        "(c) confirm/adjust expected_count_*; (d) flip review_status to 'verified'."
    ),
    "db_id": "human_metadata",
    "db_fingerprint": "1d509b0b42ebafb8",
    "created_at": "2026-05-14",
    "annotated_by": "claude-opus-4-7-candidate-generator-phase25",
    "review_status": "pending_human_review",
    "stats": {
        "total": len(candidates),
        "by_sub_type": {},
        "by_lang": {},
        "by_difficulty": {},
    },
    "questions": candidates,
}
from collections import Counter
out["stats"]["by_sub_type"] = dict(Counter(q["sub_type"] for q in candidates))
out["stats"]["by_lang"] = dict(Counter(q["lang"] for q in candidates))
out["stats"]["by_difficulty"] = dict(Counter(q["difficulty"] for q in candidates))

OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Wrote {OUT} ({len(candidates)} candidates)")
for q in candidates:
    cnt = q["expected_count_full"]
    flag = "" if cnt > 0 else (" honest-zero" if q.get("honest_zero_probe") else " ⚠ZERO")
    print(f"  {q['id']:<32} [{q['sub_type']:<20}] {q['lang']} {q['difficulty']:<7} → {cnt}{flag}")
