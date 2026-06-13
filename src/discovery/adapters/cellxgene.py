"""CellXGene adapter."""

import time
from typing import Any

import httpx

from src.discovery.config import get_settings
from src.discovery.http_utils import request_with_retry
from src.discovery.models import DatasetResult, DiscoveryResult, QueryIntent
from src.discovery.adapters.base import BaseAdapter


class CellXGeneAdapter(BaseAdapter):
    """Adapter for CZ CELLxGENE Discover.

    Strategy: fetch all collections, cache locally, do keyword matching.
    CellXGene has ~372 collections, which is small enough to cache.
    """

    name = "cellxgene"
    _base_url = "https://api.cellxgene.cziscience.com/curation/v1"
    _cache: list[dict[str, Any]] | None = None
    _cache_timestamp: float = 0.0

    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = httpx.AsyncClient(timeout=self.settings.http_timeout)

    async def _get_collections(self) -> list[dict[str, Any]]:
        """Fetch all collections with caching."""
        now = time.time()
        ttl = self.settings.cellxgene_cache_ttl_seconds

        if (
            self._cache is not None
            and (now - self._cache_timestamp) < ttl
        ):
            return self._cache

        resp = await request_with_retry(
            lambda: self.client.get(f"{self._base_url}/collections")
        )
        resp.raise_for_status()
        self._cache = resp.json()
        self._cache_timestamp = now
        return self._cache

    def _match(self, intent: QueryIntent, collection: dict) -> bool:
        """Check if a collection matches the intent.

        When the intent specifies a tissue, we require *one of the collection's
        own ontology-derived tissue labels* to substring-match a requested
        tissue term — not just any field anywhere in the collection. This
        avoids multi-tissue atlas collections leaking through a strict
        tissue query (e.g. a pan-organ atlas matching a "gut" intent
        because its description mentions "gut" once among 20 tissues).

        When intent specifies a disease, the same constraint applies on the
        disease labels. Tech / keywords still match anywhere as a soft signal.
        """
        # Collect ontology labels per axis.
        col_tissue_labels = set()
        col_disease_labels = set()
        col_assay_labels = set()
        for dataset in collection.get("datasets", []):
            for tissue in dataset.get("tissue", []):
                lab = tissue.get("label", "").lower()
                if lab:
                    col_tissue_labels.add(lab)
            for disease in dataset.get("disease", []):
                lab = disease.get("label", "").lower()
                if lab:
                    col_disease_labels.add(lab)
            for assay in dataset.get("assay", []):
                lab = assay.get("label", "").lower()
                if lab:
                    col_assay_labels.add(lab)

        # Free-text fallback corpus (collection name + description).
        free_text = " ".join(
            [collection.get("name", ""), collection.get("description", "")]
        ).lower()

        def _matches_any(terms: list[str], labels: set[str]) -> bool:
            """Returns True if any requested term substring-matches any label."""
            for term in terms:
                t = term.lower().strip()
                if not t:
                    continue
                for lab in labels:
                    if t in lab or lab in t:
                        return True
            return False

        # Hard gate: when a collection has per-dataset ontology labels,
        # the intent's tissue / disease terms must match those labels (not
        # just appear in a description). For collections WITHOUT ontology
        # labels (e.g. brand-new ones or partial metadata), fall back to a
        # free-text substring check on name + description so we don't
        # silently filter them out.
        if intent.tissue:
            if col_tissue_labels:
                if not _matches_any(intent.tissue, col_tissue_labels):
                    return False
            else:
                # Labels missing — fall back to name/description text.
                if not any(t.lower() in free_text for t in intent.tissue if t):
                    return False
        if intent.disease:
            if col_disease_labels:
                if not _matches_any(intent.disease, col_disease_labels):
                    return False
            else:
                if not any(d.lower() in free_text for d in intent.disease if d):
                    return False

        # Soft signal: tech / keywords match anywhere (label or free text).
        soft_terms = list(intent.tech) + list(intent.keywords)
        if not (intent.tissue or intent.disease) and not soft_terms:
            return False

        if not (intent.tissue or intent.disease):
            # No hard gate fired: fall back to "any soft term matches anywhere".
            full_text = (
                free_text + " " + " ".join(col_tissue_labels)
                + " " + " ".join(col_disease_labels)
                + " " + " ".join(col_assay_labels)
            )
            return any(kw.lower() in full_text for kw in soft_terms)

        return True

    async def search(self, intent: QueryIntent, max_results: int = 20) -> DiscoveryResult:
        start_time = time.perf_counter()

        try:
            collections = await self._get_collections()
            matches = [
                c for c in collections if self._match(intent, c)
            ]

            # Sort by relevance: collections with more matching keywords first
            def relevance_score(col: dict) -> int:
                keywords = (
                    intent.disease
                    + intent.tissue
                    + intent.tech
                    + intent.keywords
                )
                texts: list[str] = []
                texts.append(col.get("name", ""))
                texts.append(col.get("description", ""))
                for dataset in col.get("datasets", []):
                    for tissue in dataset.get("tissue", []):
                        texts.append(tissue.get("label", ""))
                    for disease in dataset.get("disease", []):
                        texts.append(disease.get("label", ""))
                search_text = " ".join(texts).lower()
                return sum(
                    1 for kw in keywords if kw.lower() in search_text
                )

            matches.sort(key=relevance_score, reverse=True)
            total_found = len(matches)
            matches = matches[:max_results]

            results = []
            for col in matches:
                col_id = col.get("collection_id", "")
                col_url = col.get(
                    "collection_url",
                    f"https://cellxgene.cziscience.com/collections/{col_id}",
                )

                # Aggregate dataset info
                datasets = col.get("datasets", [])
                tissue_labels = set()
                disease_labels = set()
                organism_labels: list[str] = []
                for ds in datasets:
                    for t in ds.get("tissue", []):
                        tissue_labels.add(t.get("label", ""))
                    for d in ds.get("disease", []):
                        disease_labels.add(d.get("label", ""))
                    # Closes H-Q: populate organism from per-dataset
                    # metadata so the router-level species filter can
                    # see it. CellXGene typically reports one organism
                    # per dataset; we surface the *most common* one across
                    # the collection's datasets (a collection that mixes
                    # organisms still reports its dominant species).
                    for o in ds.get("organism", []):
                        lab = o.get("label", "").strip()
                        if lab:
                            organism_labels.append(lab)

                # Most-common organism wins; ``None`` if no signal.
                organism: str | None = None
                if organism_labels:
                    from collections import Counter as _Counter

                    organism = _Counter(organism_labels).most_common(1)[0][0]

                desc_parts = [col.get("description", "")]
                if tissue_labels:
                    desc_parts.append(f"Tissues: {', '.join(tissue_labels)}")
                if disease_labels:
                    desc_parts.append(f"Diseases: {', '.join(disease_labels)}")

                results.append(
                    DatasetResult(
                        id=col_id,
                        title=col.get("name", "Unnamed Collection"),
                        description=" | ".join(desc_parts),
                        organism=organism,
                        sample_count=len(datasets),
                        date=None,
                        source_db="CellXGene",
                        source_url=col_url,
                        download_url=None,
                        data_type="scRNA-seq",
                    )
                )

            latency_ms = int((time.perf_counter() - start_time) * 1000)
            return DiscoveryResult(
                source=self.name,
                total_found=total_found,
                results=results,
                query_url="https://cellxgene.cziscience.com/",
                latency_ms=latency_ms,
            )

        except Exception as exc:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            return DiscoveryResult(
                source=self.name,
                total_found=0,
                results=[],
                error=f"{type(exc).__name__}: {str(exc)[:200]}",
                latency_ms=latency_ms,
            )

    @property
    def is_available(self) -> bool:
        return True
