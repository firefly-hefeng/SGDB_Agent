"""
LLM Prompt Templates — structured prompt builders for each pipeline stage.

Each function returns a complete prompt string with Schema Knowledge injected.
All prompts request structured JSON output for reliable parsing.
"""

from __future__ import annotations


def build_parse_prompt(
    schema_context: str,
    user_query: str,
    session_history: list[dict] | None = None,
) -> str:
    """
    Build the query parsing prompt.

    Injects full Schema Knowledge so the LLM can:
    - Classify intent
    - Extract entities with correct canonical values
    - Build filters using actual DB values
    - Handle Chinese↔English translation
    """
    history_block = ""
    if session_history:
        recent = session_history[-3:]
        turns = []
        for t in recent:
            turns.append(f"  - User: {t.get('input', '')}")
            turns.append(f"    Result: {t.get('result_count', 0)} records, intent={t.get('intent', '')}")
        history_block = f"\n## Recent Conversation\n" + "\n".join(turns) + "\n"

    return f"""You are a query parser for a single-cell RNA-seq metadata database.
Parse the user query into structured JSON for database retrieval.

{schema_context}
{history_block}
## User Query
"{user_query}"

## Output Format (JSON only)
{{
  "intent": "SEARCH | COMPARE | STATISTICS | EXPLORE | DOWNLOAD | LINEAGE",
  "target_level": "project | series | sample | celltype",
  "entities": [
    {{"text": "original text", "type": "tissue|disease|cell_type|assay|organism|source_database|sex", "value": "canonical DB value"}}
  ],
  "filters": {{
    "tissues": [],
    "diseases": [],
    "cell_types": [],
    "assays": [],
    "organisms": [],
    "source_databases": [],
    "sex": null,
    "project_ids": [],
    "sample_ids": [],
    "pmids": [],
    "free_text": null
  }},
  "aggregation": null | {{"group_by": ["field"], "metric": "count"}},
  "ordering": null | {{"field": "...", "direction": "asc|desc"}},
  "confidence": 0.0-1.0,
  "reasoning": "brief explanation of parsing decisions"
}}

## Rules
- Map user terms to actual DB values from the top_values lists above
- Translate Chinese terms to English canonical values using the synonyms
- Default organism: "Homo sapiens" (unless explicitly stated otherwise)
- "正常"/"健康"/"control" → disease: "normal"
- "数据集"/"dataset" → target_level: "sample"
- For statistics queries, set aggregation with appropriate group_by
- If the query references previous results (这些/其中/those/above), incorporate session context
- Set confidence based on how well the query maps to known DB values
- Return ONLY valid JSON, no explanation outside the JSON"""


def build_validation_prompt(
    validation_context: str,
    parsed_result: dict,
    user_query: str,
) -> str:
    """
    Build the validation prompt to verify and correct parsed results.

    Checks filter values against actual DB distributions.
    """
    import json
    parsed_json = json.dumps(parsed_result, ensure_ascii=False, indent=2)

    return f"""You are a validation module for a single-cell metadata query system.
Verify the parsed query result against the actual database values and correct any issues.

{validation_context}

## Original User Query
"{user_query}"

## Parsed Result to Validate
{parsed_json}

## Output Format (JSON only)
{{
  "is_valid": true|false,
  "corrections": [
    {{"field": "...", "original": "...", "corrected": "...", "reason": "..."}}
  ],
  "conflicts": [
    {{"fields": ["...", "..."], "reason": "..."}}
  ],
  "warnings": ["..."],
  "corrected_filters": {{...}}  // only if corrections were made; same structure as input filters
}}

## Validation Rules
- Check each filter value against the "Known DB values" list
- If a value doesn't exist in DB, find the closest match from known values
- Detect conflicting filters (e.g., tissue=brain + disease=hepatocellular carcinoma)
- Flag values that might be too specific (low count) or too broad
- If all values are valid, set is_valid=true and empty corrections
- Return ONLY valid JSON"""


def build_recovery_prompt(
    recovery_context: str,
    original_query: str,
    failed_filters: dict,
    sql: str,
) -> str:
    """
    Build the zero-result recovery prompt.

    LLM diagnoses why the query returned 0 results and suggests relaxation strategies.
    """
    import json
    filters_json = json.dumps(failed_filters, ensure_ascii=False, indent=2)

    return f"""You are a recovery module for a single-cell metadata query system.
The following query returned 0 results. Diagnose the issue and suggest how to relax the filters.

{recovery_context}

## Original Query
"{original_query}"

## Failed Filters
{filters_json}

## Executed SQL (returned 0 rows)
{sql}

## Output Format (JSON only)
{{
  "diagnosis": "brief explanation of why 0 results",
  "strategy": "relax_value | broaden_field | remove_filter | split_query",
  "relaxed_filters": {{...}},  // modified filters that should return results
  "explanation": "user-facing explanation of what was changed",
  "alternatives": [
    {{"description": "...", "filters": {{...}}}}
  ]
}}

## Recovery Strategies
- relax_value: Replace specific value with broader term (e.g., "hippocampus" → "brain")
- broaden_field: Use LIKE instead of exact match
- remove_filter: Drop the most restrictive filter
- split_query: Break into multiple simpler queries
- Use the value distributions above to pick values that actually exist in the DB
- Prefer minimal changes — relax one filter at a time
- Return ONLY valid JSON"""


def build_suggestion_prompt(
    schema_context: str,
    query: str,
    result_count: int,
    summary: str,
) -> str:
    """
    Build the suggestion generation prompt.

    LLM generates 2-4 contextual follow-up suggestions.
    """
    return f"""You are a suggestion engine for a single-cell metadata query system.
Generate 2-4 relevant follow-up suggestions based on the query results.

{schema_context}

## Query: "{query}"
## Results: {result_count} records
## Summary: {summary}

## Output Format (JSON only)
{{
  "suggestions": [
    {{
      "type": "refine | expand | compare | download | related",
      "text": "user-facing suggestion text (Chinese if query was Chinese, else English)",
      "action_query": "the actual query string to execute",
      "reason": "brief reason for this suggestion"
    }}
  ]
}}

## Rules
- Generate 2-4 suggestions, ordered by relevance
- If result_count is large (>50), suggest refinement (add disease/assay/cell_type filter)
- If result_count is small (<5), suggest broadening (remove a filter, try related terms)
- If result_count is 0, suggest alternative searches using known DB values
- Always include at least one "compare" or "related" suggestion
- Match the language of the original query (Chinese query → Chinese suggestions)
- action_query should be a natural language query the system can parse
- Return ONLY valid JSON"""


def build_sql_prompt(
    sql_context: str,
    parsed_query: dict,
    resolved_entities: list[dict] | None = None,
) -> str:
    """
    Build the SQL generation prompt.

    Injects DDL + constraints + view info for accurate SQL generation.
    """
    import json
    query_json = json.dumps(parsed_query, ensure_ascii=False, indent=2)

    entity_block = ""
    if resolved_entities:
        entity_lines = []
        for e in resolved_entities:
            db_vals = e.get("db_values", [])
            if db_vals:
                vals = [v.get("value", v) if isinstance(v, dict) else v for v in db_vals[:10]]
                entity_lines.append(f"  - {e.get('original', '?')}: DB values = {vals}")
        if entity_lines:
            entity_block = "\n## Ontology-Resolved Entities\n" + "\n".join(entity_lines) + "\n"

    return f"""You are a SQL generator for a single-cell metadata SQLite database.
Generate a parameterized SQL query based on the parsed query.

{sql_context}
{entity_block}
## Parsed Query
{query_json}

## Output Format (JSON only)
{{
  "sql": "SELECT ... FROM ... WHERE ... LIMIT ?",
  "params": ["param1", "param2", 20],
  "explanation": "brief explanation of the SQL strategy"
}}

## SQL Rules
- Use parameterized queries (? placeholders) for ALL user values
- Use LIKE '%?%' pattern for text fields (tissue, disease, cell_type)
- Use IN (?, ?, ...) for enumerated fields (source_database, sex)
- Always include LIMIT (default 20, max 200)
- Prefer v_sample_with_hierarchy view for joined queries
- Remember: in the view, pk→sample_pk, source_database→sample_source, title→project_title
- cell_type is NOT in the view — use unified_samples directly if cell_type is needed
- For statistics, use GROUP BY with COUNT(*)
- For ID lookups, query the specific table directly
- Return ONLY valid JSON"""
