"""
Ontology Resolution Engine

5-step resolution pipeline:
1. Exact label match
2. Synonym match
3. FTS5 fuzzy match
4. LLM-assisted disambiguation (when available)
5. Fallback to free text

Integrates with OntologyCache for fast local lookups and
maps user terms to actual database values via ontology expansion.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from ..core.models import (
    BioEntity,
    DBValueMatch,
    OntologyTerm,
    ResolvedEntity,
)
from ..core.interfaces import ILLMClient
from .cache import OntologyCache

logger = logging.getLogger(__name__)

# field_type → ontology source mapping
FIELD_ONTOLOGY_MAP: dict[str, str] = {
    "tissue": "UBERON",
    "disease": "MONDO",
    "cell_type": "CL",
    "assay": "EFO",
}


class OntologyResolver:
    """
    Maps user terms to standard ontology IDs and expands to database values.

    Usage::

        resolver = OntologyResolver(cache_path="data/ontologies/ontology_cache.db")
        resolved = resolver.resolve("brain", "tissue", expand=True)
        # resolved.db_values → [("brain", 25432), ("cerebral cortex", 3891), ...]
    """

    def __init__(
        self,
        cache_path: str | Path,
        llm: ILLMClient | None = None,
        expand_by_default: bool = True,
        max_expansion: int = 30,
    ):
        self.cache = OntologyCache(cache_path)
        self.llm = llm
        self.expand_by_default = expand_by_default
        self.max_expansion = max_expansion

        # runtime resolution cache (avoid repeated lookups within a session)
        self._session_cache: dict[str, ResolvedEntity] = {}

    def close(self):
        self.cache.close()

    # ─────────── main entry point ───────────

    def resolve(
        self,
        term: str,
        field_type: str,
        expand: bool | None = None,
    ) -> ResolvedEntity:
        """
        Resolve a user term through the 5-step pipeline.

        Args:
            term: user-provided text (e.g. "brain", "大脑", "cerebral")
            field_type: "tissue" | "disease" | "cell_type" | "assay"
            expand: whether to expand to child/descendant terms

        Returns:
            ResolvedEntity with ontology_term, db_values, etc.
        """
        if expand is None:
            expand = self.expand_by_default

        cache_key = f"{field_type}:{term.lower()}:{expand}"
        if cache_key in self._session_cache:
            return self._session_cache[cache_key]

        # Create the original BioEntity
        bio_entity = BioEntity(
            text=term,
            entity_type=field_type,
            normalized_value=term,
        )

        resolved = self._resolve_pipeline(bio_entity, field_type, expand)

        self._session_cache[cache_key] = resolved
        return resolved

    def resolve_entity(
        self,
        entity: BioEntity,
        expand: bool | None = None,
    ) -> ResolvedEntity:
        """Resolve a pre-built BioEntity."""
        if expand is None:
            expand = self.expand_by_default
        field_type = entity.entity_type
        term = entity.normalized_value or entity.text
        cache_key = f"{field_type}:{term.lower()}:{expand}"
        if cache_key in self._session_cache:
            return self._session_cache[cache_key]

        resolved = self._resolve_pipeline(entity, field_type, expand)
        self._session_cache[cache_key] = resolved
        return resolved

    def resolve_all(
        self,
        entities: list[BioEntity],
        expand: bool | None = None,
    ) -> list[ResolvedEntity]:
        """Resolve a list of entities."""
        return [self.resolve_entity(e, expand) for e in entities
                if e.entity_type in FIELD_ONTOLOGY_MAP]

    def clear_session_cache(self):
        self._session_cache.clear()

    # ─────────── 5-step pipeline ───────────

    # Umbrella terms that should expand to their child concepts
    UMBRELLA_TERMS: dict[str, list[str]] = {
        # Tissue systems → component tissues
        "gastrointestinal tract": ["stomach", "intestine", "colon", "esophagus", "rectum", "duodenum", "ileum", "jejunum"],
        "central nervous system": ["brain", "spinal cord", "cerebral cortex", "hippocampus", "cerebellum", "thalamus"],
        "respiratory system": ["lung", "trachea", "bronchus", "nasal cavity", "larynx"],
        "urinary system": ["kidney", "bladder", "ureter", "urethra"],
        "reproductive system": ["ovary", "testis", "uterus", "prostate", "fallopian tube"],
        "musculoskeletal system": ["muscle", "bone", "cartilage", "tendon", "ligament"],
        "cardiovascular system": ["heart", "aorta", "artery", "vein"],
        # Cell type categories → specific cell types
        "immune cell": ["T cell", "B cell", "macrophage", "monocyte", "neutrophil", "NK cell", "dendritic cell", "mast cell"],
        "epithelial cell": ["epithelial cell", "keratinocyte", "alveolar cell", "goblet cell", "enterocyte"],
        "stromal cell": ["fibroblast", "myofibroblast", "mesenchymal stem cell", "pericyte"],
        "endothelial cell": ["endothelial cell", "vascular endothelial cell", "lymphatic endothelial cell"],
        # Disease categories
        "autoimmune disease": ["multiple sclerosis", "rheumatoid arthritis", "lupus", "type 1 diabetes", "Crohn disease", "ulcerative colitis", "psoriasis"],
        "neurodegenerative disease": ["Alzheimer disease", "Parkinson disease", "amyotrophic lateral sclerosis", "Huntington disease", "multiple sclerosis"],
        "cardiovascular disease": ["heart failure", "myocardial infarction", "atherosclerosis", "hypertension", "cardiomyopathy"],
        "metabolic disease": ["diabetes mellitus", "obesity", "non-alcoholic fatty liver disease", "metabolic syndrome"],
    }

    def _resolve_pipeline(
        self,
        entity: BioEntity,
        field_type: str,
        expand: bool,
    ) -> ResolvedEntity:
        """Execute the 5-step resolution pipeline."""
        term = entity.normalized_value or entity.text
        method = "fallback"

        # Step 0: Check umbrella terms (system-level / category terms)
        umbrella_key = term.lower()
        for uterm, child_terms in self.UMBRELLA_TERMS.items():
            if umbrella_key == uterm or umbrella_key in uterm or uterm in umbrella_key:
                resolved = self._resolve_umbrella(entity, field_type, child_terms)
                if resolved and resolved.db_values:
                    return resolved
                break

        # Step 1: Exact label match
        onto_row = self.cache.lookup_exact(term)
        if onto_row:
            method = "exact"
            return self._build_resolved(entity, onto_row, field_type, expand, method)

        # Step 2: Synonym match
        onto_row = self.cache.lookup_synonym(term)
        if onto_row:
            method = "synonym"
            return self._build_resolved(entity, onto_row, field_type, expand, method)

        # Step 3: FTS5 fuzzy match
        fuzzy_results = self.cache.lookup_fuzzy(term, limit=5)
        if fuzzy_results:
            # Pick the best-ranked fuzzy result
            # Prefer terms from the expected ontology source
            expected_source = FIELD_ONTOLOGY_MAP.get(field_type, "")
            best = None
            for fr in fuzzy_results:
                if fr["ontology_source"] == expected_source:
                    best = fr
                    break
            if best is None:
                best = fuzzy_results[0]

            method = "fuzzy"
            return self._build_resolved(entity, best, field_type, expand, method)

        # Step 4: LLM disambiguation (skipped if no LLM)
        # Reserved for future — would ask LLM to pick the best match
        # from a set of candidates when fuzzy is ambiguous.

        # Step 5: Fallback — no ontology match, use raw DB value lookup
        return self._build_fallback(entity, field_type)

    def _resolve_umbrella(
        self,
        entity: BioEntity,
        field_type: str,
        child_terms: list[str],
    ) -> ResolvedEntity | None:
        """Resolve an umbrella/category term by resolving each child term."""
        all_db_values: list[DBValueMatch] = []
        first_onto: OntologyTerm | None = None

        for child in child_terms:
            # Try exact match for each child
            onto_row = self.cache.lookup_exact(child)
            if not onto_row:
                onto_row = self.cache.lookup_synonym(child)
            if not onto_row:
                fuzzy = self.cache.lookup_fuzzy(child, limit=1)
                if fuzzy:
                    onto_row = fuzzy[0]

            if onto_row:
                if first_onto is None:
                    first_onto = self._row_to_term(onto_row)
                # Get DB values for this child
                child_vals = self._get_db_values(onto_row["ontology_id"], field_type, "umbrella")
                all_db_values.extend(child_vals)

            # Also do direct DB lookup
            direct = self._direct_db_lookup(child, field_type)
            all_db_values.extend(direct)

        if not all_db_values:
            return None

        all_db_values = self._dedup_db_values(all_db_values)
        total_count = sum(v.count for v in all_db_values)

        # Create a synthetic ontology term for the umbrella
        term_text = entity.normalized_value or entity.text
        umbrella_term = OntologyTerm(
            ontology_id=f"UMBRELLA:{term_text}",
            ontology_source="umbrella",
            label=term_text,
        )

        logger.debug(
            "Umbrella resolved '%s' → %d child terms, %d DB values, %d samples",
            term_text, len(child_terms), len(all_db_values), total_count,
        )

        return ResolvedEntity(
            original=entity,
            ontology_term=umbrella_term,
            db_values=all_db_values,
            total_sample_count=total_count,
        )

    # ─────────── result builders ───────────

    def _build_resolved(
        self,
        entity: BioEntity,
        onto_row: dict,
        field_type: str,
        expand: bool,
        method: str,
    ) -> ResolvedEntity:
        """Build a ResolvedEntity from an ontology cache row."""
        onto_term = self._row_to_term(onto_row)

        # Get direct DB value matches for this term
        db_values = self._get_db_values(onto_row["ontology_id"], field_type, "exact")

        # Expand to children/descendants
        expanded_terms: list[OntologyTerm] = []
        if expand:
            # Get child values
            child_values = self.cache.get_children_values(
                onto_row["ontology_id"], field_type, max_children=self.max_expansion
            )
            for child_id, db_val, cnt in child_values:
                db_values.append(DBValueMatch(
                    raw_value=db_val,
                    ontology_id=child_id,
                    field_name=field_type,
                    count=cnt,
                    match_type="hierarchy",
                ))

            # If few child values, try descendants (deeper)
            if len(db_values) < 5:
                desc_values = self.cache.get_descendant_values(
                    onto_row["ontology_id"], field_type, max_terms=self.max_expansion
                )
                existing_vals = {v.raw_value.lower() for v in db_values}
                for desc_id, db_val, cnt in desc_values:
                    if db_val.lower() not in existing_vals:
                        db_values.append(DBValueMatch(
                            raw_value=db_val,
                            ontology_id=desc_id,
                            field_name=field_type,
                            count=cnt,
                            match_type="hierarchy",
                        ))
                        existing_vals.add(db_val.lower())

        # Deduplicate and sort by count
        db_values = self._dedup_db_values(db_values)

        total_count = sum(v.count for v in db_values)

        logger.debug(
            "Resolved '%s' → %s (%s), %d DB values, %d samples [%s]",
            entity.text, onto_term.ontology_id, onto_term.label,
            len(db_values), total_count, method,
        )

        return ResolvedEntity(
            original=entity,
            ontology_term=onto_term,
            expanded_terms=expanded_terms,
            db_values=db_values,
            total_sample_count=total_count,
        )

    def _build_fallback(
        self,
        entity: BioEntity,
        field_type: str,
    ) -> ResolvedEntity:
        """Fallback when no ontology match is found — just use the raw term."""
        term = entity.normalized_value or entity.text

        # Try to find direct DB matches even without ontology
        db_values = self._direct_db_lookup(term, field_type)

        logger.debug(
            "Fallback for '%s' (%s): %d direct DB matches",
            entity.text, field_type, len(db_values),
        )

        return ResolvedEntity(
            original=entity,
            ontology_term=None,
            db_values=db_values,
            total_sample_count=sum(v.count for v in db_values),
        )

    # ─────────── helpers ───────────

    def _row_to_term(self, row: dict) -> OntologyTerm:
        """Convert a cache row to an OntologyTerm dataclass."""
        return OntologyTerm(
            ontology_id=row["ontology_id"],
            ontology_source=row["ontology_source"],
            label=row["label"],
            synonyms=json.loads(row["synonyms_json"]) if row.get("synonyms_json") else [],
            definition=row.get("definition", ""),
            parent_ids=json.loads(row["parent_ids_json"]) if row.get("parent_ids_json") else [],
            child_ids=json.loads(row["child_ids_json"]) if row.get("child_ids_json") else [],
        )

    def _get_db_values(
        self, ontology_id: str, field_type: str, match_type: str
    ) -> list[DBValueMatch]:
        """Get DB values mapped to an ontology ID."""
        raw = self.cache.get_db_values(ontology_id, field_type)
        return [
            DBValueMatch(
                raw_value=val,
                ontology_id=ontology_id,
                field_name=field_type,
                count=cnt,
                match_type=match_type,
            )
            for val, cnt in raw
        ]

    def _direct_db_lookup(self, term: str, field_type: str) -> list[DBValueMatch]:
        """
        Search ontology_value_map for DB values matching the term directly,
        regardless of ontology resolution.
        """
        rows = self.cache.conn.execute(
            "SELECT ontology_id, db_value, sample_count FROM ontology_value_map "
            "WHERE field_name = ? AND db_value LIKE ? "
            "ORDER BY sample_count DESC LIMIT 20",
            [field_type, f"%{term}%"],
        ).fetchall()
        return [
            DBValueMatch(
                raw_value=r["db_value"],
                ontology_id=r["ontology_id"],
                field_name=field_type,
                count=r["sample_count"],
                match_type="direct",
            )
            for r in rows
        ]

    @staticmethod
    def _dedup_db_values(values: list[DBValueMatch]) -> list[DBValueMatch]:
        """Deduplicate and sort DB values by count descending."""
        seen: dict[str, DBValueMatch] = {}
        for v in values:
            key = v.raw_value.lower()
            if key not in seen or v.count > seen[key].count:
                seen[key] = v
        return sorted(seen.values(), key=lambda x: x.count, reverse=True)
