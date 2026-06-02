"""
QueryFeedbackLoop — 查询执行反馈循环

职责:
1. 记录查询执行情况 (估计 vs 实际)
2. 校正估计模型
3. 识别查询模式，优化未来生成
4. 提供相似查询的历史参考
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class QueryFeedbackLoop:
    """查询执行反馈循环"""

    def __init__(self, db_path: str | Path):
        p = Path(db_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(p), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS query_execution_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query_pattern TEXT NOT NULL,
                sql_template TEXT NOT NULL,
                estimated_rows INTEGER DEFAULT 0,
                actual_rows INTEGER DEFAULT 0,
                estimation_error REAL DEFAULT 0.0,
                execution_time_ms REAL DEFAULT 0.0,
                filters_used TEXT,
                intent TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_qel_pattern
                ON query_execution_log(query_pattern);
            CREATE INDEX IF NOT EXISTS idx_qel_created
                ON query_execution_log(created_at);

            CREATE TABLE IF NOT EXISTS estimation_correction (
                field_pattern TEXT PRIMARY KEY,
                correction_factor REAL DEFAULT 1.0,
                sample_count INTEGER DEFAULT 0,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        self.conn.commit()

    def record_execution(
        self,
        query_pattern: str,
        sql: str,
        estimated_rows: int,
        actual_rows: int,
        execution_time_ms: float,
        filters_used: dict | None = None,
        intent: str = "",
    ) -> int:
        """记录查询执行结果，返回记录ID"""
        estimation_error = (
            abs(estimated_rows - actual_rows) / max(actual_rows, 1)
            if actual_rows > 0 else 0.0
        )

        cursor = self.conn.execute(
            """INSERT INTO query_execution_log
               (query_pattern, sql_template, estimated_rows, actual_rows,
                estimation_error, execution_time_ms, filters_used, intent)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                query_pattern,
                sql[:500],
                estimated_rows,
                actual_rows,
                estimation_error,
                execution_time_ms,
                json.dumps(filters_used or {}),
                intent,
            ),
        )
        self.conn.commit()

        # 触发校正因子更新
        if filters_used and actual_rows > 0:
            self._update_correction_factors(filters_used, estimated_rows, actual_rows)

        return cursor.lastrowid

    def get_correction_factor(self, field: str, value: str) -> float:
        """获取特定字段值的校正因子"""
        pattern = f"{field}.{value}"
        cursor = self.conn.execute(
            "SELECT correction_factor FROM estimation_correction WHERE field_pattern = ?",
            (pattern,),
        )
        row = cursor.fetchone()
        return row["correction_factor"] if row else 1.0

    def get_similar_query_stats(self, query_pattern: str, days: int = 7) -> dict[str, Any]:
        """获取相似历史查询的统计"""
        cursor = self.conn.execute(
            f"""SELECT
                AVG(actual_rows) as avg_rows,
                AVG(execution_time_ms) as avg_time,
                AVG(estimation_error) as avg_error,
                COUNT(*) as sample_count,
                MAX(actual_rows) as max_rows,
                MIN(actual_rows) as min_rows
            FROM query_execution_log
            WHERE query_pattern LIKE ?
            AND created_at > datetime('now', '-{days} days')""",
            (query_pattern.replace("X", "%"),),
        )
        row = cursor.fetchone()
        if not row or row["sample_count"] == 0:
            return {"found": False}

        return {
            "found": True,
            "avg_rows": int(row["avg_rows"] or 0),
            "avg_time_ms": round(row["avg_time"] or 0, 2),
            "avg_estimation_error": round(row["avg_error"] or 0, 2),
            "sample_count": row["sample_count"],
        }

    def get_slow_queries(self, threshold_ms: float = 1000.0, limit: int = 10) -> list[dict]:
        """获取慢查询列表"""
        cursor = self.conn.execute(
            """SELECT query_pattern, AVG(execution_time_ms) as avg_time,
                      COUNT(*) as execution_count
            FROM query_execution_log
            WHERE execution_time_ms > ?
            AND created_at > datetime('now', '-7 days')
            GROUP BY query_pattern
            ORDER BY avg_time DESC
            LIMIT ?""",
            (threshold_ms, limit),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_record_count(self) -> int:
        cursor = self.conn.execute("SELECT COUNT(*) as cnt FROM query_execution_log")
        return cursor.fetchone()["cnt"]

    def cleanup_old_records(self, days: int = 30):
        self.conn.execute(
            f"DELETE FROM query_execution_log WHERE created_at < datetime('now', '-{days} days')"
        )
        self.conn.commit()

    def _update_correction_factors(
        self, filters_used: dict, estimated: int, actual: int
    ):
        """更新估计校正因子 (指数移动平均)"""
        if actual == 0:
            return
        factor = actual / max(estimated, 1)

        field_patterns = []
        for field, values in filters_used.items():
            if isinstance(values, list):
                for v in values:
                    field_patterns.append(f"{field}.{v}")
            elif values:
                field_patterns.append(f"{field}.{values}")

        for fp in field_patterns:
            self.conn.execute(
                """INSERT INTO estimation_correction (field_pattern, correction_factor, sample_count)
                   VALUES (?, ?, 1)
                   ON CONFLICT(field_pattern) DO UPDATE SET
                   correction_factor = (
                       estimation_correction.correction_factor * estimation_correction.sample_count + ?
                   ) / (estimation_correction.sample_count + 1),
                   sample_count = estimation_correction.sample_count + 1,
                   last_updated = datetime('now')""",
                (fp, factor, factor),
            )
        self.conn.commit()
