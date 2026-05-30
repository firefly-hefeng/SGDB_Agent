"""
SubqueryBuilder + CellTypeQueryBuilder — 子查询构建器

支持:
1. EXISTS — 存在性检查 (如"含T细胞的样本")
2. IN — 集合成员检查
3. CellType专用查询构建
"""

from __future__ import annotations

from typing import Optional


class SubqueryBuilder:
    """
    子查询构建器

    支持 EXISTS / IN / 标量子查询
    """

    @staticmethod
    def build_exists(
        parent_alias: str,
        parent_pk: str,
        child_table: str,
        child_fk: str,
        conditions: list[tuple[str, str, str]],
    ) -> tuple[str, list]:
        """
        构建EXISTS子查询 (参数化)

        Returns: (sql_fragment, params)

        示例输出:
        EXISTS (
            SELECT 1 FROM unified_celltypes
            WHERE unified_celltypes.sample_pk = s.pk
            AND unified_celltypes.cell_type_name LIKE ?
        )
        """
        where_parts = [f"{child_table}.{child_fk} = {parent_alias}.{parent_pk}"]
        params = []

        for field, op, value in conditions:
            where_parts.append(f"{child_table}.{field} {op} ?")
            params.append(value)

        where_clause = " AND ".join(where_parts)

        sql = f"EXISTS (\n    SELECT 1 FROM {child_table}\n    WHERE {where_clause}\n)"
        return sql, params

    @staticmethod
    def build_in(
        field: str,
        subquery_table: str,
        subquery_field: str,
        conditions: list[tuple[str, str, str]],
    ) -> tuple[str, list]:
        """
        构建IN子查询 (参数化)

        Returns: (sql_fragment, params)
        """
        where_parts = []
        params = []

        for f, op, v in conditions:
            where_parts.append(f"{f} {op} ?")
            params.append(v)

        where_clause = " AND ".join(where_parts) if where_parts else "1=1"

        sql = f"{field} IN (\n    SELECT {subquery_field} FROM {subquery_table}\n    WHERE {where_clause}\n)"
        return sql, params


class CellTypeQueryBuilder:
    """
    专门处理细胞类型查询的构建器

    将"含X细胞的样本"查询转换为EXISTS子查询。
    支持从 SchemaConfig 动态获取 celltype 表/字段配置。
    """

    # 默认值 — 仅在无 SchemaConfig 时使用
    _DEFAULT_CT_TABLE = "unified_celltypes"
    _DEFAULT_CT_FK = "sample_pk"
    _DEFAULT_CT_NAME_FIELD = "cell_type_name"
    _DEFAULT_MAIN_TABLE = "unified_samples"

    def __init__(self, *, schema_config=None):
        self.subquery = SubqueryBuilder()

        if schema_config is not None:
            ct = schema_config.get_celltype_config()
            self._ct_table = ct.get("table", self._DEFAULT_CT_TABLE)
            self._ct_fk = ct.get("fk_field", self._DEFAULT_CT_FK)
            self._ct_name = ct.get("name_field", self._DEFAULT_CT_NAME_FIELD)
            self._main_table = schema_config.main_table
        else:
            self._ct_table = self._DEFAULT_CT_TABLE
            self._ct_fk = self._DEFAULT_CT_FK
            self._ct_name = self._DEFAULT_CT_NAME_FIELD
            self._main_table = self._DEFAULT_MAIN_TABLE

    def build_celltype_filter(
        self,
        cell_types: list[str],
        parent_alias: str = "s",
        parent_pk: str = "pk",
        use_subquery: bool = False,
    ) -> tuple[Optional[str], list]:
        """
        构建细胞类型过滤条件

        Args:
            cell_types: 细胞类型列表
            parent_alias: 父表别名
            parent_pk: 父表主键字段
            use_subquery: when True, ALSO emit EXISTS subquery into
                unified_celltypes (legacy dual-path). Defaults to False:
                parent-table cell_type LIKE only — matches the typical
                oracle convention and avoids EXISTS-induced over-retrieval.

        Returns: (sql_fragment, params) or (None, [])

        Phase 20-A: dual-path default off; pass `use_subquery=True` to
        re-enable for queries that need cell-type breakdown widening.
        """
        if not cell_types:
            return None, []

        per_ct_clauses: list[str] = []
        all_params: list = []

        # Phase 20-A: pattern widening — for canonical names with "+",
        # widen to "%CD8% T cell%" etc. Also for compound names like
        # "pancreatic islet", ALSO match the loose token "%islet%" AND
        # also check the tissue column (curation splits anatomical
        # cell types across tissue / cell_type).
        _loose_aliases = {
            "pancreatic islet": ["%pancreatic islet%", "%islet%"],
            "pancreatic beta cell": ["%pancreatic beta%", "%beta cell%"],
            "pancreatic alpha cell": ["%pancreatic alpha%", "%alpha cell%"],
            "regulatory T cell": ["%regulatory T cell%", "%Treg%"],
            "CD8+ T cell": ["%CD8% T cell%", "%CD8%T%", "%cytotoxic T%"],
            "CD4+ T cell": ["%CD4% T cell%", "%CD4%T%", "%helper T%"],
        }
        _also_check_tissue = {"pancreatic islet"}

        for cell_type in cell_types:
            raw = cell_type.strip()
            if raw in _loose_aliases:
                patterns = _loose_aliases[raw]
            else:
                wc = raw.replace("+ ", "% ").replace("+", "%")
                patterns = [f"%{wc}%"]
            sub_clauses: list[str] = []
            for p in patterns:
                sub_clauses.append(f"{parent_alias}.cell_type LIKE ?")
                all_params.append(p)
            if raw in _also_check_tissue:
                sub_clauses.append(f"{parent_alias}.tissue LIKE ?")
                all_params.append(f"%{raw}%")
            parent_like = (sub_clauses[0] if len(sub_clauses) == 1
                           else "(" + " OR ".join(sub_clauses) + ")")
            if use_subquery:
                exists_sql, exists_params = self.subquery.build_exists(
                    parent_alias=parent_alias,
                    parent_pk=parent_pk,
                    child_table=self._ct_table,
                    child_fk=self._ct_fk,
                    conditions=[(self._ct_name, "LIKE", f"%{cell_type}%")],
                )
                all_params.extend(exists_params)
                per_ct_clauses.append(f"({parent_like} OR {exists_sql})")
            else:
                per_ct_clauses.append(parent_like)

        if len(per_ct_clauses) == 1:
            return per_ct_clauses[0], all_params
        combined = " OR ".join(per_ct_clauses)
        return f"({combined})", all_params

    def build_celltype_count_query(
        self,
        cell_types: list[str],
        additional_where: str = "1=1",
        additional_params: list | None = None,
        limit: int = 20,
    ) -> tuple[str, list]:
        """
        构建含细胞类型过滤的完整样本查询

        Returns: (full_sql, params)
        """
        ct_filter, ct_params = self.build_celltype_filter(cell_types, "s", "pk")

        where_parts = []
        params = []

        if additional_where and additional_where != "1=1":
            where_parts.append(additional_where)
            params.extend(additional_params or [])

        if ct_filter:
            where_parts.append(ct_filter)
            params.extend(ct_params)

        where_sql = " AND ".join(where_parts) if where_parts else "1=1"

        sql = (
            f"SELECT s.* FROM {self._main_table} s\n"
            f"WHERE {where_sql}\n"
            f"ORDER BY s.pk DESC"
        )
        return sql, params
