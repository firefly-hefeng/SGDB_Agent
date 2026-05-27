"""
Semantic Memory — System-level knowledge base (SQLite)

Persistent, globally-shared knowledge:
- Schema knowledge (field stats, top values)
- Successful query templates (auto-generalized)
- Value synonyms (auto-learned)

Lifecycle: permanent, grows over time, shared across all users.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS field_knowledge (
    table_name    TEXT NOT NULL,
    field_name    TEXT NOT NULL,
    semantic_type TEXT,           -- tissue / disease / id / metric / ...
    null_pct      REAL,
    unique_count  INTEGER,
    top_values_json TEXT,         -- JSON: [{"value": "brain", "count": 25432}, ...]
    last_analyzed REAL,
    PRIMARY KEY (table_name, field_name)
);

CREATE TABLE IF NOT EXISTS query_templates (
    template_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    intent        TEXT NOT NULL,
    pattern       TEXT NOT NULL,  -- generalized description
    sql_template  TEXT NOT NULL,
    success_count INTEGER DEFAULT 1,
    fail_count    INTEGER DEFAULT 0,
    avg_exec_ms   REAL,
    created_at    REAL,
    last_used     REAL
);

CREATE INDEX IF NOT EXISTS idx_qt_intent ON query_templates(intent, success_count DESC);

CREATE TABLE IF NOT EXISTS value_synonyms (
    field_name      TEXT NOT NULL,
    canonical_value TEXT NOT NULL,
    synonym         TEXT NOT NULL,
    confidence      REAL DEFAULT 1.0,
    source          TEXT,          -- 'ontology' / 'learned' / 'manual'
    PRIMARY KEY (field_name, synonym)
);

CREATE INDEX IF NOT EXISTS idx_vs_canonical ON value_synonyms(field_name, canonical_value);
"""


class SemanticMemory:
    """
    System-level knowledge base.

    Auto-learns from successful queries:
    - Generalizes SQL to reusable templates
    - Records value synonyms from ontology resolution
    - Caches field statistics for schema-aware generation
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None
        self._ensure_schema()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
        return self._conn

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def _ensure_schema(self):
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    # ─── field knowledge ───

    def store_field_knowledge(
        self,
        table_name: str,
        field_name: str,
        semantic_type: str,
        null_pct: float,
        unique_count: int,
        top_values: list[tuple[str, int]],
    ):
        """Store or update field-level knowledge."""
        top_json = json.dumps([{"value": v, "count": c} for v, c in top_values[:20]])
        self.conn.execute(
            "INSERT OR REPLACE INTO field_knowledge "
            "(table_name, field_name, semantic_type, null_pct, "
            "unique_count, top_values_json, last_analyzed) "
            "VALUES (?,?,?,?,?,?,?)",
            [table_name, field_name, semantic_type, null_pct,
             unique_count, top_json, time.time()],
        )
        self.conn.commit()

    def get_field_knowledge(self, table_name: str, field_name: str) -> dict | None:
        """Retrieve field knowledge."""
        row = self.conn.execute(
            "SELECT * FROM field_knowledge WHERE table_name = ? AND field_name = ?",
            [table_name, field_name],
        ).fetchone()
        if row:
            d = dict(row)
            d["top_values"] = json.loads(d["top_values_json"]) if d["top_values_json"] else []
            return d
        return None

    def get_top_values(self, table_name: str, field_name: str, limit: int = 10) -> list[str]:
        """Get top values for a field (for LLM prompt injection)."""
        fk = self.get_field_knowledge(table_name, field_name)
        if fk and fk.get("top_values"):
            return [v["value"] for v in fk["top_values"][:limit]]
        return []

    # ─── query templates ───

    def record_successful_query(
        self,
        intent: str,
        pattern: str,
        sql: str,
        exec_time_ms: float,
    ):
        """Record a successful query for template learning."""
        now = time.time()

        # Check for existing similar template
        row = self.conn.execute(
            "SELECT template_id, success_count, avg_exec_ms FROM query_templates "
            "WHERE intent = ? AND pattern = ? LIMIT 1",
            [intent, pattern],
        ).fetchone()

        if row:
            # Update existing
            new_count = row["success_count"] + 1
            new_avg = (row["avg_exec_ms"] * row["success_count"] + exec_time_ms) / new_count
            self.conn.execute(
                "UPDATE query_templates SET success_count = ?, avg_exec_ms = ?, last_used = ? "
                "WHERE template_id = ?",
                [new_count, new_avg, now, row["template_id"]],
            )
        else:
            # Insert new
            self.conn.execute(
                "INSERT INTO query_templates (intent, pattern, sql_template, "
                "success_count, avg_exec_ms, created_at, last_used) "
                "VALUES (?,?,?,1,?,?,?)",
                [intent, pattern, sql, exec_time_ms, now, now],
            )

        self.conn.commit()

    def suggest_template(self, intent: str) -> str | None:
        """Suggest a SQL template for an intent based on past success."""
        row = self.conn.execute(
            "SELECT sql_template FROM query_templates "
            "WHERE intent = ? AND success_count > fail_count "
            "ORDER BY success_count DESC LIMIT 1",
            [intent],
        ).fetchone()
        return row["sql_template"] if row else None

    # ─── value synonyms ───

    def add_synonym(
        self,
        field_name: str,
        canonical_value: str,
        synonym: str,
        confidence: float = 1.0,
        source: str = "ontology",
    ):
        """Record a value synonym."""
        self.conn.execute(
            "INSERT OR REPLACE INTO value_synonyms "
            "(field_name, canonical_value, synonym, confidence, source) "
            "VALUES (?,?,?,?,?)",
            [field_name, canonical_value, synonym, confidence, source],
        )
        self.conn.commit()

    def resolve_synonym(self, field_name: str, value: str) -> str | None:
        """Look up canonical value for a synonym."""
        row = self.conn.execute(
            "SELECT canonical_value FROM value_synonyms "
            "WHERE field_name = ? AND synonym = ? COLLATE NOCASE "
            "ORDER BY confidence DESC LIMIT 1",
            [field_name, value],
        ).fetchone()
        return row["canonical_value"] if row else None

    def get_all_synonyms(self, field_name: str, canonical: str) -> list[str]:
        """Get all synonyms for a canonical value."""
        rows = self.conn.execute(
            "SELECT synonym FROM value_synonyms "
            "WHERE field_name = ? AND canonical_value = ? "
            "ORDER BY confidence DESC",
            [field_name, canonical],
        ).fetchall()
        return [r["synonym"] for r in rows]

    # ─── auto-populate from DAL ───

    def populate_from_dal(self, dal):
        """
        Auto-populate field knowledge from the DAL's SchemaInspector.
        Call once at startup or periodically.
        """
        schema = dal.schema_inspector.analyze()

        semantic_map = {
            "tissue": "tissue", "disease": "disease",
            "cell_type": "cell_type", "assay": "assay",
            "sex": "category", "organism": "category",
            "source_database": "source", "sample_source": "source",
            "sample_id": "id", "project_id": "id", "series_id": "id",
            "pmid": "id", "doi": "id",
            "n_cells": "metric", "cell_count": "metric",
            "citation_count": "metric",
        }

        for tbl_name, tbl_info in schema["tables"].items():
            if tbl_info["is_view"]:
                continue
            for col in tbl_info["columns"]:
                col_name = col["name"]
                sem_type = semantic_map.get(col_name, "other")
                try:
                    stats = dal.get_field_stats(tbl_name, col_name, top_n=20)
                    self.store_field_knowledge(
                        table_name=tbl_name,
                        field_name=col_name,
                        semantic_type=sem_type,
                        null_pct=stats.null_pct,
                        unique_count=stats.distinct_count,
                        top_values=stats.top_values,
                    )
                except Exception:
                    pass  # skip columns that can't be analyzed

        logger.info("Populated semantic memory from DAL")
