"""
SchemaKnowledgeTree — Phase 14.

Tree-structured schema knowledge with progressive disclosure for prompts.

Why a tree:
- Flat schema dumps blow up the prompt and hurt the LLM. The DB has 39
  tables, ~150 fields, thousands of distinct values per categorical
  field. Dumping everything is wasteful and harms accuracy
  (Spider/BIRD literature: smaller, query-focused schema → +EM/EX).
- LLMs do better when they walk a tree (database → table → field →
  top values) and we render *only* the subtree relevant to the query.

Levels:
  L0 root
   ├── L1 database (here single SQLite DB but extensible)
   │    └── L2 table  (unified_samples, unified_projects, …)
   │         └── L3 field (tissue, disease_category, organism_common, …)
   │              └── L4 top_values  (top-N values for categorical fields)

Progressive disclosure:
- ``render(scope)`` accepts a *scope* hint (set of fields/tables relevant
  to the query) and a ``budget`` (max chars). It expands relevant
  branches first, falls back to high-level summaries for the rest.
- ``render_for_query(query_lower)`` picks scope by simple keyword
  matching against field names and aliases. Cheap, no LLM call.

Output is plain text (compatible with current prompt builders) but
keeps the tree shape via Markdown headings + bullets so an LLM can read
it as a structured outline. JSON output is also available for evaluator
ablation studies.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml


logger = logging.getLogger(__name__)


# ─── Field aliases (short → canonical). Used for scope detection. ────
_FIELD_ALIASES: dict[str, list[str]] = {
    "tissue": ["tissue", "组织", "器官", "tissue_standard", "tissue_system",
               "anatomy"],
    "disease": ["disease", "疾病", "癌症", "cancer", "tumor", "肿瘤",
                "disease_category", "disease_standard"],
    "organism": ["organism", "species", "物种", "human", "mouse", "人类",
                 "小鼠", "organism_common"],
    "cell_type": ["cell type", "cell_type", "细胞类型", "cell"],
    "assay": ["assay", "platform", "scrna", "snrna", "10x", "smart-seq",
              "drop-seq", "测序方法"],
    "sex": ["sex", "gender", "male", "female", "性别", "男", "女"],
    "source_database": ["source_database", "geo", "ega", "ncbi", "ebi",
                        "cellxgene", "hca", "htan", "psychad", "数据库"],
    "sample_type": ["sample_type", "tumor", "normal", "control", "treatment",
                    "样本类型"],
    "n_cells": ["n_cells", "cell count", "细胞数", "cell number"],
    "publication_date": ["year", "date", "recent", "latest", "after",
                         "before", "2020", "2021", "2022", "2023", "2024",
                         "2025", "最近", "最新"],
    "citation_count": ["citation", "cited", "高引", "影响"],
    "pmid": ["pmid", "pubmed", "文献"],
    "doi": ["doi"],
    "treatment": ["treatment", "treated", "drug", "药物"],
    "genotype": ["genotype", "knock", "ko", "wt", "wild type", "突变"],
    "time_point": ["time_point", "timepoint", "day", "week", "时间点"],
    "control_status": ["control", "case", "对照"],
    "cell_line_name": ["cell line", "cell_line", "iPSC", "ESC", "细胞系"],
}


@dataclass
class FieldNode:
    name: str
    semantic_type: str
    table: str
    distinct_count: int = 0
    null_pct: float = 0.0
    top_values: list[tuple[str, int]] = field(default_factory=list)
    note: str = ""
    indexed: bool = False
    standardized: bool = False  # True for *_standard / *_category / *_common
    aliases: list[str] = field(default_factory=list)

    @property
    def category(self) -> str:
        """Coarse grouping for tree rendering."""
        if self.standardized:
            return "standardised"
        if self.semantic_type in ("tissue", "disease", "cell_type", "organism"):
            return "biological"
        if self.semantic_type in ("id", "metric"):
            return "structural"
        return "other"


@dataclass
class TableNode:
    name: str
    description: str = ""
    row_count: int = 0
    fields: dict[str, FieldNode] = field(default_factory=dict)
    primary_key: str = ""


@dataclass
class DatabaseNode:
    name: str = "unified_metadata"
    tables: dict[str, TableNode] = field(default_factory=dict)
    views: dict[str, str] = field(default_factory=dict)  # name → SELECT body
    stats: dict[str, Any] = field(default_factory=dict)


# ─── Loader ──────────────────────────────────────────────────────────


_STANDARDISED_SUFFIXES = ("_standard", "_category", "_common", "_normalized", "_system")


def _is_standardised(field_name: str) -> bool:
    return any(field_name.endswith(s) for s in _STANDARDISED_SUFFIXES)


def load_schema_tree(yaml_path: str | Path) -> "SchemaKnowledgeTree":
    """Construct a tree from the legacy schema_knowledge.yaml file."""
    yaml_path = Path(yaml_path)
    if not yaml_path.exists():
        raise FileNotFoundError(f"Schema knowledge YAML not found: {yaml_path}")
    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))

    db = DatabaseNode(name="unified_metadata")
    db.stats = raw.get("stats", {}) or {}
    db.views = raw.get("views", {}) or {}

    tables_meta = raw.get("tables", {}) or {}
    fields_meta = raw.get("fields", {}) or {}

    # Build tables first
    for tname, tinfo in tables_meta.items():
        if not isinstance(tinfo, dict):
            continue
        db.tables[tname] = TableNode(
            name=tname,
            description=tinfo.get("description", ""),
            row_count=int(tinfo.get("row_count", tinfo.get("count", 0)) or 0),
            primary_key=tinfo.get("primary_key", ""),
        )

    # Place fields under their owning table
    for fname, finfo in fields_meta.items():
        if not isinstance(finfo, dict):
            continue
        table = finfo.get("table") or "unified_samples"
        if table not in db.tables:
            db.tables[table] = TableNode(name=table)

        top_values = []
        for tv in finfo.get("top_values", []) or []:
            if isinstance(tv, dict):
                top_values.append((str(tv.get("value", "")), int(tv.get("count", 0))))
            else:
                top_values.append((str(tv), 0))

        node = FieldNode(
            name=fname,
            semantic_type=finfo.get("semantic_type", "categorical"),
            table=table,
            distinct_count=int(finfo.get("distinct_count", 0) or 0),
            null_pct=float(finfo.get("null_pct", 0.0) or 0.0),
            top_values=top_values,
            note=finfo.get("note", ""),
            indexed=bool(finfo.get("indexed", False)),
            standardized=_is_standardised(fname),
            aliases=_FIELD_ALIASES.get(fname, []),
        )
        db.tables[table].fields[fname] = node

    return SchemaKnowledgeTree(db=db)


# ─── Live DB augmentation ────────────────────────────────────────────


def augment_from_db(tree: "SchemaKnowledgeTree", db_path: str | Path) -> "SchemaKnowledgeTree":
    """Pull live schema info to fill in fields the YAML doesn't cover.

    The YAML is hand-curated and lags. We probe sqlite_master + PRAGMA
    table_info to discover all columns, plus pull top_values lazily per
    standardised column (which is cheap because they're indexed).
    """
    import sqlite3
    db_path = str(db_path)
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    cur = con.cursor()

    # core tables
    for tname in ("unified_samples", "unified_projects", "unified_series"):
        try:
            cur.execute(f"PRAGMA table_info({tname})")
            cols = cur.fetchall()
        except sqlite3.OperationalError:
            continue
        if tname not in tree.db.tables:
            tree.db.tables[tname] = TableNode(name=tname)
        table = tree.db.tables[tname]
        try:
            cur.execute(f"SELECT COUNT(*) FROM {tname}")
            table.row_count = cur.fetchone()[0]
        except sqlite3.OperationalError:
            pass
        for cid, name, ctype, notnull, default, pk in cols:
            if name in table.fields:
                continue
            sem = _infer_semantic_type(name, ctype)
            table.fields[name] = FieldNode(
                name=name,
                semantic_type=sem,
                table=tname,
                standardized=_is_standardised(name),
                aliases=_FIELD_ALIASES.get(name, []),
            )

    # indexes → mark fields
    cur.execute(
        "SELECT tbl_name, name FROM sqlite_master WHERE type='index'"
    )
    for tbl, idxname in cur.fetchall():
        if tbl not in tree.db.tables:
            continue
        # tail of index name often matches column
        tail = idxname.replace("idx_", "").replace("samples_", "")
        for fname in tree.db.tables[tbl].fields:
            if fname.lower() in tail.lower():
                tree.db.tables[tbl].fields[fname].indexed = True

    # Top values for the standardised columns (cheap, indexed scans).
    fast_path_cols = [
        ("unified_samples", "tissue_standard"),
        ("unified_samples", "disease_category"),
        ("unified_samples", "disease_standard"),
        ("unified_samples", "organism_common"),
        ("unified_samples", "sex_normalized"),
        ("unified_samples", "sample_type"),
        ("unified_samples", "tissue_system"),
        ("unified_samples", "source_database"),
    ]
    for tname, col in fast_path_cols:
        if tname not in tree.db.tables:
            continue
        if col not in tree.db.tables[tname].fields:
            continue
        node = tree.db.tables[tname].fields[col]
        if node.top_values:
            continue
        try:
            cur.execute(
                f"SELECT {col}, COUNT(*) c FROM {tname} "
                f"WHERE {col} IS NOT NULL AND {col} != '' "
                f"GROUP BY {col} ORDER BY c DESC LIMIT 12"
            )
            node.top_values = [(str(v), int(c)) for v, c in cur.fetchall()]
            node.distinct_count = len(node.top_values) if len(node.top_values) < 12 else node.distinct_count
        except sqlite3.OperationalError as e:
            logger.debug("top_values probe failed on %s.%s: %s", tname, col, e)

    con.close()
    # Rebuild scope index after augmentation
    tree._build_scope_index()
    return tree


def _infer_semantic_type(name: str, ctype: str) -> str:
    n = name.lower()
    if n.endswith("_id") or n in ("pk", "id"):
        return "id"
    if "tissue" in n or n == "tissue":
        return "tissue"
    if "disease" in n:
        return "disease"
    if "organism" in n or "species" in n:
        return "organism"
    if "cell_type" in n:
        return "cell_type"
    if "assay" in n or "platform" in n:
        return "assay"
    if "sex" in n or "gender" in n:
        return "sex"
    if n in ("age", "age_min", "age_max", "n_cells", "citation_count",
             "sample_count", "total_cells"):
        return "metric"
    if "date" in n or "year" in n or n.endswith("_at"):
        return "temporal"
    return "categorical"


# ─── Public API ──────────────────────────────────────────────────────


@dataclass
class RenderConfig:
    """Tunable renderer parameters used in ablation experiments."""

    budget_chars: int = 1800
    top_values_per_field: int = 6
    include_null_pct: bool = True
    include_distinct_count: bool = True
    include_aliases: bool = False
    show_views: bool = True
    standardised_first: bool = True
    style: str = "tree"   # "tree" | "flat" | "json" | "minimal"


class SchemaKnowledgeTree:
    """Tree-shaped schema with progressive disclosure for prompts."""

    def __init__(self, db: DatabaseNode):
        self.db = db
        self._scope_index: dict[str, str] = {}     # alias_lower → field
        self._build_scope_index()

    def _build_scope_index(self) -> None:
        """Refresh the alias → field name lookup."""
        idx: dict[str, str] = {}
        for table in self.db.tables.values():
            for f in table.fields.values():
                idx[f.name.lower()] = f.name
                for alias in f.aliases:
                    idx[alias.lower()] = f.name
        self._scope_index = idx

    # ── Scope detection ────────────────────────────────────────────
    def fields_relevant_to(self, query: str) -> set[str]:
        """Cheap keyword scan to pick fields the query talks about.

        Two signals:
        1. Field name / alias literal match.
        2. Top-value match — if the query contains a value that appears
           in a field's top_values, that field is in scope. This catches
           "liver cancer samples from GEO" → tissue_standard via "liver".
        """
        q = query.lower()
        hit: set[str] = set()
        for alias, canonical in self._scope_index.items():
            if alias and len(alias) >= 3 and alias in q:
                hit.add(canonical)
        # Top-value match — check standardised columns first
        for table in self.db.tables.values():
            for f in table.fields.values():
                if not f.top_values:
                    continue
                # Bias towards standardised / indexed columns
                if not (f.standardized or f.indexed
                        or f.semantic_type in ("tissue", "disease", "organism", "source_database")):
                    continue
                for v, _ in f.top_values[:20]:
                    v_l = v.lower()
                    # Need at least 3 chars to avoid noise (e.g. "co", "n")
                    if len(v_l) >= 3 and v_l in q:
                        hit.add(f.name)
                        break
        return hit

    # ── Renderers ──────────────────────────────────────────────────
    def render_for_query(
        self, query: str, config: RenderConfig | None = None,
        extra_fields: Iterable[str] | None = None,
    ) -> str:
        """Render a focused tree slice for the prompt."""
        cfg = config or RenderConfig()
        scope = self.fields_relevant_to(query)
        if extra_fields:
            scope.update(extra_fields)
        return self._render(scope, cfg)

    def render_full(self, config: RenderConfig | None = None) -> str:
        cfg = config or RenderConfig()
        return self._render(scope=None, cfg=cfg)

    def render_minimal(self) -> str:
        """Bare list of standardised columns for a query parser to refer to."""
        lines = ["Standardised columns (use these for fast indexed search):"]
        for table in self.db.tables.values():
            std = [f for f in table.fields.values() if f.standardized]
            if not std:
                continue
            lines.append(f"  {table.name}:")
            for f in std:
                lines.append(f"    - {f.name}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "database": self.db.name,
            "stats": self.db.stats,
            "tables": {
                t.name: {
                    "row_count": t.row_count,
                    "fields": {
                        n: {
                            "type": f.semantic_type,
                            "distinct": f.distinct_count,
                            "null_pct": f.null_pct,
                            "top_values": f.top_values[:6],
                            "standardized": f.standardized,
                        }
                        for n, f in t.fields.items()
                    },
                }
                for t in self.db.tables.values()
            },
            "views": list(self.db.views.keys()),
        }

    # ── Internal ───────────────────────────────────────────────────
    def _render(self, scope: set[str] | None, cfg: RenderConfig) -> str:
        if cfg.style == "json":
            payload = self.to_dict() if scope is None else self._scope_payload(scope)
            return json.dumps(payload, ensure_ascii=False, indent=2)[: cfg.budget_chars]
        if cfg.style == "minimal":
            return self.render_minimal()[: cfg.budget_chars]
        if cfg.style == "flat":
            return self._render_flat(scope, cfg)
        return self._render_tree(scope, cfg)

    def _scope_payload(self, scope: set[str]) -> dict:
        out = {"database": self.db.name, "tables": {}}
        for t in self.db.tables.values():
            cols = {n: f for n, f in t.fields.items() if (not scope) or (n in scope)}
            if cols:
                out["tables"][t.name] = {
                    "row_count": t.row_count,
                    "fields": {
                        n: {
                            "type": f.semantic_type,
                            "top_values": f.top_values[:6],
                            "standardized": f.standardized,
                        }
                        for n, f in cols.items()
                    },
                }
        return out

    def _render_tree(self, scope: set[str] | None, cfg: RenderConfig) -> str:
        out: list[str] = []
        out.append("# Database: unified_metadata")
        s = self.db.stats
        if s:
            out.append(
                f"# Total: {s.get('total_samples', 0):,} samples · "
                f"{s.get('total_projects', 0):,} projects · "
                f"{s.get('total_series', 0):,} series across {s.get('total_sources', 0)} sources"
            )

        # Sort tables: target tables first
        tables = list(self.db.tables.values())
        priority = {"unified_samples": 0, "unified_projects": 1,
                    "unified_series": 2}
        tables.sort(key=lambda t: priority.get(t.name, 9))

        for table in tables:
            relevant = [f for f in table.fields.values()
                        if (scope is None) or (f.name in scope)]
            if scope is not None and not relevant:
                continue

            out.append(f"\n## Table: {table.name}  (rows={table.row_count:,})")
            if cfg.standardised_first:
                relevant.sort(key=lambda f: (not f.standardized, not f.indexed,
                                              -len(f.top_values)))

            for f in relevant:
                self._append_field(out, f, cfg)

            if scope is None:
                # also show non-relevant standardised columns as "available"
                others = [f for f in table.fields.values()
                          if f not in relevant and f.standardized]
                if others:
                    out.append("  …other standardised columns: " +
                               ", ".join(f.name for f in others[:8]))

            if len("\n".join(out)) > cfg.budget_chars:
                out.append("  …(truncated to fit budget)")
                break

        if cfg.show_views and self.db.views:
            out.append("\n## Views")
            for vname in list(self.db.views)[:3]:
                out.append(f"  - {vname}")

        return "\n".join(out)[: cfg.budget_chars]

    def _render_flat(self, scope: set[str] | None, cfg: RenderConfig) -> str:
        out = []
        for table in self.db.tables.values():
            for f in table.fields.values():
                if scope is not None and f.name not in scope:
                    continue
                top = ", ".join(v for v, _ in f.top_values[:cfg.top_values_per_field])
                tag = "★" if f.standardized else ("◆" if f.indexed else "·")
                line = f"{tag} {table.name}.{f.name} [{f.semantic_type}]"
                if top:
                    line += f" e.g. {top}"
                out.append(line)
                if len("\n".join(out)) > cfg.budget_chars:
                    return "\n".join(out)
        return "\n".join(out)

    def _append_field(self, out: list[str], f: FieldNode, cfg: RenderConfig) -> None:
        marker = "★" if f.standardized else ("◆" if f.indexed else "•")
        bits = [f"  {marker} {f.name}  ({f.semantic_type})"]
        meta = []
        if cfg.include_distinct_count and f.distinct_count:
            meta.append(f"{f.distinct_count} distinct")
        if cfg.include_null_pct and f.null_pct:
            meta.append(f"{f.null_pct:.1f}% null")
        if f.standardized:
            meta.append("indexed/normalised")
        if meta:
            bits.append("  → " + ", ".join(meta))
        out.append(" — ".join(bits))
        if f.top_values:
            top = ", ".join(
                f"{v} ({c:,})" if c else v
                for v, c in f.top_values[:cfg.top_values_per_field]
            )
            out.append(f"      top: {top}")
        if f.note:
            out.append(f"      note: {f.note}")


__all__ = [
    "SchemaKnowledgeTree", "RenderConfig", "load_schema_tree",
    "DatabaseNode", "TableNode", "FieldNode",
]
