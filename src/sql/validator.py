"""
SQLValidator — SQL语法和语义验证器

检查项:
1. 基础语法检查
2. 表/字段存在性验证
3. SQL注入风险检测
4. 查询安全性保障 (只允许SELECT)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# 危险SQL模式
_DANGEROUS_PATTERNS = [
    re.compile(r";\s*DROP\s+", re.IGNORECASE),
    re.compile(r";\s*DELETE\s+FROM\s+", re.IGNORECASE),
    re.compile(r";\s*UPDATE\s+\w+\s+SET", re.IGNORECASE),
    re.compile(r";\s*INSERT\s+INTO", re.IGNORECASE),
    re.compile(r";\s*ALTER\s+", re.IGNORECASE),
    re.compile(r";\s*CREATE\s+", re.IGNORECASE),
    # Note: we deliberately allow "UNION ALL SELECT" since the engine uses
    # it for per-source stratification. Adversarial `UNION SELECT`-style
    # payloads are refused at parse time (see parser.py adversarial guard).
]


@dataclass
class SQLValidationResult:
    """验证结果"""
    is_valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class SQLValidator:
    """
    SQL语法和语义验证器

    轻量级实现，不依赖sqlparse (减少外部依赖)。
    优先从 SchemaConfig 动态获取表/字段信息，
    无 SchemaConfig 时回退到内置默认值。
    """

    # 内置默认值 — 仅在无 SchemaConfig 时使用
    _DEFAULT_TABLES = {
        "unified_projects", "unified_series", "unified_samples",
        "unified_celltypes", "entity_links", "id_mappings",
        "v_sample_with_hierarchy",
        "stats_overall", "stats_source_distribution",
        "stats_tissue_distribution", "stats_disease_distribution",
        "stats_organism_distribution", "stats_assay_distribution",
    }

    _DEFAULT_FIELDS = {
        "unified_samples": {
            "pk", "sample_id", "sample_id_type", "source_database",
            "organism", "tissue", "tissue_ontology_term_id", "tissue_general",
            "disease", "disease_ontology_term_id",
            "sex", "age", "age_unit", "development_stage", "ethnicity",
            "individual_id", "n_cells", "cell_type",
            "series_pk", "project_pk", "biological_identity_hash",
        },
        "unified_series": {
            "pk", "series_id", "source_database", "title", "assay",
            "has_h5ad", "has_rds", "cell_count", "gene_count",
            "asset_h5ad_url", "explorer_url", "project_pk",
        },
        "unified_projects": {
            "pk", "project_id", "source_database", "title",
            "pmid", "doi", "citation_count", "journal",
            "submitter_organization",
        },
        "unified_celltypes": {
            "pk", "sample_pk", "cell_type_name",
            "cell_type_ontology_term_id", "cell_count", "fraction",
        },
    }

    def __init__(self, dal=None, schema_config=None):
        self.dal = dal
        if schema_config is not None:
            tables, fields = schema_config.get_known_tables_and_fields()
            self._table_cache = set(tables)
            self._field_cache = {k: set(v) for k, v in fields.items()}
        else:
            self._table_cache = set(self._DEFAULT_TABLES)
            self._field_cache = dict(self._DEFAULT_FIELDS)

    def validate(self, sql: str, params: list | None = None) -> SQLValidationResult:
        """完整验证SQL"""
        errors = []
        warnings = []

        sql_stripped = sql.strip()

        # 1. 基础检查: 必须是SELECT
        if not sql_stripped.upper().startswith("SELECT"):
            errors.append("只允许SELECT查询")
            return SQLValidationResult(is_valid=False, errors=errors)

        # 2. 注入风险检测
        injection_error = self._check_injection(sql_stripped)
        if injection_error:
            errors.append(f"注入风险: {injection_error}")
            return SQLValidationResult(is_valid=False, errors=errors)

        # 3. 参数数量匹配
        if params is not None:
            expected = sql_stripped.count("?")
            actual = len(params)
            if expected != actual:
                errors.append(f"参数数量不匹配: SQL中有{expected}个?，提供了{actual}个参数")

        # 4. 表存在性检查
        tables = self._extract_tables(sql_stripped)
        for table in tables:
            if table not in self._table_cache:
                # 尝试动态检查
                if self.dal and self._check_table_exists(table):
                    self._table_cache.add(table)
                else:
                    errors.append(f"表不存在: {table}")

        # 5. 警告
        if "SELECT *" in sql_stripped.upper() and "EXISTS" not in sql_stripped.upper():
            warnings.append("使用SELECT *可能影响性能，建议明确指定字段")

        if "LIMIT" not in sql_stripped.upper():
            warnings.append("缺少LIMIT，可能返回大量结果")

        return SQLValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    def _check_injection(self, sql: str) -> str | None:
        """检查SQL注入风险"""
        for pattern in _DANGEROUS_PATTERNS:
            if pattern.search(sql):
                return f"检测到危险模式: {pattern.pattern}"

        # 检查多语句
        # 允许子查询中的分号不算
        statements = sql.split(";")
        non_empty = [s.strip() for s in statements if s.strip()]
        if len(non_empty) > 1:
            return "检测到多语句执行"

        return None

    def _extract_tables(self, sql: str) -> set[str]:
        """从SQL中提取表名"""
        tables = set()
        # FROM table
        from_matches = re.findall(r'\bFROM\s+(\w+)', sql, re.IGNORECASE)
        tables.update(from_matches)
        # JOIN table
        join_matches = re.findall(r'\bJOIN\s+(\w+)', sql, re.IGNORECASE)
        tables.update(join_matches)
        return tables

    def _check_table_exists(self, table: str) -> bool:
        """动态检查表是否存在"""
        if not self.dal:
            return False
        try:
            result = self.dal.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name=?",
                [table],
            )
            return bool(result.rows)
        except Exception:
            return False
