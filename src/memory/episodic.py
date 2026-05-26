"""
Episodic Memory — User-level persistent storage (SQLite)

Tracks per-user:
- Query history (with success/failure indicators)
- Learned query patterns (frequent tissues, diseases, etc.)
- User profile (research domain inference)

Lifecycle: persists across sessions, isolated per user.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..core.models import ParsedQuery

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id             TEXT PRIMARY KEY,
    research_domain     TEXT,
    preferred_tissues   TEXT,  -- JSON array
    preferred_sources   TEXT,  -- JSON array
    query_count         INTEGER DEFAULT 0,
    created_at          REAL,
    last_active         REAL
);

CREATE TABLE IF NOT EXISTS query_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    query_text  TEXT NOT NULL,
    intent      TEXT,
    filters_json TEXT,
    result_count INTEGER,
    sql_method  TEXT,
    exec_time_ms REAL,
    created_at  REAL
);

CREATE INDEX IF NOT EXISTS idx_qh_user  ON query_history(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_qh_session ON query_history(session_id);

CREATE TABLE IF NOT EXISTS query_patterns (
    user_id     TEXT NOT NULL,
    pattern_type TEXT NOT NULL,     -- tissue / disease / cell_type / assay / source
    pattern_value TEXT NOT NULL,
    frequency   INTEGER DEFAULT 1,
    last_used   REAL,
    PRIMARY KEY (user_id, pattern_type, pattern_value)
);
"""


@dataclass
class UserProfile:
    """Learned user profile."""
    user_id: str
    research_domain: str = ""
    preferred_tissues: list[str] = field(default_factory=list)
    preferred_sources: list[str] = field(default_factory=list)
    query_count: int = 0
    top_patterns: dict[str, list[str]] = field(default_factory=dict)


class EpisodicMemory:
    """
    SQLite-backed user-level memory.

    Auto-learns user preferences from query history:
    - Frequently searched tissues/diseases → preferred_tissues
    - Frequently used sources → preferred_sources
    - Research domain inference from top patterns
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

    # ─── record ───

    def record_query(
        self,
        user_id: str,
        session_id: str,
        query: ParsedQuery,
        result_count: int = 0,
        sql_method: str = "",
        exec_time_ms: float = 0,
    ):
        """Record a query and update patterns."""
        now = time.time()

        # Insert history
        f = query.filters
        self.conn.execute(
            "INSERT INTO query_history "
            "(user_id, session_id, query_text, intent, filters_json, "
            "result_count, sql_method, exec_time_ms, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            [
                user_id, session_id, query.original_text,
                query.intent.name,
                json.dumps({
                    "tissues": f.tissues, "diseases": f.diseases,
                    "cell_types": f.cell_types, "assays": f.assays,
                    "sources": f.source_databases,
                }),
                result_count, sql_method, exec_time_ms, now,
            ],
        )

        # Update patterns
        patterns = []
        for t in f.tissues:
            patterns.append(("tissue", t))
        for d in f.diseases:
            patterns.append(("disease", d))
        for c in f.cell_types:
            patterns.append(("cell_type", c))
        for a in f.assays:
            patterns.append(("assay", a))
        for s in f.source_databases:
            patterns.append(("source", s))

        for ptype, pval in patterns:
            self.conn.execute(
                "INSERT INTO query_patterns (user_id, pattern_type, pattern_value, frequency, last_used) "
                "VALUES (?,?,?,1,?) "
                "ON CONFLICT(user_id, pattern_type, pattern_value) "
                "DO UPDATE SET frequency = frequency + 1, last_used = ?",
                [user_id, ptype, pval, now, now],
            )

        # Upsert user profile
        self.conn.execute(
            "INSERT INTO user_profiles (user_id, query_count, created_at, last_active) "
            "VALUES (?, 1, ?, ?) "
            "ON CONFLICT(user_id) "
            "DO UPDATE SET query_count = query_count + 1, last_active = ?",
            [user_id, now, now, now],
        )

        self.conn.commit()

    # ─── retrieve ───

    def get_user_profile(self, user_id: str) -> UserProfile:
        """Load user profile with learned patterns."""
        profile = UserProfile(user_id=user_id)

        row = self.conn.execute(
            "SELECT * FROM user_profiles WHERE user_id = ?", [user_id]
        ).fetchone()
        if row:
            profile.query_count = row["query_count"]
            profile.preferred_tissues = json.loads(row["preferred_tissues"]) if row["preferred_tissues"] else []
            profile.preferred_sources = json.loads(row["preferred_sources"]) if row["preferred_sources"] else []
            profile.research_domain = row["research_domain"] or ""

        # Top patterns by frequency
        for ptype in ("tissue", "disease", "cell_type", "assay", "source"):
            rows = self.conn.execute(
                "SELECT pattern_value, frequency FROM query_patterns "
                "WHERE user_id = ? AND pattern_type = ? "
                "ORDER BY frequency DESC LIMIT 5",
                [user_id, ptype],
            ).fetchall()
            if rows:
                profile.top_patterns[ptype] = [r["pattern_value"] for r in rows]

        return profile

    def get_recent_queries(
        self, user_id: str, limit: int = 10
    ) -> list[dict]:
        """Get recent query history for a user."""
        rows = self.conn.execute(
            "SELECT query_text, intent, result_count, sql_method, "
            "exec_time_ms, created_at "
            "FROM query_history WHERE user_id = ? "
            "ORDER BY created_at DESC LIMIT ?",
            [user_id, limit],
        ).fetchall()
        return [dict(r) for r in rows]

    def update_user_preferences(self, user_id: str):
        """Auto-learn preferences from query patterns (call periodically)."""
        # Top 3 tissues
        rows = self.conn.execute(
            "SELECT pattern_value FROM query_patterns "
            "WHERE user_id = ? AND pattern_type = 'tissue' "
            "ORDER BY frequency DESC LIMIT 3",
            [user_id],
        ).fetchall()
        tissues = json.dumps([r["pattern_value"] for r in rows]) if rows else None

        # Top 3 sources
        rows = self.conn.execute(
            "SELECT pattern_value FROM query_patterns "
            "WHERE user_id = ? AND pattern_type = 'source' "
            "ORDER BY frequency DESC LIMIT 3",
            [user_id],
        ).fetchall()
        sources = json.dumps([r["pattern_value"] for r in rows]) if rows else None

        # Infer research domain from top disease + tissue
        domain = None
        rows = self.conn.execute(
            "SELECT pattern_value FROM query_patterns "
            "WHERE user_id = ? AND pattern_type IN ('disease', 'tissue') "
            "ORDER BY frequency DESC LIMIT 1",
            [user_id],
        ).fetchall()
        if rows:
            domain = rows[0]["pattern_value"]

        self.conn.execute(
            "UPDATE user_profiles SET preferred_tissues = ?, "
            "preferred_sources = ?, research_domain = ? "
            "WHERE user_id = ?",
            [tissues, sources, domain, user_id],
        )
        self.conn.commit()
