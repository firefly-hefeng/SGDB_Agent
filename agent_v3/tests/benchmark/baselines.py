"""
Baseline comparison systems for evaluation.

Implements simplified baselines to compare against the full agent:
1. DirectSQL — Expert-crafted SQL (upper bound)
2. SingleDB — CellXGene-only or GEO-only search (single-source baseline)
3. KeywordOnly — Simple LIKE-based keyword search (no ontology, no fusion)
"""

from __future__ import annotations

import time
import sqlite3
from pathlib import Path


class DirectSQLBaseline:
    """
    Expert SQL baseline — represents the accuracy upper bound.
    Uses hand-crafted SQL for each benchmark question.
    """

    # Map of question_id → expert SQL
    EXPERT_SQL: dict[str, str] = {
        "SS01": "SELECT * FROM v_sample_with_hierarchy WHERE tissue LIKE '%liver%' LIMIT 20",
        "SS02": "SELECT * FROM v_sample_with_hierarchy WHERE tissue LIKE '%brain%' LIMIT 20",
        "SS03": "SELECT * FROM v_sample_with_hierarchy WHERE tissue LIKE '%blood%' LIMIT 20",
        "SS09": "SELECT * FROM v_sample_with_hierarchy WHERE disease LIKE '%cancer%' LIMIT 20",
        "SS10": "SELECT * FROM v_sample_with_hierarchy WHERE disease LIKE '%COVID%' LIMIT 20",
        "ST01": "SELECT sample_source, COUNT(*) as count FROM v_sample_with_hierarchy GROUP BY sample_source ORDER BY count DESC",
        "ST03": "SELECT tissue, COUNT(*) as count FROM unified_samples WHERE tissue IS NOT NULL GROUP BY tissue ORDER BY count DESC LIMIT 20",
        "CF01": "SELECT * FROM unified_projects WHERE project_id = 'GSE149614'",
    }

    def __init__(self, db_path: str):
        self.db_path = db_path

    def query(self, question_id: str) -> dict:
        sql = self.EXPERT_SQL.get(question_id)
        if not sql:
            return {"total_count": 0, "error": "no_expert_sql", "execution_time_ms": 0}

        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            t0 = time.perf_counter()
            rows = conn.execute(sql).fetchall()
            elapsed = (time.perf_counter() - t0) * 1000
            return {
                "total_count": len(rows),
                "execution_time_ms": elapsed,
                "sql": sql,
                "method": "expert_sql",
            }
        except Exception as e:
            return {"total_count": 0, "error": str(e), "execution_time_ms": 0}
        finally:
            conn.close()


class SingleDBBaseline:
    """
    Single database baseline — searches only one source (e.g., GEO or CellXGene).
    Demonstrates the value of cross-database fusion.
    """

    def __init__(self, db_path: str, source: str = "geo"):
        self.db_path = db_path
        self.source = source

    def query(self, keyword: str) -> dict:
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            t0 = time.perf_counter()
            sql = (
                "SELECT * FROM unified_samples "
                "WHERE source_database = ? AND "
                "(tissue LIKE ? OR disease LIKE ?) "
                "LIMIT 20"
            )
            rows = conn.execute(sql, [self.source, f"%{keyword}%", f"%{keyword}%"]).fetchall()
            elapsed = (time.perf_counter() - t0) * 1000

            # Count total
            count_sql = (
                "SELECT COUNT(*) as cnt FROM unified_samples "
                "WHERE source_database = ? AND "
                "(tissue LIKE ? OR disease LIKE ?)"
            )
            total = conn.execute(count_sql, [self.source, f"%{keyword}%", f"%{keyword}%"]).fetchone()["cnt"]

            return {
                "total_count": total,
                "displayed_count": len(rows),
                "execution_time_ms": elapsed,
                "method": f"single_db_{self.source}",
                "data_sources": [self.source],
            }
        except Exception as e:
            return {"total_count": 0, "error": str(e), "execution_time_ms": 0}
        finally:
            conn.close()


class KeywordOnlyBaseline:
    """
    Simple keyword search baseline — no ontology expansion, no fusion.
    Uses LIKE queries across all databases.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path

    def query(self, keyword: str) -> dict:
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            t0 = time.perf_counter()
            sql = (
                "SELECT *, source_database FROM unified_samples "
                "WHERE tissue LIKE ? OR disease LIKE ? OR sample_id LIKE ? "
                "LIMIT 20"
            )
            pattern = f"%{keyword}%"
            rows = conn.execute(sql, [pattern, pattern, pattern]).fetchall()
            elapsed = (time.perf_counter() - t0) * 1000

            count_sql = (
                "SELECT COUNT(*) as cnt FROM unified_samples "
                "WHERE tissue LIKE ? OR disease LIKE ? OR sample_id LIKE ?"
            )
            total = conn.execute(count_sql, [pattern, pattern, pattern]).fetchone()["cnt"]

            sources = list(set(r["source_database"] for r in rows))

            return {
                "total_count": total,
                "displayed_count": len(rows),
                "execution_time_ms": elapsed,
                "method": "keyword_only",
                "data_sources": sources,
            }
        except Exception as e:
            return {"total_count": 0, "error": str(e), "execution_time_ms": 0}
        finally:
            conn.close()


def run_baseline_comparison(
    db_path: str,
    questions: list[dict],
) -> dict:
    """
    Run all baselines on a set of questions and return comparison data.
    """
    geo_baseline = SingleDBBaseline(db_path, "geo")
    cxg_baseline = SingleDBBaseline(db_path, "cellxgene")
    keyword_baseline = KeywordOnlyBaseline(db_path)

    results = {
        "geo_only": {"passed": 0, "total": 0, "avg_time_ms": 0, "times": []},
        "cellxgene_only": {"passed": 0, "total": 0, "avg_time_ms": 0, "times": []},
        "keyword_only": {"passed": 0, "total": 0, "avg_time_ms": 0, "times": []},
    }

    for q in questions:
        query = q.get("query", "")
        if not query or len(query) < 2:
            continue

        expected_min = q.get("expected_count_min", 0)

        # Extract keyword (simple: use first significant word)
        keyword = _extract_keyword(query)
        if not keyword:
            continue

        for name, baseline in [
            ("geo_only", geo_baseline),
            ("cellxgene_only", cxg_baseline),
            ("keyword_only", keyword_baseline),
        ]:
            resp = baseline.query(keyword)
            results[name]["total"] += 1
            results[name]["times"].append(resp.get("execution_time_ms", 0))
            if resp.get("total_count", 0) >= expected_min:
                results[name]["passed"] += 1

    # Compute averages
    for name, data in results.items():
        if data["times"]:
            data["avg_time_ms"] = sum(data["times"]) / len(data["times"])
        data["pass_rate"] = (data["passed"] / data["total"] * 100) if data["total"] > 0 else 0
        del data["times"]  # Clean up

    return results


def _extract_keyword(query: str) -> str:
    """Extract the main keyword from a query for baseline search."""
    # Remove common stopwords and Chinese patterns
    stopwords = {
        "find", "search", "查找", "统计", "the", "all", "from", "datasets",
        "data", "samples", "single", "cell", "human", "的", "数据", "数据集",
        "中", "有", "哪些", "是", "相关", "across", "databases", "with",
        "count", "statistics", "how", "many", "what", "show", "get",
    }
    words = query.lower().replace("'", "").split()
    keywords = [w for w in words if w not in stopwords and len(w) > 2]
    return keywords[0] if keywords else ""
