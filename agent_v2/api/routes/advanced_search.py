"""
Advanced Search route — hybrid NL + structured iterative search.

Flow:
1. Accept existing conditions + optional NL query
2. Parse NL → extract new conditions
3. Merge with existing conditions
4. Execute SQL query
5. Compute facets for current filtered set
6. Return conditions + results + facets + provenance
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, HTTPException

from api.schemas import (
    AdvancedSearchRequest,
    AdvancedSearchResponse,
    ParsedCondition,
    ProvenanceOut,
    SuggestionOut,
)
from api.deps import get_dal, get_coordinator

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/scdbAPI", tags=["advanced-search"])

# Field display names
FIELD_LABELS = {
    "tissue": "Tissue",
    "disease": "Disease",
    "organism": "Organism",
    "assay": "Assay",
    "cell_type": "Cell Type",
    "source_database": "Database",
    "sex": "Sex",
    "project_id": "Project ID",
    "sample_id": "Sample ID",
    "pmid": "PMID",
}

ALLOWED_SORT = {
    "n_cells", "tissue", "disease", "assay", "organism",
    "source_database", "project_title", "sample_id", "sex",
}

BASE_SELECT = """
SELECT
    s.pk as sample_pk, s.sample_id, s.tissue, s.disease, s.cell_type,
    s.organism, s.sex, s.n_cells, s.source_database,
    sr.series_id, sr.title as series_title, sr.assay, sr.has_h5ad,
    p.project_id, p.title as project_title, p.pmid
FROM unified_samples s
LEFT JOIN unified_series sr ON s.series_pk = sr.pk
LEFT JOIN unified_projects p ON s.project_pk = p.pk
"""

FACET_FIELDS = {
    "tissue": "s.tissue",
    "disease": "s.disease",
    "organism": "s.organism",
    "source_database": "s.source_database",
    "sex": "s.sex",
    "cell_type": "s.cell_type",
    "assay": "sr.assay",
}


def parsed_query_to_conditions(parsed) -> list[ParsedCondition]:
    """Convert ParsedQuery filters + entities into ParsedCondition list."""
    conditions: list[ParsedCondition] = []
    f = parsed.filters

    mapping = [
        ("tissue", f.tissues),
        ("disease", f.diseases),
        ("organism", f.organisms),
        ("assay", f.assays),
        ("cell_type", f.cell_types),
        ("source_database", f.source_databases),
        ("project_id", f.project_ids),
        ("sample_id", f.sample_ids),
        ("pmid", f.pmids),
    ]

    for field, values in mapping:
        if values:
            label = FIELD_LABELS.get(field, field)
            conditions.append(ParsedCondition(
                field=field,
                operator="in",
                values=list(values),
                display_label=f"{label}: {', '.join(values)}",
                source="nl_parse",
                confidence=parsed.confidence,
            ))

    if f.sex:
        conditions.append(ParsedCondition(
            field="sex", operator="eq", values=[f.sex],
            display_label=f"Sex: {f.sex}", source="nl_parse",
            confidence=parsed.confidence,
        ))

    if f.min_cells is not None:
        conditions.append(ParsedCondition(
            field="min_cells", operator="gte", values=[str(f.min_cells)],
            display_label=f"Min Cells: {f.min_cells}", source="nl_parse",
            confidence=parsed.confidence,
        ))

    if f.has_h5ad is True:
        conditions.append(ParsedCondition(
            field="has_h5ad", operator="eq", values=["true"],
            display_label="Has H5AD: yes", source="nl_parse",
            confidence=parsed.confidence,
        ))

    if f.free_text:
        conditions.append(ParsedCondition(
            field="text_search", operator="like", values=[f.free_text],
            display_label=f"Text: {f.free_text}", source="nl_parse",
            confidence=parsed.confidence,
        ))

    return conditions


def merge_conditions(
    existing: list[ParsedCondition],
    new_conditions: list[ParsedCondition],
) -> list[ParsedCondition]:
    """Merge new conditions into existing, deduplicating by field."""
    merged = list(existing)
    existing_fields = {c.field for c in existing}

    for nc in new_conditions:
        if nc.field in existing_fields:
            # Merge values into existing condition for same field
            for i, ec in enumerate(merged):
                if ec.field == nc.field:
                    combined = list(set(ec.values + nc.values))
                    label = FIELD_LABELS.get(nc.field, nc.field)
                    merged[i] = ParsedCondition(
                        field=nc.field,
                        operator=nc.operator,
                        values=combined,
                        display_label=f"{label}: {', '.join(combined)}",
                        source=nc.source,
                        confidence=min(ec.confidence, nc.confidence),
                    )
                    break
        else:
            merged.append(nc)
            existing_fields.add(nc.field)

    return merged


def conditions_to_where(
    conditions: list[ParsedCondition],
) -> tuple[list[str], list[Any]]:
    """Convert condition list to SQL WHERE clauses + params."""
    clauses: list[str] = []
    params: list[Any] = []

    for c in conditions:
        if c.field == "tissue" and c.values:
            placeholders = ",".join("?" for _ in c.values)
            clauses.append(f"s.tissue IN ({placeholders})")
            params.extend(c.values)
        elif c.field == "disease" and c.values:
            placeholders = ",".join("?" for _ in c.values)
            clauses.append(f"s.disease IN ({placeholders})")
            params.extend(c.values)
        elif c.field == "organism" and c.values:
            placeholders = ",".join("?" for _ in c.values)
            clauses.append(f"s.organism IN ({placeholders})")
            params.extend(c.values)
        elif c.field == "assay" and c.values:
            placeholders = ",".join("?" for _ in c.values)
            clauses.append(f"sr.assay IN ({placeholders})")
            params.extend(c.values)
        elif c.field == "cell_type" and c.values:
            placeholders = ",".join("?" for _ in c.values)
            clauses.append(f"s.cell_type IN ({placeholders})")
            params.extend(c.values)
        elif c.field == "source_database" and c.values:
            placeholders = ",".join("?" for _ in c.values)
            clauses.append(f"s.source_database IN ({placeholders})")
            params.extend(c.values)
        elif c.field == "sex" and c.values:
            clauses.append("s.sex = ?")
            params.append(c.values[0])
        elif c.field == "min_cells" and c.values:
            clauses.append("s.n_cells >= ?")
            params.append(int(c.values[0]))
        elif c.field == "has_h5ad" and c.values and c.values[0] == "true":
            clauses.append("sr.has_h5ad = 1")
        elif c.field == "text_search" and c.values:
            clauses.append(
                "s.pk IN (SELECT rowid FROM fts_samples WHERE fts_samples MATCH ?)"
            )
            params.append(c.values[0])
        elif c.field == "project_id" and c.values:
            placeholders = ",".join("?" for _ in c.values)
            clauses.append(f"p.project_id IN ({placeholders})")
            params.extend(c.values)
        elif c.field == "sample_id" and c.values:
            placeholders = ",".join("?" for _ in c.values)
            clauses.append(f"s.sample_id IN ({placeholders})")
            params.extend(c.values)
        elif c.field == "pmid" and c.values:
            placeholders = ",".join("?" for _ in c.values)
            clauses.append(f"p.pmid IN ({placeholders})")
            params.extend(c.values)

    return clauses, params


def compute_filtered_facets(
    dal, where_clauses: list[str], where_params: list[Any],
) -> dict[str, list[dict]]:
    """Compute facet counts for the current filtered result set."""
    base_where = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    facets: dict[str, list[dict]] = {}

    for field_name, col_expr in FACET_FIELDS.items():
        try:
            null_clause = f"{col_expr} IS NOT NULL"
            if base_where:
                facet_where = f"{base_where} AND {null_clause}"
            else:
                facet_where = f"WHERE {null_clause}"

            needs_join = "sr." in col_expr
            if needs_join:
                from_clause = (
                    "FROM unified_samples s "
                    "LEFT JOIN unified_series sr ON s.series_pk = sr.pk "
                    "LEFT JOIN unified_projects p ON s.project_pk = p.pk"
                )
            else:
                # Check if WHERE references sr. or p.
                needs_series = "sr." in facet_where or "p." in facet_where
                if needs_series:
                    from_clause = (
                        "FROM unified_samples s "
                        "LEFT JOIN unified_series sr ON s.series_pk = sr.pk "
                        "LEFT JOIN unified_projects p ON s.project_pk = p.pk"
                    )
                else:
                    from_clause = "FROM unified_samples s"

            sql = (
                f"SELECT {col_expr} as value, COUNT(*) as count "
                f"{from_clause} {facet_where} "
                f"GROUP BY {col_expr} ORDER BY count DESC LIMIT 30"
            )
            result = dal.execute(sql, where_params)
            facets[field_name] = [
                {"value": r["value"], "count": r["count"]}
                for r in result.rows if r["value"]
            ]
        except Exception as e:
            logger.warning("Facet %s failed: %s", field_name, e)
            facets[field_name] = []

    return facets


@router.post("/advanced-search", response_model=AdvancedSearchResponse)
async def advanced_search(req: AdvancedSearchRequest):
    """Hybrid search: structured conditions + optional NL query refinement."""
    dal = get_dal()
    coordinator = get_coordinator()
    if dal is None:
        raise HTTPException(status_code=503, detail="Database not available")

    t0 = time.perf_counter()
    conditions = list(req.conditions)
    summary = ""
    provenance = ProvenanceOut()
    suggestions: list[SuggestionOut] = []

    # Step 1: If NL query provided, parse it and extract new conditions
    if req.nl_query and req.nl_query.strip():
        nl_text = req.nl_query.strip()
        provenance.original_query = nl_text

        # Route NL queries through full coordinator pipeline (parse → enrich → ontology → SQL → execute → fuse → synthesize)
        # This works with any parser (rule-based or LLM) — the enricher adds LLM intelligence
        _use_agent_pipeline = coordinator is not None

        if _use_agent_pipeline:
            # Full agent pipeline: parse → enrich → ontology → SQL → execute → fuse → synthesize
            try:
                agent_response = await coordinator.query(nl_text, session_id=req.session_id or "adv")
                provenance.parsed_intent = agent_response.provenance.parsed_intent
                provenance.sql_method = agent_response.provenance.sql_method
                provenance.sql_executed = agent_response.provenance.sql_executed
                provenance.data_sources = agent_response.provenance.data_sources
                provenance.ontology_expansions = [
                    {"original": e.get("original", ""), "field": e.get("field", ""),
                     "expanded_count": e.get("db_values_count", 0)}
                    for e in agent_response.provenance.ontology_expansions
                ]
                provenance.execution_time_ms = agent_response.provenance.execution_time_ms

                # Extract results from agent response
                records = [
                    {
                        "sample_pk": r.data.get("sample_pk", r.data.get("pk", 0)),
                        "sample_id": r.data.get("sample_id", ""),
                        "tissue": r.data.get("tissue"),
                        "disease": r.data.get("disease"),
                        "cell_type": r.data.get("cell_type"),
                        "organism": r.data.get("organism"),
                        "sex": r.data.get("sex"),
                        "n_cells": r.data.get("n_cells"),
                        "assay": r.data.get("assay"),
                        "source_database": r.data.get("source_database", r.data.get("sample_source", "")),
                        "series_id": r.data.get("series_id"),
                        "series_title": r.data.get("series_title", r.data.get("title", "")),
                        "has_h5ad": bool(r.data.get("has_h5ad")),
                        "project_id": r.data.get("project_id"),
                        "project_title": r.data.get("project_title"),
                        "pmid": r.data.get("pmid"),
                    }
                    for r in agent_response.results
                ]

                # Convert agent suggestions to API format
                suggestions = [
                    SuggestionOut(
                        text=s.text, type=s.type,
                        action_query=s.action_query, reason=s.reason,
                    )
                    for s in agent_response.suggestions
                ]

                # Compute facets from agent results for UI
                facets: dict[str, list[dict]] = {}
                if records:
                    for facet_field in ["tissue", "disease", "organism", "source_database", "sex", "cell_type", "assay"]:
                        counts: dict[str, int] = {}
                        for r in records:
                            val = r.get(facet_field)
                            if val:
                                counts[val] = counts.get(val, 0) + 1
                        facets[facet_field] = [
                            {"value": v, "count": c}
                            for v, c in sorted(counts.items(), key=lambda x: -x[1])[:30]
                        ]

                return AdvancedSearchResponse(
                    conditions=conditions,
                    results=records,
                    total_count=agent_response.total_count,
                    offset=req.offset,
                    limit=req.limit,
                    facets=facets,
                    summary=agent_response.summary,
                    provenance=provenance,
                    suggestions=suggestions,
                    error=None,
                )
            except Exception as e:
                logger.warning("Agent pipeline failed, falling back to condition-based: %s", e)
                # Fall through to condition-based parsing below

        if coordinator:
            try:
                parsed = await coordinator.parser.parse(nl_text)
                provenance.parsed_intent = parsed.intent.value
                provenance.sql_method = parsed.parse_method

                new_conditions = parsed_query_to_conditions(parsed)

                # Ontology resolution for richer conditions
                if coordinator.ontology and parsed.entities:
                    resolved = coordinator.ontology.resolve_all(parsed.entities)
                    for re_ in resolved:
                        if re_.db_values:
                            field = re_.original.entity_type
                            db_vals = [v["value"] for v in re_.db_values[:20]]
                            label = FIELD_LABELS.get(field, field)
                            # Replace or add ontology-expanded condition
                            found = False
                            for i, nc in enumerate(new_conditions):
                                if nc.field == field:
                                    new_conditions[i] = ParsedCondition(
                                        field=field, operator="in", values=db_vals,
                                        display_label=f"{label}: {re_.original.text} ({len(db_vals)} terms)",
                                        source="nl_parse", confidence=parsed.confidence,
                                    )
                                    found = True
                                    break
                            if not found:
                                new_conditions.append(ParsedCondition(
                                    field=field, operator="in", values=db_vals,
                                    display_label=f"{label}: {re_.original.text} ({len(db_vals)} terms)",
                                    source="nl_parse", confidence=parsed.confidence,
                                ))
                            provenance.ontology_expansions.append({
                                "original": re_.original.text,
                                "field": field,
                                "expanded_count": len(db_vals),
                            })

                conditions = merge_conditions(conditions, new_conditions)
                summary = f"Parsed \"{nl_text}\" → {len(new_conditions)} condition(s)"

            except Exception as e:
                logger.warning("NL parse failed: %s", e)
                summary = f"Could not parse \"{nl_text}\": {e}"
        else:
            summary = "Agent not available, using conditions only"

    # Step 2: Convert conditions to SQL WHERE
    where_clauses, where_params = conditions_to_where(conditions)
    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    # Step 3: Count total
    needs_join = any("sr." in c or "p." in c for c in where_clauses)
    if needs_join or not where_clauses:
        count_from = (
            "FROM unified_samples s "
            "LEFT JOIN unified_series sr ON s.series_pk = sr.pk "
            "LEFT JOIN unified_projects p ON s.project_pk = p.pk"
        )
    else:
        count_from = "FROM unified_samples s"

    count_sql = f"SELECT COUNT(*) as cnt {count_from} {where_sql}"
    count_result = dal.execute(count_sql, where_params)
    total_count = count_result.rows[0]["cnt"] if count_result.rows else 0

    # Step 4: Main query with sort + pagination
    sort_col = req.sort_by if req.sort_by in ALLOWED_SORT else "n_cells"
    sort_dir = "ASC" if req.sort_dir.lower() == "asc" else "DESC"
    sort_prefix = "s."
    if sort_col == "assay":
        sort_prefix = "sr."
    elif sort_col == "project_title":
        sort_prefix = "p."
        sort_col = "title"
    order_sql = f"ORDER BY {sort_prefix}{sort_col} {sort_dir} NULLS LAST"

    main_sql = f"{BASE_SELECT} {where_sql} {order_sql} LIMIT ? OFFSET ?"
    main_params = where_params + [req.limit, req.offset]
    result = dal.execute(main_sql, main_params)

    provenance.sql_executed = main_sql.strip()
    provenance.data_sources = list({r.get("source_database", "") for r in result.rows if r.get("source_database")})

    records = [
        {
            "sample_pk": r.get("sample_pk", 0),
            "sample_id": r.get("sample_id", ""),
            "tissue": r.get("tissue"),
            "disease": r.get("disease"),
            "cell_type": r.get("cell_type"),
            "organism": r.get("organism"),
            "sex": r.get("sex"),
            "n_cells": r.get("n_cells"),
            "assay": r.get("assay"),
            "source_database": r.get("source_database", ""),
            "series_id": r.get("series_id"),
            "series_title": r.get("series_title"),
            "has_h5ad": bool(r.get("has_h5ad")),
            "project_id": r.get("project_id"),
            "project_title": r.get("project_title"),
            "pmid": r.get("pmid"),
        }
        for r in result.rows
    ]

    # Step 5: Compute facets for current filtered set
    if where_clauses:
        facets = compute_filtered_facets(dal, where_clauses, where_params)
    else:
        # Use precomputed facets for unfiltered state
        from api.routes.explore import _load_precomputed_facets, _unfiltered_facets, _unfiltered_total
        if _unfiltered_facets is not None:
            facets = {k: [{"value": b.value, "count": b.count} for b in v] for k, v in _unfiltered_facets.items()}
        else:
            precomputed, _ = _load_precomputed_facets(dal)
            facets = {k: [{"value": b.value, "count": b.count} for b in v] for k, v in precomputed.items()}

    # Step 6: Build summary
    elapsed_ms = (time.perf_counter() - t0) * 1000
    provenance.execution_time_ms = elapsed_ms

    if not summary:
        summary = f"Found {total_count:,} samples"
        if conditions:
            cond_labels = [c.display_label for c in conditions if c.display_label]
            if cond_labels:
                summary += f" matching: {'; '.join(cond_labels)}"

    return AdvancedSearchResponse(
        conditions=conditions,
        results=records,
        total_count=total_count,
        offset=req.offset,
        limit=req.limit,
        facets=facets,
        summary=summary,
        provenance=provenance,
        suggestions=suggestions,
        error=None,
    )
