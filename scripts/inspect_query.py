"""Inspect parser+agent for a list of queries."""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.dal.database import DatabaseAbstractionLayer
from src.agent.coordinator import CoordinatorAgent
from src.understanding.parser import QueryParser


async def main(queries: list[str]):
    dal = DatabaseAbstractionLayer(
        str(ROOT.parent / "database_development/unified_db/human_metadata.db")
    )
    coord = CoordinatorAgent.create(
        dal=dal, llm=None,
        ontology_cache_path=str(ROOT / "data/ontologies/ontology_cache.db"),
        memory_db_path=str(ROOT / "data/memory"),
        schema_knowledge_path=str(ROOT / "data/schema_knowledge.yaml"),
        parser_mode="rule",
    )
    parser = QueryParser()

    for q in queries:
        print(f"\n{'='*70}\nQ: {q}\n{'='*70}")
        parsed = await parser.parse(q)
        print(f"intent: {parsed.intent}  strict={parsed.strict_mode}  target={parsed.target_level}  aggregation={parsed.aggregation}")
        print("entities:")
        for e in parsed.entities:
            print(f"  - {e.entity_type:<12} {e.text!r:<25} -> {e.normalized_value!r:<25} negated={getattr(e,'negated',False)}")
        print(f"filters tissues={parsed.filters.tissues!r} diseases={parsed.filters.diseases!r}")
        print(f"  cell_types={parsed.filters.cell_types!r} sample_types={parsed.filters.sample_types!r}")
        print(f"  organisms={parsed.filters.organisms!r} sources={parsed.filters.source_databases!r}")
        print(f"  min_cells={parsed.filters.min_cells} min_series_cells={parsed.filters.min_series_cells}")
        print(f"  pub_after={parsed.filters.published_after} pub_before={parsed.filters.published_before}")
        print(f"  exclude_tissues={parsed.filters.exclude_tissues!r} exclude_diseases={parsed.filters.exclude_diseases!r}")
        print(f"  exclude_assays={getattr(parsed.filters,'exclude_assays',None)!r}")
        print(f"  exclude_sources={getattr(parsed.filters,'exclude_source_databases',None)!r}")
        print(f"  has_h5ad={parsed.filters.has_h5ad}")
        try:
            r = await coord.query(q, session_id="inspect", limit=5)
            sql = r.provenance.sql_executed if hasattr(r.provenance, "sql_executed") else None
            print(f"\nagent total_count: {r.total_count}")
            print(f"sql_method: {r.provenance.sql_method if hasattr(r.provenance,'sql_method') else '?'}")
            print(f"agent SQL: {sql[:700] if sql else 'None'}")
        except Exception as e:
            print("agent error:", e)


if __name__ == "__main__":
    qs = sys.argv[1:] if len(sys.argv) > 1 else [
        "How many human cancer datasets do we have, regardless of tissue?",
        "samples from people with COVID",
        "Find all liver samples that are NOT cancer.",
        "Lung samples from human, excluding 10x assays.",
        "Largest cohorts in our DB — series with >= 100000 cells.",
        "Find Alzheimer datasets profiling specific neurons with 10x.",
        "Old datasets — anything before 2018.",
        "Group cancer datasets by tissue to see where we have most coverage.",
    ]
    asyncio.run(main(qs))
