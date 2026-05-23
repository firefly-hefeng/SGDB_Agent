"""
SchemaConfig — 数据库结构的抽象描述层

从 SchemaInspector 动态发现表结构、字段类型、外键关系，
为 SQL 生成器、验证器、JOIN 解析器提供统一的结构描述。

设计原则:
- 所有表名/字段名从数据库动态获取，不硬编码
- 通过语义标注 (semantic_type) 将物理字段映射到逻辑含义
- 数据库结构变化后只需 rebuild() 即可适配
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# 默认语义映射规则 — 按字段名关键词推断语义类型
# 可通过 SchemaConfig 构造参数覆盖
_DEFAULT_SEMANTIC_RULES: dict[str, str] = {
    "tissue": "tissue",
    "tissue_standard": "tissue",
    "tissue_normalized": "metadata",
    "tissue_system": "tissue_category",
    "tissue_general": "metadata",
    "tissue_type": "metadata",
    "disease": "disease",
    "disease_standard": "disease",
    "disease_normalized": "metadata",
    "disease_category": "disease_category",
    "disease_is_composite": "metadata",
    "organism": "organism",
    "organism_normalized": "organism",
    "organism_common": "organism",
    "sex": "sex",
    "sex_normalized": "sex",
    "assay": "assay",
    "source_database": "source",
    "cell_type": "cell_type",
    "cell_type_name": "cell_type",
    "sample_type": "sample_type",
    "sample_source_type": "metadata",
    "tissue_ontology_term_id": "ontology_id",
    "disease_ontology_term_id": "ontology_id",
    "sex_ontology_term_id": "ontology_id",
    "development_stage_ontology_term_id": "ontology_id",
    "ethnicity_ontology_term_id": "ontology_id",
    "cell_type_ontology_term_id": "ontology_id",
    "assay_ontology_term_id": "ontology_id",
    "n_cells": "metric",
    "n_cell_types": "metric",
    "cell_count": "metric",
    "citation_count": "metric",
    "pk": "id",
    "sample_id": "id",
    "series_id": "id",
    "project_id": "id",
    "pmid": "id",
    "doi": "id",
    "title": "text",
    "summary": "text",
    "abstract": "text",
    "description": "text",
}


@dataclass
class FieldInfo:
    """字段元信息"""
    name: str
    data_type: str
    table: str
    nullable: bool = True
    is_pk: bool = False
    semantic_type: str = "metadata"  # tissue, disease, cell_type, organism, id, metric, text, metadata


@dataclass
class TableInfo:
    """表元信息"""
    name: str
    is_view: bool = False
    row_count: int = 0
    fields: dict[str, FieldInfo] = field(default_factory=dict)
    field_names: list[str] = field(default_factory=list)


@dataclass
class ForeignKey:
    """外键关系"""
    from_table: str
    from_field: str
    to_table: str
    to_field: str


class SchemaConfig:
    """
    数据库结构抽象层 — 从 SchemaInspector 动态构建。

    提供:
    - tables: 所有表/视图的元信息
    - core_fields: 可过滤的核心字段列表 (tissue, disease, ...)
    - field_to_table: 字段→所在表的映射
    - foreign_keys: 外键关系
    - view_fields: 视图中包含的字段集合
    - join_rules: 表间 JOIN 规则
    """

    def __init__(
        self,
        schema_data: dict[str, Any] | None = None,
        *,
        semantic_rules: dict[str, str] | None = None,
        main_table: str = "unified_samples",
        main_view: str | None = None,
    ):
        self.semantic_rules = semantic_rules or _DEFAULT_SEMANTIC_RULES
        self.main_table = main_table
        self.main_view = main_view

        # Core data structures
        self.tables: dict[str, TableInfo] = {}
        self.foreign_keys: list[ForeignKey] = []
        self.field_to_table: dict[str, str] = {}
        self.view_fields: set[str] = set()
        self._core_fields: list[str] | None = None

        if schema_data:
            self._build(schema_data)

    @classmethod
    def from_dal(cls, dal, **kwargs) -> SchemaConfig:
        """从 DAL 的 SchemaInspector 动态构建。"""
        schema_data = dal.schema_inspector.analyze()
        config = cls(schema_data, **kwargs)

        # 自动发现主视图
        if config.main_view is None:
            for name, info in config.tables.items():
                if info.is_view and "sample" in name.lower():
                    config.main_view = name
                    config.view_fields = set(info.field_names)
                    logger.info("Auto-detected main view: %s (%d fields)",
                                name, len(info.field_names))
                    break

        return config

    def _build(self, schema_data: dict[str, Any]):
        """从 SchemaInspector.analyze() 结果构建配置。"""
        tables_data = schema_data.get("tables", {})
        relationships = schema_data.get("relationships", {})

        # 构建表信息
        for table_name, info in tables_data.items():
            columns = info.get("columns", [])
            fields = {}
            field_names = []
            for col in columns:
                name = col["name"]
                fi = FieldInfo(
                    name=name,
                    data_type=col.get("type", "TEXT"),
                    table=table_name,
                    nullable=not col.get("notnull", False),
                    is_pk=col.get("pk", False),
                    semantic_type=self._infer_semantic_type(name),
                )
                fields[name] = fi
                field_names.append(name)

            ti = TableInfo(
                name=table_name,
                is_view=info.get("is_view", False),
                row_count=info.get("record_count", 0),
                fields=fields,
                field_names=field_names,
            )
            self.tables[table_name] = ti

            # 视图字段
            if ti.is_view and "sample" in table_name.lower():
                self.view_fields = set(field_names)
                if self.main_view is None:
                    self.main_view = table_name

        # 构建字段→表映射 (主表优先)
        if self.main_table in self.tables:
            for fn in self.tables[self.main_table].field_names:
                self.field_to_table[fn] = self.main_table

        for table_name, ti in self.tables.items():
            if table_name == self.main_table:
                continue
            for fn in ti.field_names:
                if fn not in self.field_to_table:
                    self.field_to_table[fn] = table_name

        # 构建外键
        for fk_str, ref_str in relationships.items():
            parts = fk_str.split(".")
            ref_parts = ref_str.split(".")
            if len(parts) == 2 and len(ref_parts) == 2:
                self.foreign_keys.append(ForeignKey(
                    from_table=parts[0], from_field=parts[1],
                    to_table=ref_parts[0], to_field=ref_parts[1],
                ))

    def _infer_semantic_type(self, field_name: str) -> str:
        """通过字段名推断语义类型。优先精确匹配，再进行模糊匹配。"""
        name_lower = field_name.lower()
        # Exact match first
        if name_lower in self.semantic_rules:
            return self.semantic_rules[name_lower]
        # Substring match (shorter patterns matched after longer ones)
        for pattern, sem_type in sorted(self.semantic_rules.items(), key=lambda x: -len(x[0])):
            if pattern in name_lower:
                return sem_type
        return "metadata"

    # ── Public API ──

    @property
    def core_fields(self) -> list[str]:
        """可过滤的核心字段 — 自动发现 semantic_type 为生物学维度的字段。"""
        if self._core_fields is not None:
            return self._core_fields

        semantic_filter_types = {"tissue", "disease", "organism", "source", "assay", "sex",
                                  "tissue_category", "disease_category", "sample_type"}
        if self.main_table not in self.tables:
            return []

        fields = []
        for fn, fi in self.tables[self.main_table].fields.items():
            if fi.semantic_type in semantic_filter_types:
                fields.append(fn)
        self._core_fields = fields
        return fields

    @core_fields.setter
    def core_fields(self, value: list[str]):
        """手动覆盖核心字段列表。"""
        self._core_fields = value

    def get_table_names(self, include_views: bool = False) -> list[str]:
        """获取所有表名。"""
        return [
            name for name, ti in self.tables.items()
            if include_views or not ti.is_view
        ]

    def get_all_field_names(self, table: str | None = None) -> set[str]:
        """获取指定表（或所有表）的字段集合。"""
        if table:
            ti = self.tables.get(table)
            return set(ti.field_names) if ti else set()
        return set(self.field_to_table.keys())

    def get_known_tables_and_fields(self) -> tuple[set[str], dict[str, set[str]]]:
        """返回 (known_tables, {table: fields}) — 供 SQLValidator 使用。"""
        known_tables = set(self.tables.keys())
        known_fields = {
            name: set(ti.field_names)
            for name, ti in self.tables.items()
        }
        return known_tables, known_fields

    def get_join_path(self, from_table: str, to_table: str) -> list[ForeignKey] | None:
        """通过外键关系查找两表间的 JOIN 路径 (BFS)。"""
        if from_table == to_table:
            return []

        # Build adjacency list
        adj: dict[str, list[ForeignKey]] = {}
        for fk in self.foreign_keys:
            adj.setdefault(fk.from_table, []).append(fk)
            # Reverse direction
            adj.setdefault(fk.to_table, []).append(ForeignKey(
                from_table=fk.to_table, from_field=fk.to_field,
                to_table=fk.from_table, to_field=fk.from_field,
            ))

        # BFS
        from collections import deque
        queue = deque([(from_table, [])])
        visited = {from_table}

        while queue:
            current, path = queue.popleft()
            for fk in adj.get(current, []):
                next_table = fk.to_table
                if next_table in visited:
                    continue
                new_path = path + [fk]
                if next_table == to_table:
                    return new_path
                visited.add(next_table)
                queue.append((next_table, new_path))

        return None  # No path found

    def get_celltype_config(self) -> dict[str, str]:
        """
        自动发现 CellType 子表配置。

        返回: {"table": "unified_celltypes", "fk_field": "sample_pk", "name_field": "cell_type_name"}
        如果找不到，返回空字典。
        """
        for fk in self.foreign_keys:
            if "celltype" in fk.from_table.lower() or "cell_type" in fk.from_table.lower():
                # Find the name field in the celltype table
                ct_table = self.tables.get(fk.from_table)
                if not ct_table:
                    continue
                name_field = None
                for fn, fi in ct_table.fields.items():
                    if fi.semantic_type == "cell_type":
                        name_field = fn
                        break
                if name_field:
                    return {
                        "table": fk.from_table,
                        "fk_field": fk.from_field,
                        "name_field": name_field,
                    }
        return {}

    def can_use_view(self, needed_fields: set[str]) -> bool:
        """检查是否所有需要的字段都在主视图中。"""
        if not self.main_view or not self.view_fields:
            return False
        return needed_fields.issubset(self.view_fields)

    def rebuild(self, schema_data: dict[str, Any]):
        """数据库结构变化后重建配置。"""
        self.tables.clear()
        self.foreign_keys.clear()
        self.field_to_table.clear()
        self.view_fields.clear()
        self._core_fields = None
        self._build(schema_data)
        logger.info("SchemaConfig rebuilt: %d tables, %d FKs, %d core fields",
                     len(self.tables), len(self.foreign_keys), len(self.core_fields))
