"""
缓存系统

三层缓存:
- L1: Working Memory (内存LRU, 会话级)
- L2: SQL结果缓存 (SQLite, 可持久化)
- L3: 本体缓存 (独立SQLite, 长期持久化)
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from collections import OrderedDict
from threading import Lock

logger = logging.getLogger(__name__)


class LRUCache:
    """线程安全的LRU缓存"""

    def __init__(self, capacity: int = 100):
        self.capacity = capacity
        self._cache: OrderedDict = OrderedDict()
        self._lock = Lock()
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> object | None:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                self._hits += 1
                return self._cache[key]
            self._misses += 1
            return None

    def set(self, key: str, value: object, ttl: int | None = None) -> None:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = value
            if len(self._cache) > self.capacity:
                self._cache.popitem(last=False)

    def delete(self, key: str) -> None:
        with self._lock:
            self._cache.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0

    @property
    def size(self) -> int:
        return len(self._cache)

    def stats(self) -> dict:
        return {
            "size": self.size,
            "capacity": self.capacity,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self.hit_rate, 3),
        }


class SQLResultCache:
    """
    SQL查询结果缓存 (SQLite-backed)

    支持TTL过期、分类管理、容量限制。
    """

    MAX_ENTRIES = 5000

    def __init__(self, db_path: str = ":memory:"):
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS query_cache (
                cache_key TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                result_json TEXT NOT NULL,
                row_count INTEGER,
                created_at REAL NOT NULL,
                ttl INTEGER NOT NULL,
                access_count INTEGER DEFAULT 1
            )
        """)
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cache_category ON query_cache(category)"
        )
        self._conn.commit()
        self._hits = 0
        self._misses = 0

    def get(self, cache_key: str) -> list[dict] | None:
        """获取缓存结果，如过期返回None"""
        row = self._conn.execute(
            "SELECT result_json, created_at, ttl FROM query_cache WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()

        if row is None:
            self._misses += 1
            return None

        result_json, created_at, ttl = row
        if time.time() - created_at > ttl:
            self._conn.execute("DELETE FROM query_cache WHERE cache_key = ?", (cache_key,))
            self._conn.commit()
            self._misses += 1
            return None

        self._conn.execute(
            "UPDATE query_cache SET access_count = access_count + 1 WHERE cache_key = ?",
            (cache_key,),
        )
        self._hits += 1
        return json.loads(result_json)

    def set(
        self,
        cache_key: str,
        results: list[dict],
        category: str = "search",
        ttl: int = 3600,
    ) -> None:
        """缓存查询结果"""
        # 容量检查
        count = self._conn.execute("SELECT COUNT(*) FROM query_cache").fetchone()[0]
        if count >= self.MAX_ENTRIES:
            # 删除最旧的20%
            self._conn.execute("""
                DELETE FROM query_cache WHERE cache_key IN (
                    SELECT cache_key FROM query_cache
                    ORDER BY created_at ASC LIMIT ?
                )
            """, (self.MAX_ENTRIES // 5,))

        self._conn.execute(
            """INSERT OR REPLACE INTO query_cache
               (cache_key, category, result_json, row_count, created_at, ttl)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (cache_key, category, json.dumps(results, default=str),
             len(results), time.time(), ttl),
        )
        self._conn.commit()

    def invalidate_category(self, category: str) -> int:
        """按类别失效"""
        cursor = self._conn.execute(
            "DELETE FROM query_cache WHERE category = ?", (category,)
        )
        self._conn.commit()
        return cursor.rowcount

    def stats(self) -> dict:
        total = self._hits + self._misses
        row = self._conn.execute(
            "SELECT COUNT(*), SUM(row_count) FROM query_cache"
        ).fetchone()
        return {
            "entries": row[0] or 0,
            "total_cached_rows": row[1] or 0,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total, 3) if total > 0 else 0.0,
        }

    @staticmethod
    def make_cache_key(sql: str, params: list | None = None) -> str:
        """生成缓存key"""
        content = sql + "|" + json.dumps(params or [], default=str)
        return hashlib.sha256(content.encode()).hexdigest()[:16]


class CacheSystem:
    """
    统一缓存管理器

    整合三层缓存，提供统一的get/set接口。
    """

    # 缓存类别→TTL映射
    DEFAULT_TTL = {
        "search": 3600,       # 1小时
        "stats": 21600,       # 6小时
        "schema": 86400,      # 24小时
        "ontology": 604800,   # 7天
    }

    def __init__(
        self,
        session_cache_size: int = 20,
        global_cache_size: int = 100,
        sql_cache_path: str = ":memory:",
    ):
        # L1: 内存缓存
        self.session_caches: dict[str, LRUCache] = {}
        self.global_cache = LRUCache(global_cache_size)
        self._session_cache_size = session_cache_size

        # L2: SQL结果缓存
        self.sql_cache = SQLResultCache(sql_cache_path)

    def get_session_cache(self, session_id: str) -> LRUCache:
        """获取/创建会话级缓存"""
        if session_id not in self.session_caches:
            self.session_caches[session_id] = LRUCache(self._session_cache_size)
        return self.session_caches[session_id]

    def cleanup_expired_sessions(self, max_age_seconds: int = 1800):
        """清理过期会话缓存"""
        # 简单策略: 如果缓存数量超过100个会话，清理最旧的
        if len(self.session_caches) > 100:
            oldest = sorted(self.session_caches.keys())[:50]
            for sid in oldest:
                del self.session_caches[sid]

    def stats(self) -> dict:
        return {
            "global_cache": self.global_cache.stats(),
            "sql_cache": self.sql_cache.stats(),
            "active_sessions": len(self.session_caches),
        }
