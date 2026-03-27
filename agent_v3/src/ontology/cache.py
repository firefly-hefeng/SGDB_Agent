"""
Ontology Cache — SQLite-backed local ontology storage

Stores parsed OBO terms with:
- Label / synonym lookup (exact + FTS5 fuzzy)
- Parent / child / ancestor / descendant traversal
- Pre-computed value mapping to unified_metadata.db
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import List, Optional

from .parser import OBOParser, OBOTerm

logger = logging.getLogger(__name__)

# --------------- schema ---------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ontology_terms (
    ontology_id       TEXT PRIMARY KEY,
    ontology_source   TEXT NOT NULL,           -- UBERON / MONDO / CL / EFO
    label             TEXT NOT NULL,
    definition        TEXT,
    synonyms_json     TEXT,                    -- JSON array of strings
    parent_ids_json   TEXT,
    child_ids_json    TEXT,
    ancestor_ids_json TEXT,                    -- all transitive ancestors
    descendant_ids_json TEXT                   -- all transitive descendants
);

CREATE INDEX IF NOT EXISTS idx_onto_label
    ON ontology_terms(label COLLATE NOCASE);

CREATE INDEX IF NOT EXISTS idx_onto_source
    ON ontology_terms(ontology_source);

-- value mapping: ontology term → actual DB values in unified_metadata
CREATE TABLE IF NOT EXISTS ontology_value_map (
    ontology_id   TEXT    NOT NULL,
    field_name    TEXT    NOT NULL,            -- tissue / disease / cell_type / assay
    db_value      TEXT    NOT NULL,
    sample_count  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (ontology_id, field_name, db_value)
);

CREATE INDEX IF NOT EXISTS idx_ovm_field_value
    ON ontology_value_map(field_name, db_value);

-- metadata
CREATE TABLE IF NOT EXISTS ontology_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS fts_ontology USING fts5(
    ontology_id UNINDEXED,
    label,
    synonyms,
    tokenize='porter unicode61'
);
"""


class OntologyCache:
    """
    SQLite-backed ontology cache.

    Typical lifecycle:
    1. build_from_obo()   — parse OBO files and populate DB (offline, once)
    2. build_value_map()  — map ontology terms to DB values (offline, once)
    3. lookup_*()         — runtime queries (<5ms each)
    """

    def __init__(self, cache_path: str | Path):
        self.cache_path = Path(cache_path)
        self._conn: sqlite3.Connection | None = None

    # --------------- connection ---------------

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.cache_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA cache_size=-32768")  # 32 MB
        return self._conn

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    # --------------- build (offline) ---------------

    def init_schema(self):
        """Create tables if they don't exist."""
        self.conn.executescript(_SCHEMA)
        try:
            self.conn.executescript(_FTS_SCHEMA)
        except sqlite3.OperationalError:
            logger.warning("FTS5 not available; fuzzy search disabled")
        self.conn.commit()

    def build_from_obo(self, obo_path: str | Path, source_filter: str | None = None):
        """
        Parse an OBO file and insert terms into the cache.

        source_filter: if given, only keep terms whose ontology_id starts with
                       this prefix (e.g. "UBERON:" for uberon.obo).
        """
        obo_path = Path(obo_path)
        parser = OBOParser(obo_path)
        terms = parser.parse()
        closure = parser.compute_ancestors_descendants()

        # detect source prefix from first real term
        if source_filter is None:
            source_prefix = obo_path.stem.upper()
        else:
            source_prefix = source_filter

        t0 = time.time()
        batch = []
        fts_batch = []

        for term_id, term in terms.items():
            anc_set, desc_set = closure.get(term_id, (set(), set()))
            synonyms = term.synonyms or []

            batch.append((
                term.ontology_id,
                term.ontology_source,
                term.label,
                term.definition,
                json.dumps(synonyms),
                json.dumps(term.parent_ids),
                json.dumps(term.child_ids),
                json.dumps(sorted(anc_set)),
                json.dumps(sorted(desc_set)),
            ))

            fts_batch.append((
                term.ontology_id,
                term.label,
                " ".join(synonyms),
            ))

        # bulk insert
        self.conn.executemany(
            "INSERT OR REPLACE INTO ontology_terms VALUES (?,?,?,?,?,?,?,?,?)",
            batch,
        )
        try:
            self.conn.executemany(
                "INSERT OR REPLACE INTO fts_ontology(ontology_id, label, synonyms) VALUES (?,?,?)",
                fts_batch,
            )
        except sqlite3.OperationalError:
            pass  # FTS5 not available

        self.conn.commit()
        elapsed = time.time() - t0
        logger.info("Loaded %d terms from %s in %.1fs", len(batch), obo_path.name, elapsed)
        print(f"  ✓ Loaded {len(batch):,} terms from {obo_path.name} in {elapsed:.1f}s")

    # --------------- value mapping (offline) ---------------

    def build_value_map(
        self,
        metadata_db_path: str | Path,
        field_configs: dict[str, tuple[str, str]] | None = None,
    ):
        """
        Pre-compute which ontology terms match actual DB values.

        field_configs maps field_name → (table, column), e.g.:
            {"tissue": ("unified_samples", "tissue"), ...}
        """
        if field_configs is None:
            field_configs = {
                "tissue":    ("unified_samples", "tissue"),
                "disease":   ("unified_samples", "disease"),
                "cell_type": ("unified_samples", "cell_type"),
            }

        meta_conn = sqlite3.connect(str(metadata_db_path))
        meta_conn.row_factory = sqlite3.Row

        total_mapped = 0

        for field_name, (table, column) in field_configs.items():
            print(f"  Mapping {field_name}...")
            t0 = time.time()

            # get distinct values from metadata DB
            cursor = meta_conn.execute(f"""
                SELECT [{column}], COUNT(*) as cnt
                FROM [{table}]
                WHERE [{column}] IS NOT NULL
                GROUP BY [{column}]
            """)
            db_values = {row[column]: row["cnt"] for row in cursor}

            mapped = 0
            batch = []

            # for each ontology term, check if label or synonym matches a DB value
            terms_cursor = self.conn.execute(
                "SELECT ontology_id, label, synonyms_json FROM ontology_terms"
            )
            for row in terms_cursor:
                term_id = row["ontology_id"]
                label = row["label"]
                synonyms = json.loads(row["synonyms_json"]) if row["synonyms_json"] else []

                # exact match on label
                label_lower = label.lower()
                for db_val, cnt in db_values.items():
                    if db_val.lower() == label_lower:
                        batch.append((term_id, field_name, db_val, cnt))
                        mapped += 1

                # exact match on synonyms
                for syn in synonyms:
                    syn_lower = syn.lower()
                    for db_val, cnt in db_values.items():
                        if db_val.lower() == syn_lower:
                            batch.append((term_id, field_name, db_val, cnt))
                            mapped += 1

            # bulk insert
            self.conn.executemany(
                "INSERT OR REPLACE INTO ontology_value_map VALUES (?,?,?,?)",
                batch,
            )
            self.conn.commit()
            elapsed = time.time() - t0
            total_mapped += mapped
            print(f"    ✓ {mapped:,} mappings for {field_name} in {elapsed:.1f}s")

        meta_conn.close()
        print(f"  Total: {total_mapped:,} ontology→DB value mappings")
        return total_mapped

    # --------------- runtime lookups ---------------

    def lookup_exact(self, label: str) -> Optional[dict]:
        """Exact case-insensitive label match."""
        row = self.conn.execute(
            "SELECT * FROM ontology_terms WHERE label = ? COLLATE NOCASE LIMIT 1",
            [label],
        ).fetchone()
        return dict(row) if row else None

    def lookup_synonym(self, term: str) -> Optional[dict]:
        """Search all synonyms for a match."""
        term_lower = term.lower()
        # use FTS5 first
        try:
            rows = self.conn.execute(
                'SELECT ontology_id FROM fts_ontology WHERE synonyms MATCH ? LIMIT 5',
                [f'"{term}"'],
            ).fetchall()
            if rows:
                for r in rows:
                    full = self.conn.execute(
                        "SELECT * FROM ontology_terms WHERE ontology_id = ?",
                        [r["ontology_id"]],
                    ).fetchone()
                    if full:
                        syns = json.loads(full["synonyms_json"]) if full["synonyms_json"] else []
                        if any(s.lower() == term_lower for s in syns):
                            return dict(full)
        except sqlite3.OperationalError:
            pass  # FTS5 not available, fall through

        # brute-force fallback (slower)
        cursor = self.conn.execute("SELECT * FROM ontology_terms")
        for row in cursor:
            syns = json.loads(row["synonyms_json"]) if row["synonyms_json"] else []
            if any(s.lower() == term_lower for s in syns):
                return dict(row)
        return None

    def lookup_fuzzy(self, term: str, limit: int = 5) -> list[dict]:
        """FTS5 fuzzy search on label + synonyms."""
        try:
            # tokenize for FTS5 (handle multi-word)
            fts_query = " OR ".join(w + "*" for w in term.split() if len(w) > 2)
            if not fts_query:
                fts_query = term + "*"

            rows = self.conn.execute(
                "SELECT ontology_id, label, rank FROM fts_ontology "
                "WHERE fts_ontology MATCH ? ORDER BY rank LIMIT ?",
                [fts_query, limit],
            ).fetchall()

            results = []
            for r in rows:
                full = self.conn.execute(
                    "SELECT * FROM ontology_terms WHERE ontology_id = ?",
                    [r["ontology_id"]],
                ).fetchone()
                if full:
                    d = dict(full)
                    d["fts_rank"] = r["rank"]
                    results.append(d)
            return results
        except sqlite3.OperationalError:
            return []

    def get_db_values(self, ontology_id: str, field_name: str) -> list[tuple[str, int]]:
        """Get DB values mapped to an ontology term."""
        rows = self.conn.execute(
            "SELECT db_value, sample_count FROM ontology_value_map "
            "WHERE ontology_id = ? AND field_name = ? "
            "ORDER BY sample_count DESC",
            [ontology_id, field_name],
        ).fetchall()
        return [(r["db_value"], r["sample_count"]) for r in rows]

    def get_children_values(
        self, ontology_id: str, field_name: str, max_children: int = 20,
    ) -> list[tuple[str, str, int]]:
        """
        Get DB values for child terms (ontology expansion).
        Returns: [(child_id, db_value, sample_count), ...]
        """
        row = self.conn.execute(
            "SELECT child_ids_json FROM ontology_terms WHERE ontology_id = ?",
            [ontology_id],
        ).fetchone()
        if not row or not row["child_ids_json"]:
            return []

        child_ids = json.loads(row["child_ids_json"])[:max_children]
        results = []
        for cid in child_ids:
            vals = self.get_db_values(cid, field_name)
            for db_val, cnt in vals:
                results.append((cid, db_val, cnt))
        return results

    def get_descendant_values(
        self, ontology_id: str, field_name: str, max_terms: int = 50,
    ) -> list[tuple[str, str, int]]:
        """
        Get DB values for ALL descendant terms (deep expansion).
        Returns: [(descendant_id, db_value, sample_count), ...]
        """
        row = self.conn.execute(
            "SELECT descendant_ids_json FROM ontology_terms WHERE ontology_id = ?",
            [ontology_id],
        ).fetchone()
        if not row or not row["descendant_ids_json"]:
            return []

        desc_ids = json.loads(row["descendant_ids_json"])[:max_terms]
        results = []
        for did in desc_ids:
            vals = self.get_db_values(did, field_name)
            for db_val, cnt in vals:
                results.append((did, db_val, cnt))
        return results

    def get_stats(self) -> dict:
        """Return cache statistics."""
        stats = {}
        row = self.conn.execute("SELECT COUNT(*) as cnt FROM ontology_terms").fetchone()
        stats["total_terms"] = row["cnt"]

        cursor = self.conn.execute(
            "SELECT ontology_source, COUNT(*) as cnt FROM ontology_terms "
            "GROUP BY ontology_source ORDER BY cnt DESC"
        )
        stats["by_source"] = {r["ontology_source"]: r["cnt"] for r in cursor}

        row = self.conn.execute("SELECT COUNT(*) as cnt FROM ontology_value_map").fetchone()
        stats["total_mappings"] = row["cnt"]

        return stats
