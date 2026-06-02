"""
DataStatsAnalyzer — 数据分布分析器

职责:
1. 收集和维护字段级统计信息 (Cardinality, NULL率, 直方图)
2. 提供选择性估计
3. 多级缓存管理 (L1内存 + L2 SQLite)
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from typing import Optional

from ..dal.database import DatabaseAbstractionLayer
from .models import FieldStats, SelectivityEstimate

logger = logging.getLogger(__name__)


class DataStatsAnalyzer:
    """数据分布分析器 — 带多级缓存"""

    CACHE_TTL_SECONDS = 1800  # 30分钟
    HISTOGRAM_TOP_N = 20

    # 语义类型推断映射
    _SEMANTIC_MAP = {
        "tissue": ["tissue", "tissue_type", "tissue_general"],
        "disease": ["disease", "condition", "diagnosis"],
        "cell_type": ["cell_type", "celltype", "cell_type_name"],
        "organism": ["organism", "species"],
        "id": ["_id", "_pk", "uuid", "sample_id", "project_id", "series_id"],
        "metric": ["n_cells", "cell_count", "gene_count", "citation_count"],
    }

    # 语义类型默认选择性
    _DEFAULT_SELECTIVITY = {
        "tissue": 0.05,
        "disease": 0.1,
        "cell_type": 0.08,
        "organism": 0.9,
        "id": 0.0001,
        "metric": 0.5,
        "metadata": 0.3,
    }

    def __init__(self, dal: DatabaseAbstractionLayer, cache_db_path: Optional[str] = None):
        self.dal = dal
        self._memory_cache: dict[str, FieldStats] = {}
        self._cache_timestamps: dict[str, float] = {}
        self._table_row_counts: dict[str, int] = {}

        # L2: 可选持久化缓存
        self._cache_conn: Optional[sqlite3.Connection] = None
        if cache_db_path:
            self._cache_conn = sqlite3.connect(cache_db_path, check_same_thread=False)
            self._cache_conn.row_factory = sqlite3.Row
            self._init_cache_tables()

    def _init_cache_tables(self):
        if not self._cache_conn:
            return
        self._cache_conn.execute("""
            CREATE TABLE IF NOT EXISTS field_stats_cache (
                table_name TEXT,
                field_name TEXT,
                stats_json TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (table_name, field_name)
            )
        """)
        self._cache_conn.commit()

    # ── Public API ──

    async def get_field_stats(self, table: str, field: str) -> Optional[FieldStats]:
        """获取字段统计 (带多级缓存)"""
        cache_key = f"{table}.{field}"
        now = time.time()

        # L1: 内存缓存
        if cache_key in self._memory_cache:
            ts = self._cache_timestamps.get(cache_key, 0)
            if now - ts < self.CACHE_TTL_SECONDS:
                return self._memory_cache[cache_key]

        # L2: 持久化缓存
        cached = self._load_from_persistent_cache(table, field)
        if cached:
            self._memory_cache[cache_key] = cached
            self._cache_timestamps[cache_key] = now
            return cached

        # L3: 实时计算
        stats = self._compute_field_stats(table, field)
        if stats:
            self._update_cache(cache_key, stats)
        return stats

    async def get_table_row_count(self, table: str) -> int:
        """获取表总行数 (缓存)"""
        if table not in self._table_row_counts:
            try:
                result = self.dal.execute(f"SELECT COUNT(*) as cnt FROM [{table}]")
                self._table_row_counts[table] = result.rows[0]["cnt"] if result.rows else 0
            except Exception:
                self._table_row_counts[table] = 0
        return self._table_row_counts[table]

    async def estimate_selectivity(
        self, table: str, field: str, pattern: str, operator: str = "LIKE"
    ) -> SelectivityEstimate:
        """
        估计条件选择性

        策略:
        1. 精确匹配直方图 → 直接计算
        2. 前缀匹配 → 累加直方图前缀匹配项
        3. 模糊匹配 → 基于语义类型默认估计
        """
        stats = await self.get_field_stats(table, field)
        if not stats:
            return SelectivityEstimate(
                table=table, field=field, pattern=pattern,
                estimated_selectivity=0.5, confidence=0.3, based_on="default",
            )

        pattern_lower = pattern.lower().strip("%")

        # 策略1: 精确匹配
        for value, count in stats.histogram:
            if value and str(value).lower() == pattern_lower:
                sel = count / stats.total_count if stats.total_count > 0 else 0.5
                return SelectivityEstimate(
                    table=table, field=field, pattern=pattern,
                    estimated_selectivity=sel, confidence=0.95,
                    based_on="histogram_exact",
                )

        # 策略2: 前缀/包含匹配
        matching_count = sum(
            count for value, count in stats.histogram
            if value and pattern_lower in str(value).lower()
        )
        if matching_count > 0:
            sel = matching_count / stats.total_count if stats.total_count > 0 else 0.5
            return SelectivityEstimate(
                table=table, field=field, pattern=pattern,
                estimated_selectivity=sel, confidence=0.8,
                based_on="histogram_prefix",
            )

        # 策略3: 语义类型默认
        default_sel = self._DEFAULT_SELECTIVITY.get(stats.semantic_type, 0.3)
        histogram_coverage = (
            sum(c for _, c in stats.histogram) / stats.total_count
            if stats.total_count > 0 else 0
        )
        confidence = 0.5 * histogram_coverage

        return SelectivityEstimate(
            table=table, field=field, pattern=pattern,
            estimated_selectivity=default_sel, confidence=max(0.1, confidence),
            based_on="semantic_default",
        )

    async def invalidate_cache(self, table: Optional[str] = None):
        """使缓存失效"""
        if table:
            keys = [k for k in self._memory_cache if k.startswith(f"{table}.")]
            for k in keys:
                del self._memory_cache[k]
                self._cache_timestamps.pop(k, None)
            self._table_row_counts.pop(table, None)
        else:
            self._memory_cache.clear()
            self._cache_timestamps.clear()
            self._table_row_counts.clear()

    # ── Internal ──

    def _compute_field_stats(self, table: str, field: str) -> Optional[FieldStats]:
        """计算字段统计信息"""
        try:
            # 基础计数
            result = self.dal.execute(f"""
                SELECT COUNT(*) as total,
                       COUNT([{field}]) as non_null,
                       COUNT(DISTINCT [{field}]) as distinct_count
                FROM [{table}]
            """)
            if not result.rows:
                return None

            row = result.rows[0]
            total = row["total"]
            non_null = row["non_null"]
            distinct = row["distinct_count"]
            null_pct = round((total - non_null) / total * 100, 1) if total > 0 else 0
            selectivity = distinct / total if total > 0 else 1.0

            # 直方图 Top-N
            histogram = self._compute_histogram(table, field)

            # 数值范围 (尝试)
            min_val, max_val, avg_val = None, None, 0.0
            try:
                range_result = self.dal.execute(f"""
                    SELECT MIN([{field}]) as min_val,
                           MAX([{field}]) as max_val,
                           AVG(CAST([{field}] AS REAL)) as avg_val
                    FROM [{table}] WHERE [{field}] IS NOT NULL
                """)
                if range_result.rows:
                    r = range_result.rows[0]
                    min_val = r.get("min_val")
                    max_val = r.get("max_val")
                    avg_val = r.get("avg_val") or 0.0
            except Exception:
                pass

            # 推断语义类型和数据类型
            semantic_type = self._infer_semantic_type(field)
            data_type = self._get_data_type(table, field)

            return FieldStats(
                field_name=field,
                table_name=table,
                data_type=data_type,
                semantic_type=semantic_type,
                total_count=total,
                non_null_count=non_null,
                null_pct=null_pct,
                distinct_count=distinct,
                histogram=histogram,
                min_value=min_val,
                max_value=max_val,
                avg_value=avg_val,
                selectivity=selectivity,
                sample_size=total,
            )
        except Exception as e:
            logger.error("Failed to compute stats for %s.%s: %s", table, field, e)
            return None

    def _compute_histogram(self, table: str, field: str) -> list[tuple[str, int]]:
        try:
            result = self.dal.execute(f"""
                SELECT [{field}] as value, COUNT(*) as cnt
                FROM [{table}]
                WHERE [{field}] IS NOT NULL
                GROUP BY [{field}]
                ORDER BY cnt DESC
                LIMIT {self.HISTOGRAM_TOP_N}
            """)
            return [(str(r["value"]), r["cnt"]) for r in result.rows if r["value"]]
        except Exception as e:
            logger.warning("Failed to compute histogram for %s.%s: %s", table, field, e)
            return []

    def _infer_semantic_type(self, field: str) -> str:
        field_lower = field.lower()
        for sem_type, patterns in self._SEMANTIC_MAP.items():
            if any(p in field_lower for p in patterns):
                return sem_type
        return "metadata"

    def _get_data_type(self, table: str, field: str) -> str:
        try:
            result = self.dal.execute(f"PRAGMA table_info([{table}])")
            for row in result.rows:
                if row.get("name") == field:
                    return row.get("type", "TEXT")
        except Exception:
            pass
        return "TEXT"

    def _update_cache(self, key: str, stats: FieldStats):
        self._memory_cache[key] = stats
        self._cache_timestamps[key] = time.time()

        if self._cache_conn:
            try:
                from dataclasses import asdict
                data = asdict(stats)
                # datetime不能直接JSON序列化
                data["last_updated"] = str(data["last_updated"])
                self._cache_conn.execute(
                    """INSERT OR REPLACE INTO field_stats_cache
                       (table_name, field_name, stats_json, updated_at)
                       VALUES (?, ?, ?, datetime('now'))""",
                    (stats.table_name, stats.field_name, json.dumps(data, default=str)),
                )
                self._cache_conn.commit()
            except Exception as e:
                logger.warning("Failed to persist stats cache: %s", e)

    def _load_from_persistent_cache(self, table: str, field: str) -> Optional[FieldStats]:
        if not self._cache_conn:
            return None
        try:
            cursor = self._cache_conn.execute(
                """SELECT stats_json FROM field_stats_cache
                   WHERE table_name = ? AND field_name = ?
                   AND updated_at > datetime('now', '-1 hour')""",
                (table, field),
            )
            row = cursor.fetchone()
            if row:
                data = json.loads(row["stats_json"])
                # 恢复 histogram 为 tuple list
                data.pop("last_updated", None)
                data["histogram"] = [tuple(h) for h in data.get("histogram", [])]
                return FieldStats(**data)
        except Exception as e:
            logger.warning("Failed to load from persistent cache: %s", e)
        return None
