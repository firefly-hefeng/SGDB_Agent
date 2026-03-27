"""
SCeQTL-Agent Python SDK Client

Programmatic access to the SCeQTL-Agent V2 API.

Usage::

    from src.sdk.client import SCeQTLClient

    client = SCeQTLClient("http://localhost:8000")
    response = client.query("Find brain Alzheimer datasets")
    print(response.summary)
    print(f"{response.total_count} results from {response.provenance.data_sources}")

    # Export results
    client.export("Find brain data", format="csv", output="results.csv")
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore


@dataclass
class Provenance:
    original_query: str = ""
    parsed_intent: str = ""
    sql_executed: str = ""
    sql_method: str = ""
    execution_time_ms: float = 0.0
    data_sources: list[str] | None = None
    fusion_stats: dict[str, Any] | None = None
    ontology_expansions: list[dict] | None = None

    def __post_init__(self):
        self.data_sources = self.data_sources or []
        self.fusion_stats = self.fusion_stats or {}
        self.ontology_expansions = self.ontology_expansions or []


@dataclass
class QueryResponse:
    summary: str = ""
    results: list[dict] | None = None
    total_count: int = 0
    displayed_count: int = 0
    provenance: Provenance | None = None
    suggestions: list[dict] | None = None
    charts: list[dict] | None = None
    error: str | None = None

    def __post_init__(self):
        self.results = self.results or []
        self.suggestions = self.suggestions or []
        self.charts = self.charts or []


class SCeQTLClient:
    """
    Python client for SCeQTL-Agent V2 API.

    Args:
        base_url: API base URL (e.g. "http://localhost:8000")
        timeout: Request timeout in seconds
    """

    def __init__(self, base_url: str = "http://localhost:8000", timeout: float = 120.0):
        if httpx is None:
            raise ImportError("httpx is required: pip install httpx")
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(base_url=self.base_url, timeout=timeout)
        self._session_id = f"sdk-{id(self)}"

    def close(self):
        """Close the HTTP client."""
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # ── Core Methods ──

    def health(self) -> dict:
        """Check API health status."""
        r = self.client.get("/api/v1/health")
        r.raise_for_status()
        return r.json()

    def query(
        self,
        query_text: str,
        session_id: str | None = None,
        limit: int = 20,
    ) -> QueryResponse:
        """
        Send a natural language query.

        Args:
            query_text: Query in English or Chinese
            session_id: Session ID for multi-turn context
            limit: Max results to return

        Returns:
            QueryResponse with summary, results, provenance
        """
        r = self.client.post(
            "/api/v1/query",
            json={
                "query": query_text,
                "session_id": session_id or self._session_id,
                "limit": limit,
            },
        )
        r.raise_for_status()
        data = r.json()

        prov_data = data.get("provenance", {})
        provenance = Provenance(
            original_query=prov_data.get("original_query", ""),
            parsed_intent=prov_data.get("parsed_intent", ""),
            sql_executed=prov_data.get("sql_executed", ""),
            sql_method=prov_data.get("sql_method", ""),
            execution_time_ms=prov_data.get("execution_time_ms", 0),
            data_sources=prov_data.get("data_sources", []),
            fusion_stats=prov_data.get("fusion_stats", {}),
            ontology_expansions=prov_data.get("ontology_expansions", []),
        )

        return QueryResponse(
            summary=data.get("summary", ""),
            results=data.get("results", []),
            total_count=data.get("total_count", 0),
            displayed_count=data.get("displayed_count", 0),
            provenance=provenance,
            suggestions=data.get("suggestions", []),
            charts=data.get("charts", []),
            error=data.get("error"),
        )

    def entity(self, id_value: str) -> dict | None:
        """
        Look up an entity by ID (GSE*, PRJNA*, PMID, DOI, etc).

        Returns entity dict or None if not found.
        """
        r = self.client.get(f"/api/v1/entity/{id_value}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    def stats(self) -> dict:
        """Get database statistics overview."""
        r = self.client.get("/api/v1/stats")
        r.raise_for_status()
        return r.json()

    def autocomplete(self, field: str, prefix: str, limit: int = 10) -> list[dict]:
        """Get autocomplete suggestions for a field value."""
        r = self.client.get(
            "/api/v1/autocomplete",
            params={"field": field, "prefix": prefix, "limit": limit},
        )
        r.raise_for_status()
        return r.json().get("values", [])

    def resolve_ontology(self, term: str, field: str = "tissue") -> dict:
        """Resolve a term through the ontology pipeline."""
        r = self.client.get(
            "/api/v1/ontology/resolve",
            params={"term": term, "field": field},
        )
        r.raise_for_status()
        return r.json()

    # ── Export Methods ──

    def export(
        self,
        query_text: str,
        format: str = "csv",
        output: str | Path | None = None,
        limit: int = 200,
    ) -> bytes:
        """
        Export query results to file.

        Args:
            query_text: Query text
            format: "csv", "json", or "bibtex"
            output: File path to write (optional)
            limit: Max results to export

        Returns:
            Raw bytes of the export
        """
        r = self.client.post(
            "/api/v1/export",
            json={
                "query": query_text,
                "session_id": self._session_id,
                "format": format,
                "limit": limit,
            },
        )
        r.raise_for_status()
        data = r.content

        if output:
            Path(output).write_bytes(data)

        return data

    def schema(self) -> dict:
        """Get database schema summary."""
        r = self.client.get("/api/v1/schema")
        r.raise_for_status()
        return r.json()
