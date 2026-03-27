"""
Cross-Database Fusion Engine

跨库结果融合:
1. 硬链接去重 (entity_links)
2. Identity Hash去重 (biological_identity_hash)
3. 多源证据聚合
4. 质量评分
"""

from __future__ import annotations

import logging
from collections import defaultdict

from ..core.models import FusedRecord
from ..dal.database import DatabaseAbstractionLayer

logger = logging.getLogger(__name__)


# 数据源质量优先级 (越小越优)
SOURCE_QUALITY_RANK: dict[str, int] = {
    "cellxgene": 1,
    "ebi": 2,
    "ncbi": 3,
    "geo": 4,
    "hca": 5,
    "htan": 6,
    "ega": 7,
    "psychad": 8,
    "biscp": 9,
    "kpmp": 10,
    "zenodo": 11,
    "figshare": 12,
}

# 质量评分关键字段
QUALITY_FIELDS = ["tissue", "disease", "sex", "age", "organism", "assay", "n_cells", "pmid"]


class UnionFind:
    """Union-Find (Disjoint Set) for grouping linked entities."""

    def __init__(self):
        self._parent: dict[int, int] = {}
        self._rank: dict[int, int] = {}

    def find(self, x: int) -> int:
        if x not in self._parent:
            self._parent[x] = x
            self._rank[x] = 0
        if self._parent[x] != x:
            self._parent[x] = self.find(self._parent[x])
        return self._parent[x]

    def union(self, x: int, y: int):
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        if self._rank[rx] < self._rank[ry]:
            rx, ry = ry, rx
        self._parent[ry] = rx
        if self._rank[rx] == self._rank[ry]:
            self._rank[rx] += 1


class CrossDBFusionEngine:
    """跨库结果融合引擎"""

    def __init__(self, dal: DatabaseAbstractionLayer):
        self.dal = dal

    def fuse(
        self,
        results: list[dict],
        entity_type: str = "sample",
    ) -> list[FusedRecord]:
        """融合查询结果"""
        if not results:
            return []

        # 单源结果无需融合
        sources = set(r.get("source_database") or r.get("sample_source", "") for r in results)
        if len(sources) <= 1:
            return [self._single_record(r) for r in results]

        # Step 1: 硬链接去重
        groups = self._group_by_hard_links(results, entity_type)

        # Step 2: Identity Hash去重
        groups = self._merge_by_hash(groups)

        # Step 3: 多源聚合 + Step 4: 质量评分
        fused = []
        for group in groups:
            record = self._aggregate_group(group)
            record.quality_score = self._compute_quality(record)
            fused.append(record)

        fused.sort(key=lambda r: r.quality_score, reverse=True)
        return fused

    def _single_record(self, row: dict) -> FusedRecord:
        """单条记录包装"""
        src = row.get("source_database") or row.get("sample_source", "unknown")
        record = FusedRecord(
            data=dict(row),
            sources=[src],
            source_count=1,
            records_merged=1,
        )
        record.quality_score = self._compute_quality(record)
        return record

    def _group_by_hard_links(
        self, results: list[dict], entity_type: str,
    ) -> list[list[dict]]:
        """利用entity_links去重"""
        pks = [r.get("pk") or r.get("sample_pk") or r.get("project_pk") for r in results]
        pks = [p for p in pks if p is not None]

        if not pks:
            return [[r] for r in results]

        # 批量查询entity_links
        uf = UnionFind()
        BATCH = 500
        for i in range(0, len(pks), BATCH):
            batch = pks[i:i + BATCH]
            placeholders = ",".join("?" * len(batch))
            try:
                links = self.dal.execute(f"""
                    SELECT source_pk, target_pk FROM entity_links
                    WHERE source_entity_type = ?
                      AND relationship_type = 'same_as'
                      AND (source_pk IN ({placeholders}) OR target_pk IN ({placeholders}))
                """, [entity_type] + batch + batch)

                for link in links.rows:
                    sp, tp = link["source_pk"], link["target_pk"]
                    if sp in set(pks) and tp in set(pks):
                        uf.union(sp, tp)
            except Exception as e:
                logger.debug("entity_links query failed: %s", e)

        # 按组分配
        group_map: dict[int, list[dict]] = defaultdict(list)
        for r in results:
            pk = r.get("pk") or r.get("sample_pk") or r.get("project_pk") or id(r)
            root = uf.find(pk)
            group_map[root].append(r)

        return list(group_map.values())

    def _merge_by_hash(self, groups: list[list[dict]]) -> list[list[dict]]:
        """利用biological_identity_hash进一步合并"""
        hash_to_group: dict[str, int] = {}
        merged_groups: list[list[dict]] = []

        for group in groups:
            # 取组内第一个有hash的记录
            h = None
            for r in group:
                h = r.get("biological_identity_hash")
                if h:
                    break

            if h and h in hash_to_group:
                # 合并到已有组
                idx = hash_to_group[h]
                merged_groups[idx].extend(group)
            else:
                idx = len(merged_groups)
                merged_groups.append(group)
                if h:
                    hash_to_group[h] = idx

        return merged_groups

    def _aggregate_group(self, group: list[dict]) -> FusedRecord:
        """多源聚合"""
        # 按源质量排序
        sorted_group = sorted(
            group,
            key=lambda r: SOURCE_QUALITY_RANK.get(
                r.get("source_database") or r.get("sample_source", ""), 99
            ),
        )

        best = dict(sorted_group[0])
        sources = []
        all_ids: dict[str, list[str]] = defaultdict(list)

        for record in sorted_group:
            db = record.get("source_database") or record.get("sample_source", "unknown")
            sources.append(db)

            # 收集所有ID
            for id_field in ["project_id", "series_id", "sample_id", "pmid", "doi"]:
                val = record.get(id_field)
                if val:
                    all_ids[id_field].append(f"{val} ({db})")

            # 填充空字段
            for field, value in record.items():
                if value is not None and not best.get(field):
                    best[field] = value

        # 取最大citation
        best["citation_count"] = max(
            (r.get("citation_count") or 0 for r in sorted_group), default=0
        )

        return FusedRecord(
            data=best,
            sources=sources,
            source_count=len(set(sources)),
            all_ids=dict(all_ids),
            records_merged=len(group),
        )

    def _compute_quality(self, record: FusedRecord) -> float:
        """综合质量评分 (0-100)"""
        score = 0.0

        # 1. 元数据完整性 (40分)
        filled = sum(1 for f in QUALITY_FIELDS if record.data.get(f))
        score += (filled / len(QUALITY_FIELDS)) * 40

        # 2. 跨库验证 (25分)
        score += min(record.source_count / 3, 1.0) * 25

        # 3. 数据可获取性 (20分)
        if record.data.get("has_h5ad"):
            score += 20
        elif record.data.get("has_rds"):
            score += 15
        elif record.data.get("access_url") or record.data.get("explorer_url"):
            score += 10

        # 4. 引用影响力 (15分)
        citations = record.data.get("citation_count") or 0
        score += min(citations / 100, 1.0) * 15

        return round(score, 1)
