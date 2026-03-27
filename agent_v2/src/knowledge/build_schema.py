"""
Schema Knowledge Builder — CLI tool to generate schema_knowledge.yaml from the database.

Usage:
    python -m src.knowledge.build_schema --db-path data/unified_metadata.db --output data/schema_knowledge.yaml
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# Semantic fields to profile
SEMANTIC_FIELDS = {
    "tissue": {"table": "unified_samples", "ontology_source": "UBERON"},
    "disease": {"table": "unified_samples", "ontology_source": "MONDO"},
    "cell_type": {"table": "unified_samples", "ontology_source": "CL"},
    "assay": {"table": "unified_series", "ontology_source": "EFO"},
    "organism": {"table": "unified_samples", "ontology_source": None},
    "source_database": {"table": "unified_samples", "ontology_source": None},
    "sex": {"table": "unified_samples", "ontology_source": None},
}

# Built-in Chinese↔English synonyms for common terms
BUILTIN_SYNONYMS = {
    "tissue": {
        "brain": ["大脑", "脑", "cerebral", "cerebrum"],
        "blood": ["血液", "外周血", "PBMC", "whole blood", "peripheral blood"],
        "liver": ["肝", "肝脏", "hepatic"],
        "lung": ["肺", "肺部", "pulmonary"],
        "heart": ["心脏", "心", "cardiac", "myocardial"],
        "kidney": ["肾", "肾脏", "renal"],
        "skin": ["皮肤", "dermis", "epidermis"],
        "intestine": ["肠", "肠道", "gut", "colon", "bowel"],
        "pancreas": ["胰腺", "pancreatic"],
        "bone marrow": ["骨髓"],
        "breast": ["乳腺", "mammary"],
        "eye": ["眼", "视网膜", "retina", "retinal"],
        "stomach": ["胃", "gastric"],
        "spleen": ["脾脏", "脾"],
        "muscle": ["肌肉", "skeletal muscle"],
        "placenta": ["胎盘", "placental"],
        "adipose tissue": ["脂肪", "adipose", "fat tissue"],
        "lymph node": ["淋巴结", "lymph"],
        "thyroid": ["甲状腺"],
        "prostate": ["前列腺"],
        "ovary": ["卵巢", "ovarian"],
        "testis": ["睾丸", "testes"],
    },
    "disease": {
        "normal": ["正常", "健康", "对照", "healthy", "control"],
        "cancer": ["癌", "肿瘤", "恶性", "tumor", "carcinoma", "malignant", "neoplasm"],
        "Alzheimer's disease": ["阿尔茨海默", "老年痴呆", "alzheimer", "AD"],
        "COVID-19": ["新冠", "covid", "sars-cov-2", "coronavirus"],
        "diabetes": ["糖尿病", "diabetic"],
        "fibrosis": ["纤维化", "fibrotic"],
        "hepatocellular carcinoma": ["肝癌", "肝细胞癌", "HCC"],
        "lung cancer": ["肺癌", "NSCLC", "SCLC"],
        "breast cancer": ["乳腺癌"],
        "colorectal cancer": ["结直肠癌", "colon cancer"],
        "leukemia": ["白血病", "AML", "CLL", "ALL"],
        "melanoma": ["黑色素瘤"],
        "glioblastoma": ["胶质母细胞瘤", "GBM"],
        "Parkinson's disease": ["帕金森", "parkinson"],
    },
    "cell_type": {
        "T cell": ["T细胞", "t-cell", "CD4", "CD8"],
        "B cell": ["B细胞", "b-cell"],
        "macrophage": ["巨噬细胞"],
        "neutrophil": ["中性粒细胞"],
        "fibroblast": ["成纤维细胞"],
        "epithelial cell": ["上皮细胞", "epithelial"],
        "endothelial cell": ["内皮细胞", "endothelial"],
        "neuron": ["神经元", "neuronal"],
        "astrocyte": ["星形胶质细胞"],
        "hepatocyte": ["肝细胞"],
        "NK cell": ["NK细胞", "natural killer"],
        "dendritic cell": ["树突状细胞", "DC"],
        "monocyte": ["单核细胞"],
        "stem cell": ["干细胞"],
    },
    "assay": {
        "10x 3' v3": ["10x", "10x chromium", "chromium"],
        "Smart-seq2": ["smart-seq", "smartseq"],
        "Drop-seq": ["drop-seq", "dropseq"],
        "CITE-seq": ["cite-seq", "citeseq"],
        "Visium": ["visium", "spatial"],
    },
    "organism": {
        "Homo sapiens": ["人", "人类", "人源", "人的", "human", "patient"],
        "Mus musculus": ["小鼠", "鼠", "鼠源", "mouse", "murine"],
    },
}

ID_PATTERNS = [
    {"prefix": "GSE", "type": "geo_project", "table": "unified_projects", "field": "project_id"},
    {"prefix": "GSM", "type": "geo_sample", "table": "unified_samples", "field": "sample_id"},
    {"prefix": "PRJNA", "type": "sra_project", "table": "unified_projects", "field": "project_id"},
    {"prefix": "SRP", "type": "sra_study", "table": "unified_series", "field": "series_id"},
    {"prefix": "SRS", "type": "sra_sample", "table": "unified_samples", "field": "sample_id"},
    {"prefix": "SAMN", "type": "biosample", "table": "unified_samples", "field": "sample_id"},
    {"prefix": "SAME", "type": "biosample", "table": "unified_samples", "field": "sample_id"},
]

QUERY_CONSTRAINTS = [
    "Always add LIMIT (default 20, max 200)",
    "Use LIKE '%term%' for text fields (tissue, disease, cell_type)",
    "Use IN for enumerated fields (source_database, sex, organism)",
    "Parameterize all user values with ?",
    "FTS5 tables available: fts_samples, fts_projects, fts_series",
    "Use v_sample_with_hierarchy view for joined queries (samples+series+projects)",
    "cell_type is NOT available in v_sample_with_hierarchy — query unified_samples directly",
    "In v_sample_with_hierarchy: pk→sample_pk, source_database→sample_source, title→project_title",
    "Do NOT combine tissue + tissue_general in same WHERE clause",
]


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _field_profile(conn: sqlite3.Connection, table: str, field: str, top_n: int) -> dict:
    """Profile a single field: top values, null%, distinct count."""
    row = conn.execute(f"""
        SELECT COUNT(*) as total,
               COUNT([{field}]) as non_null,
               COUNT(DISTINCT [{field}]) as distinct_count
        FROM [{table}]
    """).fetchone()

    total = row["total"]
    non_null = row["non_null"]
    distinct = row["distinct_count"]
    null_pct = round((total - non_null) / total * 100, 1) if total > 0 else 0.0

    top_rows = conn.execute(f"""
        SELECT [{field}] as val, COUNT(*) as cnt
        FROM [{table}]
        WHERE [{field}] IS NOT NULL
        GROUP BY [{field}]
        ORDER BY cnt DESC
        LIMIT ?
    """, [top_n]).fetchall()

    top_values = [{"value": r["val"], "count": r["cnt"]} for r in top_rows]

    return {
        "distinct_count": distinct,
        "null_pct": null_pct,
        "top_values": top_values,
    }


def _load_ontology_synonyms(onto_db_path: str) -> dict[str, dict[str, list[str]]]:
    """Load synonym mappings from ontology_cache.db if available."""
    result: dict[str, dict[str, list[str]]] = {}
    if not Path(onto_db_path).exists():
        return result

    try:
        conn = sqlite3.connect(f"file:{onto_db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT field_name, db_value, ontology_label
            FROM ontology_mappings
            WHERE db_value IS NOT NULL AND ontology_label IS NOT NULL
        """).fetchall()
        conn.close()

        for r in rows:
            field = r["field_name"]
            db_val = r["db_value"]
            label = r["ontology_label"]
            if field not in result:
                result[field] = {}
            if db_val not in result[field]:
                result[field][db_val] = []
            if label != db_val and label not in result[field][db_val]:
                result[field][db_val].append(label)
    except Exception as e:
        logger.warning("Could not load ontology synonyms: %s", e)

    return result


def _get_table_info(conn: sqlite3.Connection) -> dict:
    """Get table/view metadata."""
    tables = {}
    rows = conn.execute(
        "SELECT name, type FROM sqlite_master WHERE type IN ('table', 'view') "
        "AND name NOT LIKE 'sqlite_%' ORDER BY type, name"
    ).fetchall()

    # Precomputed counts
    precomputed: dict[str, int] = {}
    try:
        stats = conn.execute("SELECT metric, value FROM stats_overall").fetchall()
        metric_map = {
            "total_projects": "unified_projects",
            "total_series": "unified_series",
            "total_samples": "unified_samples",
            "total_celltypes": "unified_celltypes",
            "total_entity_links": "entity_links",
        }
        for s in stats:
            tbl = metric_map.get(s["metric"])
            if tbl:
                precomputed[tbl] = s["value"]
    except Exception:
        pass

    for row in rows:
        name = row["name"]
        is_view = row["type"] == "view"
        cols = conn.execute(f"PRAGMA table_info('{name}')").fetchall()
        columns = [{"name": c["name"], "type": c["type"]} for c in cols]

        count = 0
        if not is_view and not name.startswith("fts_") and not name.startswith("stats_"):
            if name in precomputed:
                count = precomputed[name]
            else:
                try:
                    count = conn.execute(f"SELECT COUNT(*) as cnt FROM [{name}]").fetchone()["cnt"]
                except Exception:
                    pass

        tables[name] = {
            "is_view": is_view,
            "record_count": count,
            "columns": columns,
        }

    return tables


def _source_db_stats(conn: sqlite3.Connection) -> list[dict]:
    """Get per-source-database sample counts."""
    rows = conn.execute("""
        SELECT source_database as name, COUNT(*) as sample_count
        FROM unified_samples
        WHERE source_database IS NOT NULL
        GROUP BY source_database
        ORDER BY sample_count DESC
    """).fetchall()
    return [{"name": r["name"], "sample_count": r["sample_count"]} for r in rows]


def build_schema_knowledge(
    db_path: str,
    output_path: str,
    top_n: int = 100,
    ontology_db_path: str | None = None,
) -> dict:
    """Build the complete schema knowledge YAML."""
    t0 = time.perf_counter()
    conn = _connect(db_path)

    logger.info("Profiling semantic fields...")

    # Global stats
    tables_info = _get_table_info(conn)
    source_stats = _source_db_stats(conn)

    total_samples = tables_info.get("unified_samples", {}).get("record_count", 0)
    total_projects = tables_info.get("unified_projects", {}).get("record_count", 0)
    total_series = tables_info.get("unified_series", {}).get("record_count", 0)

    # Load ontology synonyms
    onto_synonyms: dict[str, dict[str, list[str]]] = {}
    if ontology_db_path:
        onto_synonyms = _load_ontology_synonyms(ontology_db_path)

    # Profile each semantic field
    fields = {}
    for field_name, meta in SEMANTIC_FIELDS.items():
        logger.info("  Profiling %s.%s ...", meta["table"], field_name)
        profile = _field_profile(conn, meta["table"], field_name, top_n)

        # Merge synonyms: builtin + ontology
        synonyms = dict(BUILTIN_SYNONYMS.get(field_name, {}))
        onto_field_syns = onto_synonyms.get(field_name, {})
        for db_val, onto_labels in onto_field_syns.items():
            if db_val in synonyms:
                for lbl in onto_labels:
                    if lbl not in synonyms[db_val]:
                        synonyms[db_val].append(lbl)
            else:
                synonyms[db_val] = onto_labels

        field_entry = {
            "semantic_type": field_name,
            "table": meta["table"],
            "distinct_count": profile["distinct_count"],
            "null_pct": profile["null_pct"],
            "top_values": profile["top_values"],
        }
        if meta["ontology_source"]:
            field_entry["ontology_source"] = meta["ontology_source"]
        if synonyms:
            field_entry["known_synonyms"] = synonyms

        fields[field_name] = field_entry

    # Table summaries (non-view, non-FTS, non-stats)
    table_summaries = {}
    for name, info in tables_info.items():
        if info["is_view"] or name.startswith("fts_") or name.startswith("stats_"):
            continue
        table_summaries[name] = {
            "record_count": info["record_count"],
            "key_columns": [c["name"] for c in info["columns"]],
        }

    # View info
    views = {}
    if "v_sample_with_hierarchy" in tables_info:
        v_cols = [c["name"] for c in tables_info["v_sample_with_hierarchy"]["columns"]]
        views["v_sample_with_hierarchy"] = {
            "description": "Pre-joined samples+series+projects",
            "columns": v_cols,
            "note": "cell_type NOT available in this view",
            "column_aliases": {
                "pk": "sample_pk",
                "source_database": "sample_source",
                "title": "project_title",
            },
        }

    conn.close()

    # Assemble YAML
    knowledge = {
        "version": "1.0",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "stats": {
            "total_samples": total_samples,
            "total_projects": total_projects,
            "total_series": total_series,
            "source_databases": source_stats,
        },
        "fields": fields,
        "tables": table_summaries,
        "views": views,
        "id_patterns": ID_PATTERNS,
        "query_constraints": QUERY_CONSTRAINTS,
        "overrides": {
            "synonyms": {},
            "notes": {},
        },
    }

    # Write YAML
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        yaml.dump(knowledge, f, allow_unicode=True, default_flow_style=False, sort_keys=False, width=120)

    elapsed = time.perf_counter() - t0
    logger.info("Schema knowledge written to %s (%.1fs)", output_path, elapsed)
    return knowledge


def main():
    parser = argparse.ArgumentParser(description="Build schema_knowledge.yaml from database")
    parser.add_argument("--db-path", required=True, help="Path to unified_metadata.db")
    parser.add_argument("--output", default="data/schema_knowledge.yaml", help="Output YAML path")
    parser.add_argument("--top-n", type=int, default=100, help="Top N values per field")
    parser.add_argument("--ontology-db", default=None, help="Path to ontology_cache.db")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    build_schema_knowledge(
        db_path=args.db_path,
        output_path=args.output,
        top_n=args.top_n,
        ontology_db_path=args.ontology_db,
    )


if __name__ == "__main__":
    main()
