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
import re
from pathlib import Path

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


# Phase 28.G — extract a plain DB-value term from a SQL-fragment-style
# umbrella entry. Returns None when the fragment isn't a recognised shape.
#
# Recognises:
#   disease LIKE '%cancer%'           → "cancer"
#   disease LIKE "%neoplasm%"         → "neoplasm"
#   disease_category=neoplasm          → "neoplasm"
#   disease_category = 'neoplasm'      → "neoplasm"
_LIKE_FRAGMENT_RE = re.compile(
    r"""^\s*\w+\s+LIKE\s+['"]\s*%([^%'"\\]+?)%\s*['"]\s*$""",
    re.IGNORECASE,
)
_EQ_FRAGMENT_RE = re.compile(
    r"""^\s*\w+\s*=\s*['"]?([\w\-\s]+?)['"]?\s*$""",
)


def _extract_term_from_sql_fragment(fragment: str) -> str | None:
    """Pull the searchable substring out of an umbrella YAML SQL fragment."""
    m = _LIKE_FRAGMENT_RE.match(fragment)
    if m:
        return m.group(1).strip()
    m = _EQ_FRAGMENT_RE.match(fragment)
    if m and ("=" in fragment):
        return m.group(1).strip()
    return None


# Phase 32 F14: gate against contaminating expansion display via
# unfortunate substring matches. "ALL" matched "smALL cell lung",
# "ALLergy", "ALLergic dermatitis"; "AML" matched "anti-AMyLoid" etc.
# Short (≤4 char) abbreviations and all-uppercase tokens are dropped
# from the `LIKE '%term%'` direct-DB lookup but retained for the
# precise ontology cache lookups.
def _is_safe_for_substring_match(term: str) -> bool:
    """Return True iff this term is OK to use in a `LIKE '%term%'` scan.

    Rejects short tokens and acronym-style abbreviations whose
    substring match is likely to drag in unrelated rows.
    """
    if not term:
        return False
    s = term.strip()
    if len(s) <= 4:
        return False
    # All-uppercase + no whitespace usually means abbreviation (PBMC,
    # PDAC, NSCLC). For these, the exact/synonym path is enough.
    if s.upper() == s and " " not in s:
        return False
    return True


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
        umbrella_yaml_path: str | Path | None = None,
    ):
        self.cache = OntologyCache(cache_path)
        self.llm = llm
        self.expand_by_default = expand_by_default
        self.max_expansion = max_expansion

        # runtime resolution cache (avoid repeated lookups within a session)
        self._session_cache: dict[str, ResolvedEntity] = {}

        # Phase 28.F — per-instance caches for the DB-hitting hot paths in
        # umbrella expansion. Each umbrella child (e.g. "type 1 diabetes")
        # triggers exact/synonym/fuzzy + per-id value-map + direct LIKE
        # lookups; with 8+ children per umbrella that's 30+ SQLite queries
        # per resolve(). The ontology DB is read-only at runtime so these
        # caches never need invalidation — clear them via `clear_session_cache()`.
        self._lookup_exact_cache: dict[tuple[str, str | None], dict | None] = {}
        self._lookup_synonym_cache: dict[str, dict | None] = {}
        self._lookup_fuzzy_cache: dict[tuple[str, int], list[dict]] = {}
        self._db_values_raw_cache: dict[tuple[str, str], list[tuple[str, int]]] = {}
        self._direct_db_rows_cache: dict[tuple[str, str], list[tuple[str, str, int]]] = {}
        # cache-hit counters for telemetry / tests
        self._cache_stats: dict[str, int] = {
            "lookup_exact_hits": 0, "lookup_exact_misses": 0,
            "lookup_synonym_hits": 0, "lookup_synonym_misses": 0,
            "lookup_fuzzy_hits": 0, "lookup_fuzzy_misses": 0,
            "db_values_hits": 0, "db_values_misses": 0,
            "direct_db_hits": 0, "direct_db_misses": 0,
        }

        # Phase 28.D — merge biologist-curated umbrella YAML into the
        # hardcoded `UMBRELLA_TERMS` dict. The YAML has 39 entries
        # spanning tissues / diseases / cell_types and was curated in
        # Phase 24; without this step the resolver only sees the ~15
        # hardcoded entries below.
        if umbrella_yaml_path is None:
            project_root = Path(__file__).resolve().parents[2]
            default_yaml = project_root / "docs" / "umbrella_terms_v1.yaml"
            if default_yaml.exists():
                umbrella_yaml_path = default_yaml
        if umbrella_yaml_path is not None:
            loaded = self._load_umbrella_yaml(Path(umbrella_yaml_path))
            if loaded:
                # Per-instance override; do NOT mutate the class attribute
                # (so unit tests with a different YAML stay isolated).
                merged = dict(self.UMBRELLA_TERMS)
                merged.update(loaded)
                self.UMBRELLA_TERMS = merged  # type: ignore[misc]
                logger.info(
                    "OntologyResolver: merged %d umbrella terms from %s "
                    "(total now %d)",
                    len(loaded), umbrella_yaml_path, len(merged),
                )

    @staticmethod
    def _load_umbrella_yaml(path: Path) -> dict[str, list[str]]:
        """Parse the biologist-curated YAML into the flat
        `{umbrella_term: [child_terms]}` shape used by the resolver.

        For each section (tissues / diseases / cell_types):
          - read the `broad` list when `final_recommendation == 'broad'`
            (the curator's default), else read `narrow`
          - dedupe + lowercase the umbrella key so lookups are robust to
            "Brain" / "brain" / "BRAIN" variation

        On any error (file missing, malformed YAML, etc.) return an empty
        dict — the resolver will silently fall back to the hardcoded list.
        """
        try:
            import yaml  # local import: optional dep when YAML not present
        except ImportError:
            logger.warning("OntologyResolver: PyYAML not installed; umbrella YAML skipped")
            return {}
        if not path.exists():
            return {}
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception as e:
            logger.warning("OntologyResolver: failed to parse %s: %s", path, e)
            return {}

        out: dict[str, list[str]] = {}
        for section_key in ("tissues", "diseases", "cell_types"):
            section = doc.get(section_key) or {}
            if not isinstance(section, dict):
                continue
            for raw_term, entry in section.items():
                if not isinstance(entry, dict):
                    continue
                rec = (entry.get("final_recommendation") or "broad").lower()
                key_list = "narrow" if rec == "narrow" else "broad"
                children = entry.get(key_list) or entry.get("broad") or entry.get("narrow") or []
                if not isinstance(children, list):
                    continue
                # Phase 28.G — the biologist YAML for cancer/leukemia/etc.
                # stores expansion as SQL fragments (e.g.
                # "disease LIKE '%cancer%'", "disease_category=neoplasm").
                # Filtering them out drops the entire umbrella. Instead,
                # extract the *substring* / *value* so downstream
                # `_direct_db_lookup` can match it via LIKE '%term%'.
                cleaned: list[str] = []
                for x in children:
                    c = str(x).strip()
                    if not c:
                        continue
                    extracted = _extract_term_from_sql_fragment(c)
                    if extracted is not None:
                        cleaned.append(extracted)
                    elif " LIKE " not in c and "=" not in c and "'" not in c:
                        cleaned.append(c)
                    # else: unparseable fragment — drop silently
                if not cleaned:
                    continue
                # YAML keys use underscores ("bone_marrow"); the agent
                # passes natural-language ("bone marrow"). Index both.
                key = str(raw_term).lower().strip()
                out[key] = cleaned
                if "_" in key:
                    out[key.replace("_", " ")] = cleaned
        return out

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
        """Resolve a pre-built BioEntity.

        IMPORTANT: the resolver caches by (field_type, term, expand).
        The cached ResolvedEntity carries an `.original` attribute that
        was set from the *first* caller. Downstream code (engine.py)
        reads `ent.original.negated` to decide whether to apply a
        positive predicate, so a stale cached entry from a previous
        non-negated query would force the negated entity into a
        positive predicate. We dataclass-copy the cached entry and
        substitute the caller's `entity` to keep the `.negated` flag
        and any other per-call attributes accurate.
        """
        if expand is None:
            expand = self.expand_by_default
        field_type = entity.entity_type
        term = entity.normalized_value or entity.text
        cache_key = f"{field_type}:{term.lower()}:{expand}"
        if cache_key in self._session_cache:
            cached = self._session_cache[cache_key]
            from dataclasses import replace as _dc_replace
            return _dc_replace(cached, original=entity)

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
        self._lookup_exact_cache.clear()
        self._lookup_synonym_cache.clear()
        self._lookup_fuzzy_cache.clear()
        self._db_values_raw_cache.clear()
        self._direct_db_rows_cache.clear()
        for k in self._cache_stats:
            self._cache_stats[k] = 0

    # ─────────── Phase 28.F: cached cache-layer wrappers ───────────

    def _cached_lookup_exact(
        self, label: str, preferred_source: str | None = None
    ) -> dict | None:
        key = (label.lower(), preferred_source)
        if key in self._lookup_exact_cache:
            self._cache_stats["lookup_exact_hits"] += 1
            return self._lookup_exact_cache[key]
        self._cache_stats["lookup_exact_misses"] += 1
        row = self.cache.lookup_exact(label, preferred_source=preferred_source)
        self._lookup_exact_cache[key] = row
        return row

    def _cached_lookup_synonym(self, term: str) -> dict | None:
        key = term.lower()
        if key in self._lookup_synonym_cache:
            self._cache_stats["lookup_synonym_hits"] += 1
            return self._lookup_synonym_cache[key]
        self._cache_stats["lookup_synonym_misses"] += 1
        row = self.cache.lookup_synonym(term)
        self._lookup_synonym_cache[key] = row
        return row

    def _cached_lookup_fuzzy(self, term: str, limit: int = 5) -> list[dict]:
        key = (term.lower(), limit)
        if key in self._lookup_fuzzy_cache:
            self._cache_stats["lookup_fuzzy_hits"] += 1
            return self._lookup_fuzzy_cache[key]
        self._cache_stats["lookup_fuzzy_misses"] += 1
        rows = self.cache.lookup_fuzzy(term, limit=limit)
        self._lookup_fuzzy_cache[key] = rows
        return rows

    def _cached_db_values_raw(
        self, ontology_id: str, field_name: str
    ) -> list[tuple[str, int]]:
        key = (ontology_id, field_name)
        if key in self._db_values_raw_cache:
            self._cache_stats["db_values_hits"] += 1
            return self._db_values_raw_cache[key]
        self._cache_stats["db_values_misses"] += 1
        rows = self.cache.get_db_values(ontology_id, field_name)
        self._db_values_raw_cache[key] = rows
        return rows

    def _cached_direct_db_rows(
        self, term: str, field_type: str
    ) -> list[tuple[str, str, int]]:
        key = (term.lower(), field_type)
        if key in self._direct_db_rows_cache:
            self._cache_stats["direct_db_hits"] += 1
            return self._direct_db_rows_cache[key]
        self._cache_stats["direct_db_misses"] += 1
        rows = self.cache.conn.execute(
            "SELECT ontology_id, db_value, sample_count FROM ontology_value_map "
            "WHERE field_name = ? AND db_value LIKE ? "
            "ORDER BY sample_count DESC LIMIT 20",
            [field_type, f"%{term}%"],
        ).fetchall()
        # materialize as plain tuples so the cached list is small and pickle-safe
        out = [(r["ontology_id"], r["db_value"], r["sample_count"]) for r in rows]
        self._direct_db_rows_cache[key] = out
        return out

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
        #
        # Phase 32 fix — substring matching here was too greedy:
        # "pancreatic cancer" → caught by uterm "cancer" → expanded to the
        # entire cancer umbrella (~50k samples). Likewise "alzheimer's disease"
        # would have matched anything containing "disease". We now require
        # an *exact* (case-folded, whitespace-stripped) match; the precise
        # MONDO/EFO entry for "pancreatic cancer" is then picked up in
        # Step 1 below.
        umbrella_key = term.lower().strip()
        child_terms = self.UMBRELLA_TERMS.get(umbrella_key)
        if child_terms is not None:
            resolved = self._resolve_umbrella(entity, field_type, child_terms)
            if resolved and resolved.db_values:
                return resolved

        # Step 1: Exact label match (prefer the expected ontology source)
        expected_source = FIELD_ONTOLOGY_MAP.get(field_type, "")
        onto_row = self._cached_lookup_exact(term, preferred_source=expected_source)
        if onto_row:
            method = "exact"
            return self._build_resolved(entity, onto_row, field_type, expand, method)

        # Step 2: Synonym match
        onto_row = self._cached_lookup_synonym(term)
        if onto_row:
            method = "synonym"
            return self._build_resolved(entity, onto_row, field_type, expand, method)

        # Step 3: FTS5 fuzzy match
        fuzzy_results = self._cached_lookup_fuzzy(term, limit=5)
        if fuzzy_results:
            # Pick the best-ranked fuzzy result
            # Prefer terms from the expected ontology source
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
            # Try exact match for each child (cache-backed)
            onto_row = self._cached_lookup_exact(child)
            if not onto_row:
                onto_row = self._cached_lookup_synonym(child)
            if not onto_row:
                fuzzy = self._cached_lookup_fuzzy(child, limit=1)
                if fuzzy:
                    onto_row = fuzzy[0]

            if onto_row:
                if first_onto is None:
                    first_onto = self._row_to_term(onto_row)
                # Get DB values for this child
                child_vals = self._get_db_values(onto_row["ontology_id"], field_type, "umbrella")
                all_db_values.extend(child_vals)

            # Phase 32 F14: skip _direct_db_lookup for short abbreviations
            # like "ALL", "AML", "CML", "APL" — `LIKE '%ALL%'` matches
            # unrelated strings ("smALL cell lung", "ALLergic dermatitis",
            # "non-smALL cell"). The exact/synonym/fuzzy steps above
            # already cover legitimate abbreviation hits via the ontology
            # cache. Skip the LIKE-substring path when the term is short
            # or all-caps; keep it for full-text terms where substring
            # match is intentional (e.g. "acute myeloid leukemia").
            if _is_safe_for_substring_match(child):
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
        """Get DB values mapped to an ontology ID (cache-backed)."""
        raw = self._cached_db_values_raw(ontology_id, field_type)
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
        regardless of ontology resolution. Cache-backed (Phase 28.F).
        """
        rows = self._cached_direct_db_rows(term, field_type)
        return [
            DBValueMatch(
                raw_value=db_value,
                ontology_id=ontology_id,
                field_name=field_type,
                count=count,
                match_type="direct",
            )
            for ontology_id, db_value, count in rows
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
