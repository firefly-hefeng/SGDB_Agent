"""
数据库抽象层 (DAL)

连接 unified_metadata.db，提供统一数据访问接口。
支持 SQLite (当前) 和 PostgreSQL (未来迁移)。

特性:
- 连接池: 复用连接，减少 open/close 开销
- 读写分离: read_only 模式默认
- Schema introspection: 自动发现表结构
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from collections import deque
from pathlib import Path

from ..core.exceptions import DatabaseError, DatabaseNotFoundError
from ..core.models import FieldStats, QueryFilters, QueryResult

logger = logging.getLogger(__name__)


class ConnectionPool:
    """
    简单的 SQLite 连接池

    SQLite 连接不支持跨线程共享 (除非 check_same_thread=False)，
    因此本连接池为线程安全的连接分发器。

    策略:
    - 连接按需创建，复用已关闭的连接
    - max_size 控制上限
    - 使用 context manager 自动回收
    """

    def __init__(self, db_path: str, read_only: bool = True, max_size: int = 8):
        self._db_path = db_path
        self._read_only = read_only
        self._max_size = max_size
        self._pool: deque[sqlite3.Connection] = deque()
        self._active_count = 0
        self._lock = threading.Lock()

    def _create_connection(self) -> sqlite3.Connection:
        """Create a new configured SQLite connection."""
        uri = f"file:{self._db_path}"
        if self._read_only:
            uri += "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        # WAL requires write access; skip on read-only connections
        if not self._read_only:
            conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA cache_size=-65536")        # 64MB page cache
        conn.execute("PRAGMA mmap_size=1073741824")     # 1GB memory-mapped I/O
        conn.execute("PRAGMA temp_store=MEMORY")        # temp tables in memory
        return conn

    def acquire(self) -> sqlite3.Connection:
        """Acquire a connection from the pool."""
        with self._lock:
            if self._pool:
                conn = self._pool.popleft()
                self._active_count += 1
                return conn

            if self._active_count < self._max_size:
                conn = self._create_connection()
                self._active_count += 1
                return conn

        # Pool exhausted — create one beyond limit with warning
        logger.warning("Connection pool exhausted (active=%d, max=%d)", self._active_count, self._max_size)
        return self._create_connection()

    def release(self, conn: sqlite3.Connection):
        """Return a connection to the pool."""
        with self._lock:
            self._active_count = max(0, self._active_count - 1)
            if len(self._pool) < self._max_size:
                self._pool.append(conn)
            else:
                conn.close()

    def close_all(self):
        """Close all pooled connections."""
        with self._lock:
            while self._pool:
                self._pool.popleft().close()
            self._active_count = 0


class DatabaseAbstractionLayer:
    """
    数据库抽象层

    职责:
    - 连接池管理
    - 统一查询接口
    - ID自动识别与跨库解析
    - Schema introspection
    """

    # ID模式 → (表, 字段)
    ID_PATTERNS: dict[str, tuple[str, str]] = {
        "GSE": ("unified_projects", "project_id"),
        "GSM": ("unified_samples", "sample_id"),
        "PRJNA": ("unified_projects", "project_id"),
        "SRP": ("unified_series", "series_id"),
        "SRS": ("unified_samples", "sample_id"),
        "SAMN": ("unified_samples", "sample_id"),
        "SAME": ("unified_samples", "sample_id"),
    }

    def __init__(self, db_path: str, read_only: bool = True, pool_size: int = 8):
        self.db_path = db_path
        self.read_only = read_only
        self._schema_inspector: SchemaInspector | None = None

        if not Path(db_path).exists():
            raise DatabaseNotFoundError(db_path)

        # Initialize connection pool
        self._pool = ConnectionPool(db_path, read_only, pool_size)

        # Verify connectivity
        conn = self._pool.acquire()
        self._pool.release(conn)
        logger.info("DAL connected to %s (pool_size=%d)", db_path, pool_size)

    def _get_connection(self) -> sqlite3.Connection:
        """获取数据库连接 (from pool)"""
        return self._pool.acquire()

    def _release_connection(self, conn: sqlite3.Connection):
        """归还连接到池"""
        self._pool.release(conn)

    def close(self):
        """Close all connections."""
        self._pool.close_all()

    @property
    def schema_inspector(self) -> SchemaInspector:
        if self._schema_inspector is None:
            self._schema_inspector = SchemaInspector(self)
        return self._schema_inspector

    # ========== 核心查询接口 ==========

    def execute(self, sql: str, params: list | None = None) -> QueryResult:
        """执行原始SQL"""
        conn = self._get_connection()
        try:
            t0 = time.perf_counter()
            cursor = conn.execute(sql, params or [])
            rows = cursor.fetchall()
            elapsed = (time.perf_counter() - t0) * 1000

            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            dict_rows = [dict(r) for r in rows]

            return QueryResult(
                rows=dict_rows,
                columns=columns,
                total_count=len(dict_rows),
                returned_count=len(dict_rows),
                execution_time_ms=round(elapsed, 2),
                sql=sql,
                source="raw",
            )
        except sqlite3.Error as e:
            raise DatabaseError(f"SQL execution failed: {e}", detail=sql) from e
        finally:
            self._release_connection(conn)

    def search_samples(
        self,
        filters: QueryFilters,
        fields: list[str] | None = None,
        limit: int = 20,
        offset: int = 0,
        use_view: bool = True,
    ) -> QueryResult:
        """搜索样本 - 最常用的查询入口"""
        table = "v_sample_with_hierarchy" if use_view else "unified_samples"
        select = ", ".join(fields) if fields else "*"

        conditions: list[str] = []
        params: list = []

        def _add_list_filter(field: str, values: list[str]):
            if not values:
                return
            placeholders = ", ".join("?" * len(values))
            conditions.append(f"{field} IN ({placeholders})")
            params.extend(values)

        def _add_like_filter(field: str, values: list[str]):
            if not values:
                return
            or_parts = [f"{field} LIKE ?" for _ in values]
            conditions.append(f"({' OR '.join(or_parts)})")
            params.extend(f"%{v}%" for v in values)

        _add_list_filter("organism", filters.organisms)
        _add_like_filter("tissue", filters.tissues)
        _add_like_filter("disease", filters.diseases)
        _add_like_filter("cell_type" if not use_view else "cell_type", filters.cell_types)
        _add_list_filter("source_database" if not use_view else "sample_source", filters.source_databases)

        if filters.sex:
            conditions.append("sex = ?")
            params.append(filters.sex)

        if filters.min_cells is not None:
            conditions.append("n_cells >= ?")
            params.append(filters.min_cells)

        if filters.has_h5ad is not None and use_view:
            conditions.append("assay IS NOT NULL" if filters.has_h5ad else "1=1")

        if filters.pmids:
            _add_list_filter("pmid", filters.pmids)

        where = " AND ".join(conditions) if conditions else "1=1"
        sql = f"SELECT {select} FROM {table} WHERE {where} LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        result = self.execute(sql, params)
        result.source = "view" if use_view else "table"

        # 获取总数
        count_sql = f"SELECT COUNT(*) as cnt FROM {table} WHERE {where}"
        count_result = self.execute(count_sql, params[:-2])  # 去掉LIMIT/OFFSET参数
        if count_result.rows:
            result.total_count = count_result.rows[0]["cnt"]

        return result

    def get_entity_by_id(self, id_value: str) -> dict | None:
        """
        根据ID获取实体 (自动识别ID类型)

        支持: GSE*, GSM*, PRJNA*, SRP*, SRS*, SAMN*, PMID, DOI
        """
        id_upper = id_value.strip().upper()

        # 1. 尝试直接匹配已知ID模式
        for prefix, (table, field) in self.ID_PATTERNS.items():
            if id_upper.startswith(prefix):
                result = self.execute(
                    f"SELECT * FROM {table} WHERE {field} = ? LIMIT 1",
                    [id_value.strip()],
                )
                if result.rows:
                    return result.rows[0]

        # 2. 尝试PMID
        if id_upper.startswith("PMID") or id_upper.isdigit():
            pmid = id_value.replace("PMID:", "").replace("PMID", "").strip()
            result = self.execute(
                "SELECT * FROM unified_projects WHERE pmid = ? LIMIT 5",
                [pmid],
            )
            if result.rows:
                return result.rows[0]

        # 3. 尝试DOI
        if id_value.startswith("10."):
            result = self.execute(
                "SELECT * FROM unified_projects WHERE doi = ? LIMIT 1",
                [id_value.strip()],
            )
            if result.rows:
                return result.rows[0]

        # 4. 查询 id_mappings 表
        result = self.execute(
            "SELECT entity_type, entity_pk FROM id_mappings WHERE id_value = ? LIMIT 1",
            [id_value.strip()],
        )
        if result.rows:
            mapping = result.rows[0]
            table_map = {
                "project": "unified_projects",
                "series": "unified_series",
                "sample": "unified_samples",
            }
            table = table_map.get(mapping["entity_type"])
            if table:
                r2 = self.execute(f"SELECT * FROM {table} WHERE pk = ?", [mapping["entity_pk"]])
                if r2.rows:
                    return r2.rows[0]

        return None

    def get_cross_db_links(self, entity_pk: int, entity_type: str = "project") -> list[dict]:
        """获取跨库关联"""
        result = self.execute("""
            SELECT el.*,
                   p.project_id as linked_id, p.source_database as linked_db, p.title as linked_title
            FROM entity_links el
            LEFT JOIN unified_projects p ON el.target_pk = p.pk
            WHERE (el.source_pk = ? AND el.source_entity_type = ?)
               OR (el.target_pk = ? AND el.target_entity_type = ?)
        """, [entity_pk, entity_type, entity_pk, entity_type])
        return result.rows

    def get_field_stats(
        self, table: str, field: str, top_n: int = 20
    ) -> FieldStats:
        """获取字段统计"""
        return self.schema_inspector.get_field_stats(table, field, top_n)

    def get_schema_summary(self) -> dict:
        """返回schema摘要 (用于System Prompt注入)"""
        return self.schema_inspector.get_summary()


class SchemaInspector:
    """
    动态Schema发现

    自动分析数据库表结构、字段分布、外键关系。
    结果缓存在内存中，启动时构建一次。
    """

    def __init__(self, dal: DatabaseAbstractionLayer):
        self._dal = dal
        self._cache: dict = {}
        self._analyzed = False

    def analyze(self) -> dict:
        """完整schema分析 — uses precomputed stats for fast row counts."""
        if self._analyzed:
            return self._cache

        logger.info("Analyzing database schema...")
        t0 = time.perf_counter()

        tables = {}
        conn = self._dal._get_connection()
        try:
            # Pre-load row counts from stats_overall to avoid slow COUNT(*)
            precomputed_counts: dict[str, int] = {}
            try:
                stats_rows = conn.execute("SELECT metric, value FROM stats_overall").fetchall()
                metric_to_table = {
                    "total_projects": "unified_projects",
                    "total_series": "unified_series",
                    "total_samples": "unified_samples",
                    "total_celltypes": "unified_celltypes",
                    "total_entity_links": "entity_links",
                }
                for sr in stats_rows:
                    table_name = metric_to_table.get(sr["metric"])
                    if table_name:
                        precomputed_counts[table_name] = sr["value"]
            except Exception:
                pass  # stats_overall may not exist; fall back to live COUNT

            # 获取所有表
            result = conn.execute(
                "SELECT name, type FROM sqlite_master WHERE type IN ('table', 'view') "
                "AND name NOT LIKE 'sqlite_%' ORDER BY type, name"
            ).fetchall()

            for row in result:
                name = row["name"]
                is_view = row["type"] == "view"

                # 获取列信息
                cols = conn.execute(f"PRAGMA table_info('{name}')").fetchall()
                columns = [
                    {
                        "name": c["name"],
                        "type": c["type"],
                        "notnull": bool(c["notnull"]),
                        "pk": bool(c["pk"]),
                    }
                    for c in cols
                ]

                # 行数 — use precomputed counts for large tables, skip views/FTS/stats
                count = 0
                if not is_view and not name.startswith("fts_") and not name.startswith("stats_"):
                    if name in precomputed_counts:
                        count = precomputed_counts[name]
                    else:
                        try:
                            count = conn.execute(f"SELECT COUNT(*) as cnt FROM [{name}]").fetchone()["cnt"]
                        except Exception:
                            count = 0

                tables[name] = {
                    "columns": columns,
                    "column_names": [c["name"] for c in columns],
                    "record_count": count,
                    "is_view": is_view,
                }

        finally:
            self._dal._release_connection(conn)

        # 外键关系
        relationships = {
            "unified_series.project_pk": "unified_projects.pk",
            "unified_samples.series_pk": "unified_series.pk",
            "unified_samples.project_pk": "unified_projects.pk",
            "unified_celltypes.sample_pk": "unified_samples.pk",
        }

        self._cache = {
            "tables": tables,
            "relationships": relationships,
            "total_tables": len([t for t in tables if not tables[t]["is_view"]]),
            "total_views": len([t for t in tables if tables[t]["is_view"]]),
        }
        self._analyzed = True
        elapsed = (time.perf_counter() - t0) * 1000
        logger.info("Schema analysis complete in %.0fms: %d tables, %d views",
                     elapsed, self._cache["total_tables"], self._cache["total_views"])
        return self._cache

    def get_summary(self) -> dict:
        """
        返回精简的schema摘要 (用于LLM prompt注入)
        """
        schema = self.analyze()
        summary = {"tables": {}, "views": []}

        for name, info in schema["tables"].items():
            if info["is_view"]:
                summary["views"].append(name)
            else:
                summary["tables"][name] = {
                    "record_count": info["record_count"],
                    "columns": info["column_names"],
                }

        # 添加关键统计
        tables = schema["tables"]
        summary["stats"] = {
            "total_projects": tables.get("unified_projects", {}).get("record_count", 0),
            "total_series": tables.get("unified_series", {}).get("record_count", 0),
            "total_samples": tables.get("unified_samples", {}).get("record_count", 0),
            "total_celltypes": tables.get("unified_celltypes", {}).get("record_count", 0),
            "total_entity_links": tables.get("entity_links", {}).get("record_count", 0),
            "total_id_mappings": tables.get("id_mappings", {}).get("record_count", 0),
        }

        return summary

    def get_field_stats(
        self, table: str, field: str, top_n: int = 20
    ) -> FieldStats:
        """获取字段统计"""
        cache_key = f"{table}.{field}.{top_n}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        conn = self._dal._get_connection()
        try:
            # 总数和非空数
            row = conn.execute(f"""
                SELECT COUNT(*) as total,
                       COUNT([{field}]) as non_null,
                       COUNT(DISTINCT [{field}]) as distinct_count
                FROM [{table}]
            """).fetchone()

            total = row["total"]
            non_null = row["non_null"]
            distinct = row["distinct_count"]
            null_pct = round((total - non_null) / total * 100, 1) if total > 0 else 0

            # Top N 值
            top_rows = conn.execute(f"""
                SELECT [{field}] as val, COUNT(*) as cnt
                FROM [{table}]
                WHERE [{field}] IS NOT NULL
                GROUP BY [{field}]
                ORDER BY cnt DESC
                LIMIT ?
            """, [top_n]).fetchall()

            top_values = [(r["val"], r["cnt"]) for r in top_rows]

            stats = FieldStats(
                table_name=table,
                field_name=field,
                total_count=total,
                non_null_count=non_null,
                null_pct=null_pct,
                distinct_count=distinct,
                top_values=top_values,
            )
            self._cache[cache_key] = stats
            return stats

        finally:
            self._dal._release_connection(conn)

    def get_ddl_summary(self) -> str:
        """
        生成精简的DDL摘要 (用于LLM SQL生成 prompt)
        """
        schema = self.analyze()
        lines = ["-- Unified Single-Cell Metadata Database Schema"]

        for name, info in schema["tables"].items():
            if info["is_view"]:
                continue
            cols = ", ".join(
                f"{c['name']} {c['type']}" + (" PK" if c["pk"] else "")
                for c in info["columns"][:15]  # 最多15个字段
            )
            lines.append(f"-- {name} ({info['record_count']:,} rows)")
            lines.append(f"CREATE TABLE {name} ({cols});")
            lines.append("")

        lines.append("-- Key relationships:")
        for fk, pk in schema["relationships"].items():
            lines.append(f"--   {fk} → {pk}")

        lines.append("")
        lines.append("-- View: v_sample_with_hierarchy")
        lines.append("-- Joins: unified_samples + unified_series + unified_projects")

        return "\n".join(lines)
