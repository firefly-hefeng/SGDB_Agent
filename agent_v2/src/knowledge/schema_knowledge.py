"""
Schema Knowledge — runtime read-only accessor for schema_knowledge.yaml.

Loads the YAML asset once and provides:
- Field metadata access (top values, synonyms, stats)
- ID pattern matching
- LLM prompt formatting (the core value: structured context injection)
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


class SchemaKnowledge:
    """Runtime read-only Schema Knowledge. Loaded from YAML, injected into LLM prompts."""

    def __init__(self, yaml_path: str | Path):
        self._path = Path(yaml_path)
        self._data: dict = {}
        self._load()

    def _load(self):
        if not self._path.exists():
            raise FileNotFoundError(f"Schema knowledge not found: {self._path}")
        with open(self._path, "r", encoding="utf-8") as f:
            self._data = yaml.safe_load(f) or {}
        logger.info(
            "SchemaKnowledge loaded: v%s, %d fields, %d tables",
            self._data.get("version", "?"),
            len(self._data.get("fields", {})),
            len(self._data.get("tables", {})),
        )

    # ── Accessors ──

    @property
    def stats(self) -> dict:
        return self._data.get("stats", {})

    @property
    def fields(self) -> dict[str, dict]:
        return self._data.get("fields", {})

    @property
    def tables(self) -> dict[str, dict]:
        return self._data.get("tables", {})

    @property
    def views(self) -> dict[str, dict]:
        return self._data.get("views", {})

    @property
    def id_patterns(self) -> list[dict]:
        return self._data.get("id_patterns", [])

    @property
    def query_constraints(self) -> list[str]:
        return self._data.get("query_constraints", [])

    def get_field(self, name: str) -> dict | None:
        return self.fields.get(name)

    def get_top_values(self, field: str, n: int = 20) -> list[dict]:
        f = self.get_field(field)
        if not f:
            return []
        return f.get("top_values", [])[:n]

    def get_synonyms(self, field: str) -> dict[str, list[str]]:
        f = self.get_field(field)
        if not f:
            return {}
        base = dict(f.get("known_synonyms", {}))
        # Merge overrides
        overrides = self._data.get("overrides", {}).get("synonyms", {}).get(field, {})
        for k, v in overrides.items():
            base[k] = v
        return base

    def resolve_synonym(self, field: str, user_term: str) -> str | None:
        """Resolve a user term to a canonical DB value via synonyms. Returns None if no match."""
        synonyms = self.get_synonyms(field)
        term_lower = user_term.lower().strip()

        # Direct match on canonical value
        for canonical in synonyms:
            if canonical.lower() == term_lower:
                return canonical

        # Match on synonym list
        for canonical, syns in synonyms.items():
            for s in syns:
                if s.lower() == term_lower:
                    return canonical

        return None

    def match_id_pattern(self, text: str) -> dict | None:
        """Match text against known ID patterns. Returns pattern info or None."""
        text = text.strip()
        for pat in self.id_patterns:
            if text.upper().startswith(pat["prefix"]):
                return pat
        # DOI
        if text.startswith("10."):
            return {"prefix": "10.", "type": "doi", "table": "unified_projects", "field": "doi"}
        return None

    # ── LLM Prompt Formatting (core) ──

    def format_for_parse_prompt(self) -> str:
        """Full schema context for query parsing (~2-4K tokens)."""
        lines = ["## Database Schema Knowledge\n"]

        # Stats
        s = self.stats
        lines.append(f"Total: {s.get('total_samples', 0):,} samples, "
                      f"{s.get('total_projects', 0):,} projects, "
                      f"{s.get('total_series', 0):,} series")
        src_dbs = s.get("source_databases", [])
        if src_dbs:
            src_str = ", ".join(f"{d['name']}({d['sample_count']:,})" for d in src_dbs[:8])
            lines.append(f"Sources: {src_str}")
        lines.append("")

        # Fields with top values + synonyms
        for fname, finfo in self.fields.items():
            lines.append(f"### {fname} (table: {finfo.get('table', '?')}, "
                          f"distinct: {finfo.get('distinct_count', 0):,}, "
                          f"null: {finfo.get('null_pct', 0)}%)")
            top = finfo.get("top_values", [])[:20]
            if top:
                vals = ", ".join(f"{v['value']}({v['count']:,})" for v in top)
                lines.append(f"  Top values: {vals}")
            syns = finfo.get("known_synonyms", {})
            if syns:
                syn_examples = []
                for canonical, aliases in list(syns.items())[:8]:
                    syn_examples.append(f"{canonical}=[{', '.join(aliases[:3])}]")
                lines.append(f"  Synonyms: {'; '.join(syn_examples)}")
            lines.append("")

        # ID patterns
        lines.append("### ID Patterns")
        for p in self.id_patterns:
            lines.append(f"  {p['prefix']}* → {p['table']}.{p['field']}")
        lines.append("")

        # Query constraints
        lines.append("### Query Constraints")
        for c in self.query_constraints:
            lines.append(f"  - {c}")

        return "\n".join(lines)

    def format_for_validation(self, filters: dict) -> str:
        """Focused context for validating parsed filters (~1K tokens)."""
        lines = ["## Validation Context\n"]

        # Only include fields that appear in filters
        field_map = {
            "tissues": "tissue",
            "diseases": "disease",
            "cell_types": "cell_type",
            "assays": "assay",
            "organisms": "organism",
            "source_databases": "source_database",
            "sex": "sex",
        }

        for filter_key, field_name in field_map.items():
            values = filters.get(filter_key)
            if not values:
                continue
            if isinstance(values, str):
                values = [values]

            finfo = self.get_field(field_name)
            if not finfo:
                continue

            lines.append(f"### {field_name}")
            top = finfo.get("top_values", [])[:30]
            if top:
                vals = [v["value"] for v in top]
                lines.append(f"  Known DB values: {', '.join(vals[:30])}")
            syns = finfo.get("known_synonyms", {})
            if syns:
                # Show synonyms relevant to the user's values
                for uv in values:
                    resolved = self.resolve_synonym(field_name, uv)
                    if resolved and resolved != uv:
                        lines.append(f"  '{uv}' → canonical: '{resolved}'")
            lines.append("")

        return "\n".join(lines)

    def format_for_recovery(self, filters: dict) -> str:
        """Context for zero-result recovery: value distributions (~1K tokens)."""
        lines = ["## Recovery Context — Value Distributions\n"]

        field_map = {
            "tissues": "tissue",
            "diseases": "disease",
            "cell_types": "cell_type",
            "assays": "assay",
            "organisms": "organism",
            "source_databases": "source_database",
        }

        for filter_key, field_name in field_map.items():
            values = filters.get(filter_key)
            if not values:
                continue

            finfo = self.get_field(field_name)
            if not finfo:
                continue

            lines.append(f"### {field_name} (user searched: {values})")
            top = finfo.get("top_values", [])[:15]
            if top:
                for v in top:
                    lines.append(f"  - {v['value']}: {v['count']:,}")
            lines.append(f"  Total distinct: {finfo.get('distinct_count', 0):,}")
            lines.append("")

        return "\n".join(lines)

    def format_for_sql_generation(self) -> str:
        """DDL + constraints + view info for SQL generation."""
        lines = ["## SQL Generation Context\n"]

        # Tables
        lines.append("### Tables")
        for tname, tinfo in self.tables.items():
            cols = ", ".join(tinfo.get("key_columns", [])[:15])
            lines.append(f"  {tname} ({tinfo.get('record_count', 0):,} rows): {cols}")
        lines.append("")

        # Views
        lines.append("### Views")
        for vname, vinfo in self.views.items():
            lines.append(f"  {vname}: {vinfo.get('description', '')}")
            if vinfo.get("note"):
                lines.append(f"    NOTE: {vinfo['note']}")
            aliases = vinfo.get("column_aliases", {})
            if aliases:
                alias_str = ", ".join(f"{k}→{v}" for k, v in aliases.items())
                lines.append(f"    Column aliases: {alias_str}")
        lines.append("")

        # Constraints
        lines.append("### Constraints")
        for c in self.query_constraints:
            lines.append(f"  - {c}")

        # Relationships
        lines.append("\n### Relationships")
        lines.append("  unified_series.project_pk → unified_projects.pk")
        lines.append("  unified_samples.series_pk → unified_series.pk")
        lines.append("  unified_samples.project_pk → unified_projects.pk")
        lines.append("  unified_celltypes.sample_pk → unified_samples.pk")

        return "\n".join(lines)

    def format_for_suggestions(self) -> str:
        """Stats + field overview for suggestion generation (~500 tokens)."""
        lines = ["## Database Overview for Suggestions\n"]

        s = self.stats
        lines.append(f"Total: {s.get('total_samples', 0):,} samples across "
                      f"{s.get('total_projects', 0):,} projects")
        src_dbs = s.get("source_databases", [])
        if src_dbs:
            for d in src_dbs:
                lines.append(f"  - {d['name']}: {d['sample_count']:,} samples")
        lines.append("")

        lines.append("### Available filter fields")
        for fname, finfo in self.fields.items():
            top3 = finfo.get("top_values", [])[:3]
            examples = ", ".join(v["value"] for v in top3) if top3 else "N/A"
            lines.append(f"  {fname}: {finfo.get('distinct_count', 0):,} values (e.g. {examples})")

        return "\n".join(lines)
