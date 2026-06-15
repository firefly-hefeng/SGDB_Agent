"""
Workspace storage — independent SQLite DB for user-saved collections (Phase 15D).

Identity: each workspace belongs to a `user_token` derived from
client IP + a stable UUID the frontend persists in localStorage.
This gives us anonymous-but-stable scoping without a login flow.

Soft delete: workspaces have a `deleted_at` column instead of being
removed; the /recover route undoes the soft delete.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS workspaces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_token TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_workspaces_user_active
    ON workspaces(user_token, deleted_at);

CREATE TABLE IF NOT EXISTS workspace_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL,
    item_type TEXT NOT NULL,
    item_pk INTEGER,
    item_id TEXT NOT NULL,
    source_database TEXT,
    title TEXT,
    metadata_json TEXT,
    note TEXT,
    added_at TEXT NOT NULL,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
    UNIQUE (workspace_id, item_type, item_id)
);
CREATE INDEX IF NOT EXISTS idx_workspace_items_ws
    ON workspace_items(workspace_id);
"""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class WorkspaceStore:
    """Single-process SQLite-backed store. Thread-safe via per-call connections."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        return con

    def _init_schema(self):
        with self._lock, self._conn() as con:
            con.executescript(SCHEMA)
            con.commit()

    # ── Workspace CRUD ──

    def create(self, user_token: str, name: str, description: str = "") -> dict:
        ts = _now()
        with self._lock, self._conn() as con:
            cur = con.execute(
                "INSERT INTO workspaces (user_token, name, description, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_token, name, description, ts, ts),
            )
            con.commit()
            return self._fetch_workspace(con, cur.lastrowid)

    def list_for_user(self, user_token: str, include_deleted: bool = False) -> list[dict]:
        with self._conn() as con:
            if include_deleted:
                rows = con.execute(
                    "SELECT * FROM workspaces WHERE user_token = ? ORDER BY updated_at DESC",
                    (user_token,),
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT * FROM workspaces WHERE user_token = ? AND deleted_at IS NULL "
                    "ORDER BY updated_at DESC",
                    (user_token,),
                ).fetchall()
            results = []
            for r in rows:
                ws = dict(r)
                ws["item_count"] = con.execute(
                    "SELECT COUNT(*) FROM workspace_items WHERE workspace_id = ?",
                    (ws["id"],),
                ).fetchone()[0]
                results.append(ws)
            return results

    def get(self, workspace_id: int, user_token: str) -> dict | None:
        with self._conn() as con:
            return self._fetch_workspace(con, workspace_id, user_token=user_token)

    def update(
        self, workspace_id: int, user_token: str,
        name: str | None = None, description: str | None = None,
    ) -> dict | None:
        with self._lock, self._conn() as con:
            ws = self._fetch_workspace(con, workspace_id, user_token=user_token)
            # Audit F13: a soft-deleted workspace must not be mutated (the owner
            # may still read it via get()/list to recover it, but not edit it).
            if ws is None or ws.get("deleted_at"):
                return None
            updates = []
            params: list[Any] = []
            if name is not None:
                updates.append("name = ?")
                params.append(name)
            if description is not None:
                updates.append("description = ?")
                params.append(description)
            if not updates:
                return ws
            updates.append("updated_at = ?")
            params.append(_now())
            params.append(workspace_id)
            con.execute(f"UPDATE workspaces SET {', '.join(updates)} WHERE id = ?", params)
            con.commit()
            return self._fetch_workspace(con, workspace_id, user_token=user_token)

    def soft_delete(self, workspace_id: int, user_token: str) -> bool:
        with self._lock, self._conn() as con:
            ws = self._fetch_workspace(con, workspace_id, user_token=user_token)
            if ws is None or ws.get("deleted_at"):
                return False
            con.execute(
                "UPDATE workspaces SET deleted_at = ?, updated_at = ? WHERE id = ?",
                (_now(), _now(), workspace_id),
            )
            con.commit()
            return True

    def recover(self, workspace_id: int, user_token: str) -> bool:
        with self._lock, self._conn() as con:
            row = con.execute(
                "SELECT * FROM workspaces WHERE id = ? AND user_token = ?",
                (workspace_id, user_token),
            ).fetchone()
            if row is None or row["deleted_at"] is None:
                return False
            con.execute(
                "UPDATE workspaces SET deleted_at = NULL, updated_at = ? WHERE id = ?",
                (_now(), workspace_id),
            )
            con.commit()
            return True

    # ── Item operations ──

    def add_items(self, workspace_id: int, user_token: str, items: list[dict]) -> dict:
        """Insert items (idempotent on (item_type, item_id))."""
        with self._lock, self._conn() as con:
            ws = self._fetch_workspace(con, workspace_id, user_token=user_token)
            if ws is None:
                return {"added": 0, "skipped": 0, "error": "not_found"}
            # Audit F13: refuse to mutate a soft-deleted workspace.
            if ws.get("deleted_at"):
                return {"added": 0, "skipped": 0, "error": "deleted"}
            added = 0
            skipped = 0
            ts = _now()
            for it in items:
                item_type = it.get("item_type") or "sample"
                item_id = str(it.get("item_id", ""))
                if not item_id:
                    skipped += 1
                    continue
                metadata_json = json.dumps(it.get("metadata"), ensure_ascii=False) if it.get("metadata") else None
                try:
                    con.execute(
                        "INSERT INTO workspace_items "
                        "(workspace_id, item_type, item_pk, item_id, source_database, title, "
                        " metadata_json, note, added_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (workspace_id, item_type, it.get("item_pk"), item_id,
                         it.get("source_database"), it.get("title"),
                         metadata_json, it.get("note"), ts),
                    )
                    added += 1
                except sqlite3.IntegrityError:
                    skipped += 1
            if added:
                con.execute(
                    "UPDATE workspaces SET updated_at = ? WHERE id = ?",
                    (ts, workspace_id),
                )
            con.commit()
            return {"added": added, "skipped": skipped}

    def remove_item(self, workspace_id: int, user_token: str, item_pk: int) -> bool:
        with self._lock, self._conn() as con:
            ws = self._fetch_workspace(con, workspace_id, user_token=user_token)
            # Audit F13: refuse to mutate a soft-deleted workspace.
            if ws is None or ws.get("deleted_at"):
                return False
            cur = con.execute(
                "DELETE FROM workspace_items WHERE id = ? AND workspace_id = ?",
                (item_pk, workspace_id),
            )
            if cur.rowcount:
                con.execute(
                    "UPDATE workspaces SET updated_at = ? WHERE id = ?",
                    (_now(), workspace_id),
                )
                con.commit()
                return True
            return False

    def list_items(self, workspace_id: int, user_token: str) -> list[dict]:
        with self._conn() as con:
            ws = self._fetch_workspace(con, workspace_id, user_token=user_token)
            if ws is None:
                return []
            rows = con.execute(
                "SELECT * FROM workspace_items WHERE workspace_id = ? ORDER BY added_at DESC",
                (workspace_id,),
            ).fetchall()
            return [self._row_to_item(r) for r in rows]

    # ── Internals ──

    def _fetch_workspace(
        self, con: sqlite3.Connection,
        workspace_id: int, user_token: str | None = None,
    ) -> dict | None:
        if user_token is not None:
            row = con.execute(
                "SELECT * FROM workspaces WHERE id = ? AND user_token = ?",
                (workspace_id, user_token),
            ).fetchone()
        else:
            row = con.execute(
                "SELECT * FROM workspaces WHERE id = ?",
                (workspace_id,),
            ).fetchone()
        if row is None:
            return None
        ws = dict(row)
        ws["item_count"] = con.execute(
            "SELECT COUNT(*) FROM workspace_items WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchone()[0]
        return ws

    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> dict:
        d = dict(row)
        if d.get("metadata_json"):
            try:
                d["metadata"] = json.loads(d["metadata_json"])
            except Exception:
                d["metadata"] = None
        else:
            d["metadata"] = None
        d.pop("metadata_json", None)
        return d
