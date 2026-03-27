"""Base ETL class with common utilities for all data source pipelines."""

import sqlite3
import json
import hashlib
import logging
import math
import re
import time
from datetime import datetime
from typing import Dict, List, Optional, Any, Iterator

logger = logging.getLogger(__name__)


class BaseETL:
    """Base class for all ETL pipelines."""

    SOURCE_DATABASE: str = ''  # Override in subclass
    BATCH_SIZE: int = 5000

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None
        self.stats = {
            'processed': 0, 'loaded': 0,
            'skipped': 0, 'errored': 0
        }
        self._start_time = None

    def connect(self):
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA synchronous = NORMAL")
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA cache_size = -64000")  # 64MB
        self.conn.row_factory = sqlite3.Row

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None

    def run(self):
        """Main entry point. Override in subclass."""
        self._start_time = time.time()
        try:
            self.connect()
            self.log_run('full', 'started')
            self.extract_and_load()
            elapsed = time.time() - self._start_time
            self.log_run('full', 'completed', duration=elapsed)
            logger.info(
                f"[{self.SOURCE_DATABASE}] ETL completed in {elapsed:.1f}s. "
                f"Processed={self.stats['processed']}, Loaded={self.stats['loaded']}, "
                f"Skipped={self.stats['skipped']}, Errors={self.stats['errored']}"
            )
        except Exception as e:
            elapsed = time.time() - self._start_time
            self.log_run('full', 'failed', error_msg=str(e), duration=elapsed)
            logger.error(f"[{self.SOURCE_DATABASE}] ETL failed: {e}")
            raise
        finally:
            self.close()

    def extract_and_load(self):
        """Override in subclass to implement the ETL logic."""
        raise NotImplementedError

    # ── Batch insert ──────────────────────────────────────────

    def batch_insert(self, table: str, rows: List[Dict],
                     on_conflict: str = 'IGNORE') -> int:
        """Insert rows in batch. Returns number of rows affected."""
        if not rows:
            return 0
        columns = list(rows[0].keys())
        placeholders = ', '.join(['?' for _ in columns])
        col_names = ', '.join(columns)

        sql = f"INSERT OR {on_conflict} INTO {table} ({col_names}) VALUES ({placeholders})"

        values = [tuple(row.get(c) for c in columns) for row in rows]
        cursor = self.conn.executemany(sql, values)
        self.conn.commit()
        return cursor.rowcount

    def insert_one(self, table: str, row: Dict,
                   on_conflict: str = 'IGNORE') -> Optional[int]:
        """Insert a single row and return its pk (or existing pk on conflict)."""
        columns = list(row.keys())
        placeholders = ', '.join(['?' for _ in columns])
        col_names = ', '.join(columns)
        values = tuple(row.get(c) for c in columns)

        sql = f"INSERT OR {on_conflict} INTO {table} ({col_names}) VALUES ({placeholders})"
        cursor = self.conn.execute(sql, values)
        if cursor.lastrowid:
            return cursor.lastrowid
        return None

    # ── Lookup helpers ────────────────────────────────────────

    def lookup_pk(self, table: str, **kwargs) -> Optional[int]:
        """Lookup pk by unique key fields."""
        conditions = ' AND '.join([f"{k} = ?" for k in kwargs.keys()])
        sql = f"SELECT pk FROM {table} WHERE {conditions}"
        cursor = self.conn.execute(sql, tuple(kwargs.values()))
        row = cursor.fetchone()
        return row[0] if row else None

    def lookup_or_insert(self, table: str, unique_fields: Dict,
                         full_row: Dict) -> int:
        """Lookup by unique fields, insert if not found. Returns pk."""
        pk = self.lookup_pk(table, **unique_fields)
        if pk:
            return pk
        pk = self.insert_one(table, full_row)
        if pk:
            return pk
        # Race condition fallback
        return self.lookup_pk(table, **unique_fields)

    # ── ID mappings ───────────────────────────────────────────

    def add_id_mapping(self, entity_type: str, entity_pk: int,
                       id_type: str, id_value: str,
                       is_primary: int = 0):
        """Add an ID mapping entry."""
        if not id_value or not entity_pk:
            return
        self.conn.execute(
            """INSERT OR IGNORE INTO id_mappings
               (entity_type, entity_pk, id_type, id_value, id_source_database, is_primary)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (entity_type, entity_pk, id_type, str(id_value).strip(),
             self.SOURCE_DATABASE, is_primary)
        )

    def flush_id_mappings(self):
        """Commit pending id_mappings."""
        self.conn.commit()

    # ── ETL run log ───────────────────────────────────────────

    def log_run(self, phase: str, status: str, error_msg: str = None,
                duration: float = None):
        """Log ETL run to etl_run_log table."""
        try:
            self.conn.execute(
                """INSERT INTO etl_run_log
                   (source_database, phase, status, records_processed, records_loaded,
                    records_skipped, records_errored, error_message,
                    started_at, duration_seconds)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (self.SOURCE_DATABASE, phase, status,
                 self.stats['processed'], self.stats['loaded'],
                 self.stats['skipped'], self.stats['errored'],
                 error_msg, datetime.now().isoformat(), duration)
            )
            self.conn.commit()
        except Exception:
            pass  # Don't fail ETL because of logging

    # ── Identity hash ─────────────────────────────────────────

    @staticmethod
    def compute_identity_hash(organism: str = None, tissue: str = None,
                              disease: str = None, sex: str = None,
                              individual_id: str = None,
                              development_stage: str = None) -> Optional[str]:
        """Compute MD5 hash for biological sample identity.

        Returns None if insufficient fields for a meaningful hash.
        """
        def norm(val):
            if val is None:
                return ''
            return str(val).strip().lower()

        parts = [
            norm(organism), norm(tissue), norm(disease),
            norm(sex), norm(individual_id), norm(development_stage)
        ]

        # Need at least organism + one other field
        if parts[0] == '' or all(p == '' for p in parts[1:]):
            return None

        hash_input = '::'.join(parts)
        return hashlib.md5(hash_input.encode('utf-8')).hexdigest()

    # ── Normalization utilities ───────────────────────────────

    @staticmethod
    def normalize_organism(val: str) -> Optional[str]:
        if not val:
            return None
        val = val.strip()
        mapping = {
            'homo sapiens': 'Homo sapiens',
            'human': 'Homo sapiens',
            'mus musculus': 'Mus musculus',
            'mouse': 'Mus musculus',
            'macaca mulatta': 'Macaca mulatta',
            'rattus norvegicus': 'Rattus norvegicus',
            'danio rerio': 'Danio rerio',
        }
        return mapping.get(val.lower(), val)

    @staticmethod
    def normalize_sex(val: str) -> Optional[str]:
        if not val:
            return None
        val = val.strip().lower()
        mapping = {
            'male': 'male', 'm': 'male', 'man': 'male',
            'female': 'female', 'f': 'female', 'woman': 'female',
            'unknown': 'unknown', 'na': 'unknown',
            'not reported': 'unknown', 'n/a': 'unknown',
            'mixed': 'mixed',
        }
        return mapping.get(val, val)

    @staticmethod
    def parse_age_from_dev_stage(dev_stage: str):
        """Extract age and unit from development stage string.

        Input: '39-year-old stage', '3-month-old', etc.
        Returns: (age_str, unit) or (None, None)
        """
        if not dev_stage or dev_stage.lower() == 'unknown':
            return None, None
        match = re.match(r'(\d+)-year-old', dev_stage)
        if match:
            return match.group(1), 'year'
        match = re.match(r'(\d+)-month-old', dev_stage)
        if match:
            return match.group(1), 'month'
        match = re.match(r'(\d+)-week-old', dev_stage)
        if match:
            return match.group(1), 'week'
        match = re.match(r'(\d+)-day-old', dev_stage)
        if match:
            return match.group(1), 'day'
        return None, None

    @staticmethod
    def safe_json_dumps(obj) -> Optional[str]:
        """Safely serialize to JSON."""
        if obj is None:
            return None
        try:
            return json.dumps(obj, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return json.dumps(str(obj))

    @staticmethod
    def clean_str(val) -> Optional[str]:
        """Clean a string value: strip, convert NaN/None to None."""
        if val is None:
            return None
        if isinstance(val, float) and math.isnan(val):
            return None
        val = str(val).strip()
        if val in ('', 'nan', 'NaN', 'None', 'NA', 'N/A'):
            return None
        return val

    @staticmethod
    def float_to_int_str(val) -> Optional[str]:
        """Convert float PubMed ID to integer string.

        Input: 37012345.0 or '37012345.0' or NaN
        Output: '37012345' or None
        """
        if val is None:
            return None
        if isinstance(val, float) and math.isnan(val):
            return None
        try:
            return str(int(float(val)))
        except (ValueError, OverflowError):
            return None

    # ── Progress logging ──────────────────────────────────────

    def log_progress(self, phase: str = ''):
        """Log progress every 10000 records."""
        if self.stats['processed'] % 10000 == 0 and self.stats['processed'] > 0:
            elapsed = time.time() - self._start_time
            rate = self.stats['processed'] / elapsed if elapsed > 0 else 0
            logger.info(
                f"[{self.SOURCE_DATABASE}] {phase} progress: "
                f"{self.stats['processed']} processed, "
                f"{self.stats['loaded']} loaded, "
                f"{rate:.0f} rec/s"
            )
