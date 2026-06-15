"""SRA adapter using NCBI E-utilities."""

import time
import urllib.parse
from typing import Any

import httpx

from src.discovery.config import get_settings
from src.discovery.http_utils import request_with_retry
from src.discovery.models import DatasetResult, DiscoveryResult, QueryIntent
from src.discovery.adapters.base import BaseAdapter
from src.discovery.adapters.geo import _get_ncbi_semaphore


class SraAdapter(BaseAdapter):
    """Adapter for SRA (Sequence Read Archive) via NCBI E-utilities.

    Note: SRA metadata is very sparse. This adapter is a secondary source.
    """

    name = "sra"
    _base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = httpx.AsyncClient(timeout=self.settings.http_timeout)

    def _build_term(self, intent: QueryIntent) -> str:
        parts = []
        keywords = []

        if intent.disease:
            keywords.extend(intent.disease)
        if intent.tissue:
            keywords.extend(intent.tissue)
        if intent.tech:
            keywords.extend(intent.tech)
        # Most user queries flow into `keywords` (the free-text bucket) when
        # the intent parser can't classify them as a known tissue / disease /
        # technology. Without this branch, SRA only ever searches for the
        # organism + strategy — useless. Include up to 3 keywords to avoid
        # the URL exploding past NCBI's 8k-char limit.
        if intent.keywords:
            keywords.extend(intent.keywords[:3])

        if keywords:
            keyword_str = " OR ".join(f'"{kw}"' for kw in keywords)
            parts.append(f"({keyword_str})")

        if intent.species:
            species_str = " OR ".join(
                f'"{sp}"[Organism]' for sp in intent.species
            )
            parts.append(f"({species_str})")

        parts.append('"rna seq"[Strategy]')
        return " AND ".join(parts)

    async def _ncbi_get(self, endpoint: str, params: dict[str, Any]) -> dict:
        if self.settings.ncbi_api_key:
            params["api_key"] = self.settings.ncbi_api_key
        if self.settings.ncbi_email:
            params["email"] = self.settings.ncbi_email

        url = f"{self._base_url}/{endpoint}"
        sem = _get_ncbi_semaphore()
        async with sem:
            resp = await request_with_retry(
                lambda: self.client.get(url, params=params)
            )
            resp.raise_for_status()
            return resp.json()

    async def search(self, intent: QueryIntent, max_results: int = 20) -> DiscoveryResult:
        start_time = time.perf_counter()
        term = self._build_term(intent)

        try:
            data = await self._ncbi_get(
                "esearch.fcgi",
                {
                    "db": "sra",
                    "term": term,
                    "retmax": max_results,
                    "retmode": "json",
                    "sort": "date",
                },
            )
            uids = data.get("esearchresult", {}).get("idlist", [])
            total_found = int(
                data.get("esearchresult", {}).get("count", len(uids))
            )

            if not uids:
                return DiscoveryResult(
                    source=self.name,
                    total_found=total_found,
                    results=[],
                    query_url=f"{self._base_url}/esearch.fcgi?db=sra&term={urllib.parse.quote(term)}",
                    latency_ms=int(
                        (time.perf_counter() - start_time) * 1000
                    ),
                )

            summary_data = await self._ncbi_get(
                "esummary.fcgi",
                {"db": "sra", "id": ",".join(uids), "retmode": "json"},
            )
            summaries = summary_data.get("result", {})

            results = []
            for uid in uids:
                info = summaries.get(uid)
                if not info or not isinstance(info, dict):
                    continue

                exp_xml = info.get("expxml", "")
                title = info.get("title", "")
                if not title and "<Title>" in exp_xml:
                    title = exp_xml.split("<Title>")[1].split("</Title>")[0]

                accession = info.get("accession", "")
                if not accession:
                    runs = info.get("runs", "")
                    # NCBI esummary returns runs as XML fragments shaped like:
                    #   <Run acc="SRRnnnnnnnn" ...
                    # Older versions of this adapter looked for 'accession="'
                    # which never matches — every SRA result was silently
                    # dropped.
                    if ' acc="' in runs:
                        accession = runs.split(' acc="')[1].split('"')[0]

                # Also try to pull a study accession (SRP/PRJ) from expxml.
                if not accession and exp_xml:
                    for prefix in ("<Study acc=\"", "<Bioproject>"):
                        if prefix in exp_xml:
                            tail = exp_xml.split(prefix, 1)[1]
                            cand = tail.split('"', 1)[0] if "<Study" in prefix else tail.split("<", 1)[0]
                            if cand:
                                accession = cand.strip()
                                break

                if not accession:
                    continue

                # esummary buries organism inside expxml as
                #   <Organism ScientificName="Homo sapiens" .../>
                organism = info.get("organism") or None
                if not organism and exp_xml and 'ScientificName="' in exp_xml:
                    organism = exp_xml.split('ScientificName="')[1].split('"')[0]

                results.append(
                    DatasetResult(
                        id=accession,
                        title=title or f"SRA {accession}",
                        description=None,
                        organism=organism,
                        sample_count=None,
                        date=None,
                        source_db=self.name.upper(),
                        source_url=f"https://www.ncbi.nlm.nih.gov/sra/?term={accession}",
                        download_url=None,
                        data_type="RNA-Seq",
                    )
                )

            latency_ms = int((time.perf_counter() - start_time) * 1000)
            return DiscoveryResult(
                source=self.name,
                total_found=total_found,
                results=results,
                query_url=f"{self._base_url}/esearch.fcgi?db=sra&term={urllib.parse.quote(term)}",
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
