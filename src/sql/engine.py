"""
SQL Generation & Parallel Execution

- JoinPathResolver: 自动推导JOIN路径
- SQLGenerator: 3候选生成 (模板 + 规则 + LLM)
- ParallelSQLExecutor: 并行执行 + 渐进降级
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..core.schema_config import SchemaConfig

from ..core.models import (
    ExecutionResult,
    JoinClause,
    JoinPlan,
    ParsedQuery,
    QueryComplexity,
    QueryFilters,
    QueryIntent,
    ResolvedEntity,
    SQLCandidate,
    ValidationResult,
)
from ..core.interfaces import ILLMClient
from ..dal.database import DatabaseAbstractionLayer

logger = logging.getLogger(__name__)


# Phase 27: distinctive scRNA-seq platform stems. When the parser emits a
# collapsed assay token ("10xv3", "smartseq2") the DB's canonical value is
# spaced/hyphenated ("10x 3' v3", "smart-seq2"), so `LIKE '%10xv3%'` misses.
# Mapping the token back to its family stem ("10x", "smart-seq") restores the
# match. Stems are deliberately distinctive — no bare "seq" which would match
# nearly every assay.
_ASSAY_FAMILY_STEMS: tuple[str, ...] = (
    "10x", "smart-seq", "smartseq", "drop-seq", "dropseq", "cel-seq", "celseq",
    "seq-well", "seqwell", "sci-rna", "sci-seq", "split-seq", "splitseq",
    "indrop", "mars-seq", "marsseq", "microwell", "rhapsody", "strt",
    "quartz-seq", "quartzseq", "plate-seq",
)


def _assay_family_stem(assay: str | None) -> str | None:
    """Return the platform-family stem an assay value begins with, else None.

    e.g. "10xv3" / "10x 3' v3" / "10X Genomics" → "10x";
         "smartseq2" / "Smart-seq2" → "smart-seq".
    """
    if not assay:
        return None
    s = assay.lower().strip()
    for stem in _ASSAY_FAMILY_STEMS:
        if s.startswith(stem):
            # Normalise the smartseq/dropseq/etc. variants to the hyphenated
            # form that appears in the DB, but only when distinctive.
            return stem.replace("smartseq", "smart-seq").replace("dropseq", "drop-seq")
    return None


# Phase 33: map natural-language age/life-stage words to the canonical
# `dev_stage_category` values present in the DB (adult / aged / juvenile /
# neonatal / embryonic / fetal). Used by the parser to populate
# ParsedQuery.filters.development_stages. Word-boundary matched, so "adult"
# won't fire inside "adultomimetic" etc. "old" is intentionally excluded (too
# ambiguous). Keys are lowercase whole words/phrases.
import re as _re_ds

_DEV_STAGE_KEYWORDS: dict[str, list[str]] = {
    "pediatric": ["juvenile", "neonatal"], "paediatric": ["juvenile", "neonatal"],
    "children": ["juvenile", "neonatal"], "child": ["juvenile", "neonatal"],
    "kids": ["juvenile", "neonatal"], "adolescent": ["juvenile"],
    "adolescents": ["juvenile"], "teen": ["juvenile"], "teenage": ["juvenile"],
    "juvenile": ["juvenile"], "young": ["juvenile"],
    "infant": ["neonatal"], "infants": ["neonatal"], "newborn": ["neonatal"],
    "newborns": ["neonatal"], "neonatal": ["neonatal"], "neonate": ["neonatal"],
    "neonates": ["neonatal"], "perinatal": ["neonatal"],
    "adult": ["adult"], "adults": ["adult"],
    "elderly": ["aged"], "aged": ["aged"], "geriatric": ["aged"], "senior": ["aged"],
    "fetal": ["fetal"], "foetal": ["fetal"], "fetus": ["fetal"], "foetus": ["fetal"],
    "prenatal": ["fetal", "embryonic"], "antenatal": ["fetal", "embryonic"],
    "embryonic": ["embryonic"], "embryo": ["embryonic"], "embryos": ["embryonic"],
    "embryonal": ["embryonic"],
}


def extract_dev_stage_categories(text: str) -> list[str]:
    """Return canonical dev_stage_category values implied by life-stage words in
    `text` (order-preserving, de-duplicated). Empty when none present.

    Guards against overloaded biology phrases: "embryonic/embryo" is skipped
    when "stem" appears (embryonic stem cell ≠ an age filter); "fetal" is
    skipped with "serum"/"bovine" (fetal bovine serum)."""
    if not text:
        return []
    words = set(_re_ds.findall(r"[a-z]+", text.lower()))
    out: list[str] = []
    for kw, cats in _DEV_STAGE_KEYWORDS.items():
        if kw not in words:
            continue
        if kw in ("embryonic", "embryo", "embryos", "embryonal") and "stem" in words:
            continue
        if kw in ("fetal", "foetal", "fetus", "foetus") and (
            "serum" in words or "bovine" in words or "fbs" in words
        ):
            continue
        for c in cats:
            if c not in out:
                out.append(c)
    return out


# ========== Fuzzy fallback for failed strict queries ==========

def _relax_sql_for_fuzzy(sql: str, params: list) -> tuple[str, list]:
    """Rewrite a strict SQL query to use LIKE-based fuzzy matching.

    Handles two patterns produced by the SQL generator (Phase 28.D):

    1. ``col = ?``       →  ``col LIKE ?``     (single-value equality)
    2. ``col IN (?,?…)`` →  ``(LOWER(col) LIKE ? OR LOWER(col) LIKE ? …)``
       (multi-value lists — what ontology-expanded queries emit)

    All string parameters are wrapped with ``%`` on each side; numeric
    parameters pass through. The fallback only kicks in if the original
    strict query returned 0 rows, so the cost is amortised.

    Pre-Phase-28.D only the first pattern was relaxed, which meant any
    query with `IN (...)` (i.e. most multi-entity ones) never benefited
    from fuzzy matching and honest-zero'd. See lvtongxuan Round 2
    audit Q02 / Q03 / Q06.
    """
    import re

    # Walk the SQL token by token, replacing relevant patterns.
    # We scan for `IN ( ?, ?, ... )` blocks first, then handle the
    # remaining `=` → `LIKE` in a second pass on the split segments.

    in_pat = re.compile(
        r"""
        (?P<col>[A-Za-z_][\w.]*)        # column name
        \s+IN\s*\(                       # IN (
        \s*(?P<qmarks>\?(?:\s*,\s*\?)*)  # ?, ?, ?
        \s*\)
        """,
        re.IGNORECASE | re.VERBOSE,
    )

    # We need to know how many params each `?` consumes so we can splice
    # the new params correctly. The original list order matches the
    # original `?` order in the SQL.
    qmark_count = sql.count("?")
    if qmark_count != len(params):
        # If the param count doesn't line up, fall back to the simple
        # `=` → `LIKE` transformation only.
        return _relax_eq_to_like(sql, params)

    # Map: position of `?` (0-indexed in the SQL) → param value
    # We rebuild the SQL by emitting segments separated by ?, replacing
    # `IN (?, ?, ...)` blocks atomically.
    out_chunks: list[str] = []
    out_params = []

    pos = 0  # cursor in sql
    qmark_idx = 0
    # Bug (Phase 37): `col IN (...)` also matches the `IN` inside `NOT IN (...)`,
    # capturing the keyword "NOT" as the column → `(LOWER(NOT) LIKE ?)`, a
    # `near ")"` syntax error that crashed the fuzzy fallback for any negated-set
    # query ("…not cell-line"). A negated IN must NOT be relaxed to an OR-of-LIKE
    # (that would also invert the semantics) — skip matches whose "column" is a
    # SQL keyword so the `NOT IN (?)` clause passes through verbatim.
    _kw = {"NOT", "AND", "OR", "WHERE", "ON", "IN", "SELECT"}
    matches = [m for m in in_pat.finditer(sql) if m.group("col").upper() not in _kw]
    for m in matches:
        # Emit the text up to the IN(
        head = sql[pos:m.start()]
        # Count how many ?s are in `head` — those each consume one param
        head_qm = head.count("?")
        for _ in range(head_qm):
            out_params.append(params[qmark_idx]); qmark_idx += 1
        out_chunks.append(head)

        col = m.group("col")
        n_q = m.group("qmarks").count("?")
        # Build the OR-of-LIKE block. Use LOWER(col) for case-insensitive
        # match; wrap each placeholder param with %.
        like_parts = [f"LOWER({col}) LIKE ?" for _ in range(n_q)]
        out_chunks.append(f"({' OR '.join(like_parts)})")
        for _ in range(n_q):
            p = params[qmark_idx]; qmark_idx += 1
            if isinstance(p, str):
                out_params.append(f"%{p.lower()}%")
            else:
                # Non-string in IN list is unusual; pass through as-is.
                out_params.append(p)

        pos = m.end()

    tail = sql[pos:]
    tail_qm = tail.count("?")
    for _ in range(tail_qm):
        out_params.append(params[qmark_idx]); qmark_idx += 1
    out_chunks.append(tail)

    intermediate_sql = "".join(out_chunks)

    # Now do the simple `=` → `LIKE` pass on whatever's left.
    final_sql, final_params = _relax_eq_to_like(intermediate_sql, out_params)
    return final_sql, final_params


def _relax_eq_to_like(sql: str, params: list) -> tuple[str, list]:
    """Inner helper: replace `col = ?` with `col LIKE ?` (string params
    only) and wrap each string param with %. Numeric params pass through
    untouched. This is the original Phase-27 fallback behaviour, kept as
    a building block for `_relax_sql_for_fuzzy`."""
    relaxed_parts: list[str] = []
    param_idx = 0
    for segment in sql.split("?"):
        relaxed_parts.append(segment)
        if param_idx < len(params):
            seg = segment.rstrip()
            # Only relax a *bare* equality `col = ?`. A comparison operator that
            # merely ends in '=' (`!=`, `<=`, `>=`) must not be rewritten to
            # ` LIKE ` — that produced malformed SQL like `col ! LIKE ?`.
            is_bare_eq = seg.endswith("=") and not seg.endswith(("!=", "<=", ">=", "<>"))
            if isinstance(params[param_idx], str) and is_bare_eq:
                last = relaxed_parts[-1]
                relaxed_parts[-1] = last[: last.rstrip().rfind("=")] + " LIKE "
            param_idx += 1
    relaxed_sql = "?".join(relaxed_parts)
    relaxed_params = [
        f"%{p}%" if isinstance(p, str) and not (p.startswith("%") and p.endswith("%")) else p
        for p in params
    ]
    return relaxed_sql, relaxed_params


# ========== 视图列名映射 (默认值) ==========
# v_sample_with_hierarchy 中部分列名与原表不同
_DEFAULT_VIEW_COLUMN_MAP: dict[str, str] = {
    "pk": "sample_pk",
    "source_database": "sample_source",
    "title": "project_title",
}

# 保持向后兼容
VIEW_COLUMN_MAP = _DEFAULT_VIEW_COLUMN_MAP


def _vc(field: str, use_view: bool, view_col_map: dict[str, str] | None = None) -> str:
    """将字段名映射为视图兼容的列名"""
    if use_view:
        m = view_col_map if view_col_map is not None else _DEFAULT_VIEW_COLUMN_MAP
        return m.get(field, field)
    return field


def _cell_count_col(table: str) -> str:
    """The per-table column holding a cell-count total, for aggregate SUMs.

    samples / *_with_hierarchy view → ``n_cells``; ``unified_projects`` →
    ``total_cells``; ``unified_series`` / ``unified_celltypes`` → ``cell_count``.
    Hardcoding ``n_cells`` made project/series STATISTICS emit ``no such column``.
    """
    if table == "unified_projects":
        return "total_cells"
    if table in ("unified_series", "unified_celltypes"):
        return "cell_count"
    return "n_cells"


# ========== 字段→表映射 (默认值) ==========

_DEFAULT_FIELD_TABLE: dict[str, str] = {
    # Projects
    "project_id": "unified_projects", "pmid": "unified_projects",
    "doi": "unified_projects", "citation_count": "unified_projects",
    "journal": "unified_projects", "project_title": "unified_projects",
    "submitter_organization": "unified_projects",
    # Series
    "series_id": "unified_series", "assay": "unified_series",
    "has_h5ad": "unified_series", "has_rds": "unified_series",
    "cell_count": "unified_series", "gene_count": "unified_series",
    "asset_h5ad_url": "unified_series", "explorer_url": "unified_series",
    # Samples
    "sample_id": "unified_samples", "tissue": "unified_samples",
    "disease": "unified_samples", "cell_type": "unified_samples",
    "sex": "unified_samples", "age": "unified_samples",
    "organism": "unified_samples", "ethnicity": "unified_samples",
    "development_stage": "unified_samples", "n_cells": "unified_samples",
    "individual_id": "unified_samples", "source_database": "unified_samples",
    "tissue_ontology_term_id": "unified_samples",
    "disease_ontology_term_id": "unified_samples",
    # Celltypes
    "cell_type_name": "unified_celltypes",
    "cell_type_ontology_term_id": "unified_celltypes",
}

# 保持向后兼容
FIELD_TABLE = _DEFAULT_FIELD_TABLE

# v_sample_with_hierarchy 包含的字段 (默认值)
_DEFAULT_VIEW_FIELDS = {
    "sample_pk", "sample_id", "sample_id_type", "sample_source",
    "organism", "tissue", "tissue_ontology_term_id", "tissue_general",
    "disease", "disease_ontology_term_id",
    "sex", "age", "age_unit", "development_stage", "ethnicity",
    "individual_id", "n_cells", "n_cell_types", "biological_identity_hash",
    # Standardized fields
    "tissue_standard", "tissue_system",
    "disease_standard", "disease_category",
    "organism_normalized", "organism_common",
    "sex_normalized", "sample_type",
    # Phase 38: canonical anatomical / lineage roll-ups (now exposed by the view)
    "tissue_standard_l1", "tissue_standard_leaf",
    "disease_standard_l1", "cell_type_standard", "cell_type_lineage",
    # Series
    "series_pk", "series_id", "series_title", "assay",
    "series_cell_count",
    # Projects
    "project_pk", "project_id", "project_title",
    "pmid", "doi", "citation_count",
}

# 保持向后兼容
VIEW_FIELDS = _DEFAULT_VIEW_FIELDS


# ========== Tier-1 indexed-equality fast path ===========================
#
# These maps tell the SQL builder "if the user said X, you can run an indexed
# equality (col=?) instead of a LIKE '%X%'". For known-good canonical terms
# this turns 20 s scans into 50 ms index seeks.
#
# Discovery: every value listed here is verified to occur in the corresponding
# *_standard / *_category / *_common column of the production DB.
# Missing or ambiguous terms fall back to the slower LIKE path.

_TISSUE_STANDARD_VALUES: set[str] = {
    "blood", "bone marrow", "PBMC", "peripheral blood", "liver", "skin",
    "breast", "iPSC", "brain", "lung", "heart", "kidney", "pancreas",
    "intestine", "stomach", "colon", "prostate", "ovary", "thyroid",
    "spleen", "testis", "adipose tissue", "muscle", "placenta",
    "eye", "retina", "esophagus",
}

_DISEASE_STANDARD_VALUES: set[str] = {
    "normal", "cancer", "COVID-19", "type 2 diabetes mellitus", "melanoma",
    "acute myeloid leukemia", "IgA nephropathy", "myelofibrosis",
    "Alzheimer disease", "Parkinson disease", "multiple sclerosis",
}

# Map user-friendly disease keyword → DB-standard value.
# Used when the parser already normalised "癌"/"tumor" → "cancer".
# Generic umbrella terms (cancer, tumor) map to the broader
# disease_category='neoplasm' rather than disease_standard='cancer' because
# users asking for "cancer" really want any neoplasm. Specific diseases
# (Alzheimer, COVID-19) map directly to disease_standard.
_DISEASE_KEYWORD_TO_CATEGORY: dict[str, str] = {
    # neoplasm
    "cancer": "neoplasm", "tumor": "neoplasm", "tumour": "neoplasm",
    "carcinoma": "neoplasm", "neoplasm": "neoplasm", "malignant": "neoplasm",
    "癌症": "neoplasm", "肿瘤": "neoplasm",

    # hematological (blood / leukaemia / lymphoma)
    "leukemia": "hematological", "leukaemia": "hematological",
    "lymphoma": "hematological", "myeloma": "hematological",
    "白血病": "hematological", "淋巴瘤": "hematological",
    "hematological": "hematological", "haematological": "hematological",
    "hematologic": "hematological", "hematological disease": "hematological",
    "blood cancer": "hematological", "blood cancers": "hematological",
    "血液病": "hematological", "血液系统疾病": "hematological",
    "血液肿瘤": "hematological",

    # autoimmune
    "autoimmune": "autoimmune", "autoimmune disease": "autoimmune",
    "lupus": "autoimmune", "rheumatoid arthritis": "autoimmune",
    "multiple sclerosis": "autoimmune",
    "自身免疫": "autoimmune",

    # infectious
    "infection": "infectious", "infectious disease": "infectious",
    "covid": "infectious", "covid-19": "infectious",
    "sars-cov-2": "infectious", "tuberculosis": "infectious",
    "hiv": "infectious", "viral": "infectious",
    "感染": "infectious",

    # metabolic / endocrine
    "diabetes": "metabolic_endocrine", "obesity": "metabolic_endocrine",
    "metabolic syndrome": "metabolic_endocrine",
    "metabolic disease": "metabolic_endocrine",
    "endocrine": "metabolic_endocrine",
    "糖尿病": "metabolic_endocrine", "代谢性疾病": "metabolic_endocrine",

    # neurological
    "neurological": "neurological",
    "neurological disease": "neurological",
    "neurodegenerative": "neurological",
    "neurodegenerative disease": "neurological",
    "alzheimer": "neurological", "alzheimer's": "neurological",
    "parkinson": "neurological", "parkinson's": "neurological",
    "stroke": "neurological", "epilepsy": "neurological",
    "神经系统疾病": "neurological", "神经退行性疾病": "neurological",
    "阿尔茨海默": "neurological", "帕金森": "neurological",

    # cardiovascular
    "cardiovascular": "cardiovascular",
    "cardiovascular disease": "cardiovascular",
    "heart disease": "cardiovascular",
    "myocardial infarction": "cardiovascular",
    "atherosclerosis": "cardiovascular",
    "心血管": "cardiovascular",

    # respiratory
    "respiratory": "respiratory", "asthma": "respiratory",
    "copd": "respiratory", "pneumonia": "respiratory",
    "呼吸系统疾病": "respiratory",

    # gastrointestinal
    "gastrointestinal": "gastrointestinal", "ibd": "gastrointestinal",
    "crohn": "gastrointestinal", "ulcerative colitis": "gastrointestinal",
    "消化系统疾病": "gastrointestinal", "炎症性肠病": "gastrointestinal",

    # genitourinary
    "kidney disease": "genitourinary", "renal disease": "genitourinary",
    "肾脏疾病": "genitourinary",

    # genetic / congenital
    "genetic disease": "genetic_congenital",
    "congenital": "genetic_congenital",
    "遗传病": "genetic_congenital",

    # ophthalmic
    "ophthalmic": "ophthalmic", "eye disease": "ophthalmic",
    "macular degeneration": "ophthalmic",

    # dermatological
    "skin disease": "dermatological", "psoriasis": "dermatological",
    "皮肤病": "dermatological",

    # psychiatric
    "psychiatric": "psychiatric", "depression": "psychiatric",
    "schizophrenia": "psychiatric", "autism": "psychiatric",
    "精神疾病": "psychiatric", "精神病": "psychiatric",

    # musculoskeletal
    "musculoskeletal": "musculoskeletal",
    "osteoarthritis": "musculoskeletal",
    "肌肉骨骼": "musculoskeletal",

    # normal / healthy
    "normal": "normal", "healthy": "normal", "control": "normal",
    "正常": "normal", "健康": "normal",
}

_DISEASE_KEYWORD_TO_STANDARD: dict[str, str] = {
    "normal": "normal",
    "alzheimer": "Alzheimer disease",
    "alzheimer's disease": "Alzheimer disease",
    "alzheimer disease": "Alzheimer disease",
    "parkinson": "Parkinson disease",
    "parkinson's disease": "Parkinson disease",
    "parkinson disease": "Parkinson disease",
    "covid": "COVID-19",
    "covid-19": "COVID-19",
    "diabetes": "type 2 diabetes mellitus",
    "melanoma": "melanoma",
    "leukemia": "acute myeloid leukemia",
    "multiple sclerosis": "multiple sclerosis",
}

# Phase 23-C: specific disease names should NOT silently widen to the
# whole disease_category umbrella. When the user asks for "COVID samples"
# they mean COVID-19, not all infectious diseases. When they ask for
# "leukemia" they mean leukemia samples, not all hematological diseases.
# Diseases listed here route to (disease_standard='X' OR disease LIKE
# '%keyword%') rather than disease_category='X'. Umbrella terms like
# "cancer" / "neurological" remain category-mapped.
#
# Each key is the lower-cased keyword (matching parser normalisation).
# Each value is the literal LIKE token to use ('' = use the key itself).
_SPECIFIC_DISEASE_LIKE: dict[str, str] = {
    "covid": "COVID",
    "covid-19": "COVID",
    "sars-cov-2": "SARS-CoV-2",
    "alzheimer": "alzheimer",
    "alzheimer disease": "alzheimer",
    "alzheimer's": "alzheimer",
    "alzheimer's disease": "alzheimer",
    "ad": "alzheimer",
    "阿尔茨海默": "alzheimer",
    "parkinson": "parkinson",
    "parkinson disease": "parkinson",
    "parkinson's": "parkinson",
    "parkinson's disease": "parkinson",
    "帕金森": "parkinson",
    "diabetes": "diabetes",
    "type 2 diabetes mellitus": "diabetes",
    "糖尿病": "diabetes",  # CN→EN: DB stores English names
    "leukemia": "leukemia",
    "leukaemia": "leukemia",
    "acute myeloid leukemia": "leukemia",
    "白血病": "leukemia",
    "lymphoma": "lymphoma",
    "淋巴瘤": "lymphoma",
    "myeloma": "myeloma",
    "clonal hematopoiesis": "clonal h",  # matches both American & British (ha/hae) spellings
    "clonal haematopoiesis": "clonal h",
    "克隆性造血": "clonal h",
    "melanoma": "melanoma",
    "黑色素瘤": "melanoma",
    "glioma": "glioma",
    "胶质瘤": "glioma",
    "multiple sclerosis": "multiple sclerosis",
    "ms": "multiple sclerosis",
    "lupus": "lupus",
    "rheumatoid arthritis": "rheumatoid arthritis",
    "tuberculosis": "tuberculosis",
    "hiv": "HIV",
    "asthma": "asthma",
    "copd": "COPD",
    "pneumonia": "pneumonia",
    "ibd": "inflammatory bowel",
    "crohn": "crohn",
    "ulcerative colitis": "ulcerative colitis",
    "炎症性肠病": "inflammatory bowel",
    "psoriasis": "psoriasis",
    "macular degeneration": "macular degeneration",
    "depression": "depression",
    "schizophrenia": "schizophrenia",
    "autism": "autism",
    "osteoarthritis": "osteoarthritis",
    "atherosclerosis": "atherosclerosis",
    "myocardial infarction": "myocardial infarction",
    "stroke": "stroke",
    "epilepsy": "epilepsy",
    "hepatocellular carcinoma": "hepatocellular carcinoma",
    "hcc": "hepatocellular carcinoma",
    "肝癌": "hepatocellular carcinoma",
    "lung cancer": "lung cancer",
    "肺癌": "lung cancer",
    "breast cancer": "breast cancer",
    "乳腺癌": "breast cancer",
    "colorectal cancer": "colorectal",
    "结直肠癌": "colorectal",
    "fibrosis": "fibrosis",
    "纤维化": "fibrosis",
    "glioblastoma": "glioblastoma",
    "胶质母细胞瘤": "glioblastoma",
}

# Phase 19-C: when a specific disease has a known umbrella category, querying
# for the disease should ALSO cover samples coded only under the category
# (e.g. "melanoma" samples include rows where disease_category='neoplasm'
# but disease_standard is null/different). This bridges the
# disease/category split in curation.
_DISEASE_STANDARD_TO_CATEGORY: dict[str, str] = {
    "melanoma": "neoplasm",
    "acute myeloid leukemia": "hematological",
    "multiple sclerosis": "autoimmune",
    "Alzheimer disease": "neurological",
    "Parkinson disease": "neurological",
    "COVID-19": "infectious",
    "type 2 diabetes mellitus": "metabolic",
}

# Some tissue keywords map to *multiple* DB-standard values — "blood" should
# include PBMC and peripheral blood, "intestine" should include colon /
# small intestine variants. We use a list-of-strings instead of a single
# string for these.
_TISSUE_KEYWORD_TO_STANDARD: dict[str, str | list[str]] = {
    "liver": "liver", "brain": "brain", "lung": "lung", "heart": "heart",
    "kidney": "kidney",
    # "blood" stays an umbrella that covers its specific subtypes —
    # users asking for "blood samples" generally want PBMC + peripheral
    # blood too. But asking specifically for "PBMC" should *not*
    # silently widen to "peripheral blood": those are distinct DB
    # categories with different cell preps and the gold oracle treats
    # them as separate.
    "blood": ["blood", "PBMC", "peripheral blood"],
    "pbmc": "PBMC",
    "peripheral blood": "peripheral blood",
    "bone marrow": "bone marrow",
    "skin": "skin",
    "intestine": ["intestine", "colon"],
    "colon": "colon",
    "pancreas": "pancreas",
    "breast": "breast", "stomach": "stomach",
    "prostate": "prostate", "ovary": "ovary", "thyroid": "thyroid",
    "spleen": "spleen", "testis": "testis", "muscle": "muscle",
    "placenta": "placenta", "adipose tissue": "adipose tissue",
    "eye": "eye", "retina": "retina",
}

# Phase 38: organ-level tissue keyword → canonical anatomical roll-up
# (tissue_standard_l1). When a user asks for an ORGAN ("brain", "blood", "skin"),
# the right answer is every sample of that organ — including subregions whose
# standardized label lacks the organ word (prefrontal cortex → brain, PBMC →
# blood, dermis → skin). tissue_standard + raw LIKE systematically under-count
# these (brain 9,933+LIKE vs L1 39,960) AND let raw-LIKE false positives in
# (xenografts, brain *tumors*). L1 equality is both more complete and cleaner.
# Only organ-level terms roll up; a user naming a subregion ("hippocampus") still
# routes through the specific tissue_standard path below.
_TISSUE_KEYWORD_TO_L1: dict[str, str] = {
    "brain": "brain", "blood": "blood", "skin": "skin", "liver": "liver",
    "lung": "lung", "heart": "heart", "kidney": "kidney", "pancreas": "pancreas",
    "bone marrow": "bone marrow", "breast": "breast", "stomach": "stomach",
    "prostate": "prostate gland", "ovary": "ovary", "thyroid": "thyroid gland",
    "spleen": "spleen", "testis": "testis", "muscle": "muscle",
    "placenta": "placenta", "colon": "colon", "retina": "retina",
}

_ORGANISM_KEYWORD_TO_COMMON: dict[str, str] = {
    "human": "human", "homo sapiens": "human",
    "mouse": "mouse", "mus musculus": "mouse",
    "rat": "rat", "rattus norvegicus": "rat",
    "zebrafish": "zebrafish", "danio rerio": "zebrafish",
    "fly": "fruit fly", "drosophila": "fruit fly", "drosophila melanogaster": "fruit fly",
    "monkey": "cynomolgus monkey",
}


class JoinPathResolver:
    """根据查询涉及的字段自动推导JOIN路径"""

    _DEFAULT_JOIN_RULES = {
        ("unified_samples", "unified_projects"): JoinClause(
            "LEFT JOIN", "unified_projects", "p",
            "s.project_pk = p.pk",
        ),
        ("unified_samples", "unified_series"): JoinClause(
            "LEFT JOIN", "unified_series", "sr",
            "s.series_pk = sr.pk",
        ),
        ("unified_celltypes", "unified_samples"): JoinClause(
            "INNER JOIN", "unified_samples", "s",
            "ct.sample_pk = s.pk",
        ),
    }

    def __init__(self, *, schema_config: SchemaConfig | None = None):
        self._schema_config = schema_config

        if schema_config is not None:
            self._field_table = dict(schema_config.field_to_table)
            self._view_fields = set(schema_config.view_fields)
            self._main_table = schema_config.main_table
        else:
            self._field_table = dict(_DEFAULT_FIELD_TABLE)
            self._view_fields = set(_DEFAULT_VIEW_FIELDS)
            self._main_table = "unified_samples"

        # JOIN rules are kept hardcoded — SchemaConfig provides BFS join paths
        # which are used by EnhancedJoinResolver; this class uses simple rules
        self.JOIN_RULES = dict(self._DEFAULT_JOIN_RULES)

    def resolve(self, needed_fields: list[str], target_table: str = "") -> JoinPlan:
        """推导最优JOIN路径"""
        if not target_table:
            target_table = self._main_table

        # Phase 28.I — table-routing column-availability check.
        #
        # When the parser sets target_level=series (e.g. "heart single-cell
        # atlas" → series) and the filters reference sample-only columns
        # (tissue, disease, cell_type, …), the old code would emit
        # `FROM unified_series WHERE tissue_standard = ?` — but
        # tissue_standard only exists on unified_samples / the main view.
        # SQLite raises `no such column` and the query silently 0s out.
        #
        # If every needed field is available in the main view, demote to
        # the view: it carries both series_pk/series_id AND sample-level
        # columns, so downstream callers can still aggregate by series.
        field_set = set(needed_fields)
        if target_table != self._main_table and field_set:
            samples_required = any(
                self._field_table.get(f) == "unified_samples"
                for f in field_set
            )
            if samples_required and field_set.issubset(self._view_fields):
                main_view = (self._schema_config.main_view
                             if self._schema_config else "v_sample_with_hierarchy")
                return JoinPlan(
                    base_table=main_view or "v_sample_with_hierarchy",
                    use_view=True,
                )

        # 检查是否能用视图
        if target_table == self._main_table:
            if field_set.issubset(self._view_fields) or not field_set:
                main_view = (self._schema_config.main_view
                             if self._schema_config else "v_sample_with_hierarchy")
                return JoinPlan(base_table=main_view or "v_sample_with_hierarchy",
                                use_view=True)

        needed_tables = set()
        for f in needed_fields:
            t = self._field_table.get(f)
            if t:
                needed_tables.add(t)
        needed_tables.add(target_table)

        if len(needed_tables) <= 1:
            return JoinPlan(base_table=target_table)

        # 构建JOIN链
        joins = []
        connected = {target_table}
        remaining = needed_tables - connected

        for table in sorted(remaining):
            key = (target_table, table)
            rev_key = (table, target_table)
            rule = self.JOIN_RULES.get(key) or self.JOIN_RULES.get(rev_key)
            if rule:
                joins.append(rule)
                connected.add(table)

        return JoinPlan(base_table=target_table, joins=joins)


class SQLGenerator:
    """
    SQL生成器: 3候选策略
    1. 模板 (常见模式)
    2. 规则 (灵活组合)
    3. LLM (复杂/歧义)
    """

    # 默认 target_level → table 映射
    _DEFAULT_TARGET_TABLE: dict[str, str] = {
        "project": "unified_projects",
        "series": "unified_series",
        "sample": "unified_samples",
        "celltype": "unified_celltypes",
    }

    def __init__(
        self,
        dal: DatabaseAbstractionLayer,
        llm: ILLMClient | None = None,
        *,
        schema_config: SchemaConfig | None = None,
    ):
        self.dal = dal
        self.llm = llm
        self._schema_config = schema_config
        self.join_resolver = JoinPathResolver(schema_config=schema_config)

        # Derive main table / view from schema_config or use defaults
        self._main_table = schema_config.main_table if schema_config else "unified_samples"
        self._main_view = (
            (schema_config.main_view if schema_config else "v_sample_with_hierarchy")
            or "v_sample_with_hierarchy"
        )

    async def generate(
        self,
        query: ParsedQuery,
        resolved_entities: list[ResolvedEntity] | None = None,
    ) -> list[SQLCandidate]:
        """生成SQL候选列表"""
        candidates: list[SQLCandidate] = []

        # 确定涉及的字段
        needed_fields = self._collect_needed_fields(query)
        plan = self.join_resolver.resolve(needed_fields, self._target_to_table(query.target_level))

        # 路径1: 模板
        tpl = self._from_template(query, resolved_entities, plan)
        if tpl:
            candidates.append(tpl)

        # 路径2: 规则
        rule = self._from_rules(query, resolved_entities, plan)
        candidates.append(rule)

        # 路径3: LLM (仅复杂查询)
        if self.llm and query.complexity in (QueryComplexity.MODERATE, QueryComplexity.COMPLEX):
            try:
                llm_sql = await self._from_llm(query, resolved_entities, plan)
                if llm_sql:
                    candidates.append(llm_sql)
            except Exception as e:
                logger.warning("LLM SQL generation failed: %s", e)

        return candidates

    def _collect_needed_fields(self, query: ParsedQuery) -> list[str]:
        """收集查询涉及的字段"""
        fields = set()
        f = query.filters
        if f.tissues:
            fields.add("tissue")
        if f.diseases:
            fields.add("disease")
        if f.assays:
            fields.add("assay")
        if f.cell_types:
            fields.add("cell_type")
        if f.source_databases:
            fields.add("source_database")
        if f.sex:
            fields.add("sex")
        if f.organisms:
            fields.add("organism")
        if f.development_stages:
            fields.add("development_stage")
        if f.has_h5ad is not None:
            fields.add("has_h5ad")
        if f.pmids:
            fields.add("pmid")
        if f.dois:
            fields.add("doi")
        if f.sample_types:
            fields.add("sample_type")
        if f.disease_categories:
            fields.add("disease_category")
        if f.tissue_systems:
            fields.add("tissue_system")
        if f.min_cells is not None:
            fields.add("n_cells")
        if f.min_series_cells is not None:
            fields.add("cell_count")
        if f.min_citation_count is not None:
            fields.add("citation_count")
        if query.ordering:
            fields.add(query.ordering.field)
        if query.aggregation:
            fields.update(query.aggregation.group_by)
        return list(fields)

    def _target_to_table(self, level: str) -> str:
        return self._DEFAULT_TARGET_TABLE.get(level, self._main_table)

    # ---------- 模板生成 ----------

    def _from_template(
        self, query: ParsedQuery, entities: list[ResolvedEntity] | None, plan: JoinPlan,
    ) -> SQLCandidate | None:
        """模板化SQL生成"""
        f = query.filters

        # ID查询模板. Phase 38 fix for systematic ID over-count:
        # A basic ID lookup ("GSE149614") must return the named dataset's OWN
        # samples. Previously the template ALWAYS unioned entity_links, so a
        # GEO↔SRA mirror twin (linked via same_as / pmid, holding the identical
        # biological samples) doubled every count (GSE149614 21→42). Only an
        # explicit "samples linked to X" (LINEAGE intent) should follow links —
        # and even then never `same_as` mirrors (pure duplicates). The own-sample
        # lookup is alias-aware via id_mappings so accessions absent from
        # unified_projects.project_id (e.g. GSE100866 → 0) still resolve.
        if f.project_ids:
            pid = f.project_ids[0]
            # Resolve the named accession to its OWN project. Prefer the direct
            # project_id match; fall back to id_mappings only when the accession
            # is absent from unified_projects.project_id (e.g. GSE100866). The
            # NOT-EXISTS guard prevents id_mappings (which also indexes the SRA
            # twin under the same GEO accession) from re-adding the mirror's
            # samples — that twin double-counting is the ID over-count bug.
            own = (
                f"SELECT s.* FROM {self._main_table} s "
                f"JOIN unified_projects p ON s.project_pk = p.pk "
                f"WHERE p.project_id = ? OR ("
                f"  NOT EXISTS (SELECT 1 FROM unified_projects WHERE project_id = ?) "
                f"  AND p.pk IN (SELECT entity_pk FROM id_mappings "
                f"               WHERE entity_type='project' AND id_value = ?))"
            )
            if query.intent == QueryIntent.LINEAGE:
                # An explicit "samples linked to / across databases for X" query
                # is exactly the cross-DB fusion case — surface every deposit
                # INCLUDING the same_as mirror twins (that is the cross-database
                # value here, distinct from a bare-accession lookup which dedups).
                sql = (
                    own + " OR p.pk IN ("
                    "  SELECT target_pk FROM entity_links WHERE source_id = ? "
                    "  UNION SELECT source_pk FROM entity_links WHERE target_id = ?"
                    ") LIMIT 10000"
                )
                params = [pid, pid, pid, pid, pid]
            else:
                sql = own + " LIMIT 10000"
                params = [pid, pid, pid]
            return SQLCandidate(sql=sql, params=params, method="template")
        if f.sample_ids:
            sid = f.sample_ids[0]
            return SQLCandidate(
                sql=f"SELECT * FROM {self._main_table} WHERE sample_id = ? LIMIT 1",
                params=[sid], method="template",
            )
        if f.pmids:
            return SQLCandidate(
                sql=f"SELECT s.* FROM {self._main_table} s JOIN unified_projects p ON s.project_pk = p.pk WHERE p.pmid = ? LIMIT 10000",
                params=[f.pmids[0]], method="template",
            )

        # 统计模板
        if query.aggregation and query.intent == QueryIntent.STATISTICS:
            return self._statistics_template(query, plan)

        return None

    def _statistics_template(self, query: ParsedQuery, plan: JoinPlan) -> SQLCandidate:
        """统计类SQL模板"""
        agg = query.aggregation
        group_field = _vc(
            agg.group_by[0] if agg.group_by else "source_database",
            plan.use_view,
        )
        table = plan.base_table

        where_parts, params = self._build_where(query.filters, table, plan.use_view)
        where_sql = " AND ".join(where_parts) if where_parts else "1=1"

        # Cell-count column differs per entity table: samples/view → n_cells,
        # projects → total_cells, series/celltypes → cell_count. Hardcoding
        # n_cells made project/series STATISTICS emit `no such column` (W2.1).
        cc = _cell_count_col(table)
        sql = (
            f"SELECT {group_field}, COUNT(*) as count, "
            f"SUM(CASE WHEN {cc} IS NOT NULL THEN {cc} ELSE 0 END) as total_cells "
            f"FROM {table} WHERE {where_sql} "
            f"GROUP BY {group_field} ORDER BY count DESC"
        )
        return SQLCandidate(sql=sql, params=params, method="template")

    # ---------- 规则生成 ----------

    def _from_rules(
        self, query: ParsedQuery, entities: list[ResolvedEntity] | None, plan: JoinPlan,
    ) -> SQLCandidate:
        """规则化SQL构建"""
        table = plan.base_table
        use_view = plan.use_view

        # Collect ontology-expanded fields to exclude from _build_where
        onto_fields: set[str] = set()
        onto_parts: list[str] = []
        onto_params: list = []
        # Phase 20-A: group per-entity predicates by entity_type so that
        # multiple same-type entities (e.g. "hippocampus, cortex,
        # cerebellum") OR together instead of AND-ing into an
        # unsatisfiable intersection.
        _per_type_preds: dict[str, list[str]] = {}
        _per_type_params: dict[str, list] = {}

        def _add_pred(et: str, sql: str, params_: list):
            _per_type_preds.setdefault(et, []).append(sql)
            _per_type_params.setdefault(et, []).extend(params_)

        # Under strict_mode the user is asking for literal matches, so
        # skip ontology resolution entirely and let _build_where emit the
        # narrow equality / LIKE clauses for every field.
        if entities and not query.strict_mode:
            for ent in entities:
                if ent.db_values and ent.original.entity_type in ("tissue", "disease", "cell_type"):
                    # Skip negated entities — they should NOT be expanded into IN()
                    if getattr(ent.original, 'negated', False):
                        continue
                    field = _vc(ent.original.entity_type, use_view)
                    # Cap ontology expansion breadth: more than 8 OR-clauses
                    # balloons the query plan. Take the top N by sample count.
                    values = [v.raw_value for v in ent.db_values[:8]]
                    if values:
                        onto_fields.add(ent.original.entity_type)
                        original_text = ent.original.text or ent.original.normalized_value or ""
                        normalized = (ent.original.normalized_value or original_text).lower().strip()
                        lookup_text = original_text.lower().strip()
                        et = ent.original.entity_type
                        if et in ("tissue", "disease"):
                            # Tier-1 indexed-equality fast path: prefer
                            # *_standard / *_category / *_common indexed cols.
                            # Phase 19-C: try the entity's *normalized_value*
                            # alongside the user text so "pancreatic" resolves
                            # via "pancreas", "kidneys" via "kidney", etc.
                            if et == "disease":
                                # Phase 23-C: if user's term is a *specific*
                                # disease (covid, alzheimer, diabetes, etc.),
                                # skip category widening — emit
                                # (disease_standard = X OR disease LIKE Y) only.
                                specific_like = (
                                    _SPECIFIC_DISEASE_LIKE.get(lookup_text)
                                    or _SPECIFIC_DISEASE_LIKE.get(normalized)
                                )
                                cat_v = (
                                    None if specific_like else (
                                        _DISEASE_KEYWORD_TO_CATEGORY.get(lookup_text)
                                        or _DISEASE_KEYWORD_TO_CATEGORY.get(normalized)
                                    )
                                )
                                std_v = (
                                    _DISEASE_KEYWORD_TO_STANDARD.get(lookup_text)
                                    or _DISEASE_KEYWORD_TO_STANDARD.get(normalized)
                                )
                                # Priority order:
                                # 0. Specific disease: emit (std OR LIKE) without category.
                                # 1. Umbrella (cat_v found): category clause alone.
                                # 2. std_v + known umbrella (cat_from_std): OR with category.
                                # 3. std_v alone.
                                # 4. LIKE fallback.
                                cat_from_std = (
                                    _DISEASE_STANDARD_TO_CATEGORY.get(std_v)
                                    if std_v else None
                                )
                                if specific_like:
                                    parts_clauses: list[str] = []
                                    parts_params: list = []
                                    std_col = _vc('disease_standard', use_view)
                                    # Phase 38: match disease_standard with LIKE on
                                    # the curated token, NOT an exact std_v. Several
                                    # "specific" diseases are umbrella-but-specific —
                                    # they have many standardized SUBTYPES sharing the
                                    # token: "diabetes" → type 1 / type 2 / gestational
                                    # diabetes mellitus; "leukemia" → AML / CML / ALL /
                                    # CLL. The old exact `disease_standard =
                                    # 'type 2 diabetes mellitus'` captured ONLY T2DM
                                    # (4,281) instead of all 14,715 diabetes rows. The
                                    # token is always a substring of its canonical std
                                    # value (COVID⊂COVID-19, alzheimer⊂Alzheimer
                                    # disease), so LIKE is a strict superset that still
                                    # matches single-standard diseases unchanged while
                                    # correctly including subtypes/spelling variants.
                                    # (Strict-mode diabetes stays narrow — strict skips
                                    # this ontology entity fast-path entirely.)
                                    parts_clauses.append(f"{std_col} LIKE ?")
                                    parts_params.append(f"%{specific_like}%")
                                    parts_clauses.append(f"{field} LIKE ?")
                                    parts_params.append(f"%{specific_like}%")
                                    _add_pred(et,
                                        "(" + " OR ".join(parts_clauses) + ")",
                                        parts_params)
                                elif cat_v:
                                    cat_col = _vc("disease_category", use_view)
                                    _add_pred(et, f"{cat_col} = ?", [cat_v])
                                elif std_v and cat_from_std:
                                    _add_pred(et,
                                        f"({_vc('disease_standard', use_view)} = ?"
                                        f" OR {_vc('disease_category', use_view)} = ?)",
                                        [std_v, cat_from_std])
                                elif std_v:
                                    std_col = _vc("disease_standard", use_view)
                                    _add_pred(et, f"{std_col} = ?", [std_v])
                                else:
                                    all_terms = list(dict.fromkeys(values + [original_text]))
                                    like_clauses = [f"{field} LIKE ?" for _ in all_terms]
                                    _add_pred(et,
                                        f"({' OR '.join(like_clauses)})",
                                        [f"%{t}%" for t in all_terms])
                            else:  # tissue
                                std_field = "tissue_standard"
                                std_col = _vc(std_field, use_view)
                                mapped = (
                                    _TISSUE_KEYWORD_TO_STANDARD.get(lookup_text)
                                    or _TISSUE_KEYWORD_TO_STANDARD.get(normalized)
                                )
                                # Phase 38: organ-level tissues route to the
                                # canonical anatomical roll-up tissue_standard_l1,
                                # which already groups every subregion (prefrontal
                                # cortex → brain, PBMC → blood, dermis → skin) and
                                # drops raw-LIKE false positives (xenografts, brain
                                # *tumors*). Strict mode keeps the literal column.
                                _l1_tissue = (
                                    _TISSUE_KEYWORD_TO_L1.get(lookup_text)
                                    or _TISSUE_KEYWORD_TO_L1.get(normalized)
                                )
                                _use_l1 = bool(_l1_tissue) and not getattr(query, "strict_mode", False)
                                if _use_l1:
                                    std_field = "tissue_standard_l1"
                                    std_col = _vc(std_field, use_view)
                                    mapped = _l1_tissue
                                # Phase 19-C: exclude tissues that the user
                                # negated elsewhere from umbrella expansion
                                # (e.g. "blood, no PBMC" should not re-include
                                # PBMC via the blood→[blood, PBMC, peripheral
                                # blood] mapping).
                                excl = {t.lower().strip()
                                        for t in (query.filters.exclude_tissues or [])}
                                if mapped:
                                    # Phase 23-C v2: only widen via LIKE for a
                                    # small set of anatomical-hierarchy tissues
                                    # whose DB rows often carry sub-region
                                    # values that the standardiser missed
                                    # (e.g. "frontal cortex of brain",
                                    # "brain organoid"). Adding LIKE
                                    # indiscriminately for every tissue (liver,
                                    # lung, kidney…) over-retrieves curation
                                    # variants the user didn't ask for.
                                    _hierarchical = {"brain", "intestine", "spinal cord"}
                                    is_hierarchical = (
                                        lookup_text in _hierarchical
                                        or normalized in _hierarchical
                                    )
                                    # L1 roll-up already covers subregions — adding
                                    # the raw LIKE would re-admit the false positives
                                    # L1 was chosen to exclude.
                                    if _use_l1:
                                        is_hierarchical = False
                                    if isinstance(mapped, list):
                                        mapped_list = [m for m in
                                                       dict.fromkeys(mapped)
                                                       if m.lower().strip()
                                                       not in excl]
                                        if not mapped_list:
                                            mapped_list = list(dict.fromkeys(mapped))
                                        placeholders = ", ".join("?" * len(mapped_list))
                                        if is_hierarchical:
                                            raw_col = _vc(field, use_view)
                                            _add_pred(et,
                                                f"({std_col} IN ({placeholders}) "
                                                f"OR {raw_col} LIKE ?)",
                                                mapped_list + [f"%{lookup_text}%"])
                                        else:
                                            _add_pred(et,
                                                f"{std_col} IN ({placeholders})",
                                                mapped_list)
                                    else:
                                        if mapped.lower().strip() in excl:
                                            # Whole mapping excluded — fall back to LIKE
                                            all_terms = list(dict.fromkeys(values + [original_text]))
                                            like_clauses = [f"{field} LIKE ?" for _ in all_terms]
                                            _add_pred(et,
                                                f"({' OR '.join(like_clauses)})",
                                                [f"%{t}%" for t in all_terms])
                                        else:
                                            if is_hierarchical:
                                                raw_col = _vc(field, use_view)
                                                _add_pred(et,
                                                    f"({std_col} = ? OR {raw_col} LIKE ?)",
                                                    [mapped, f"%{lookup_text}%"])
                                            else:
                                                _add_pred(et, f"{std_col} = ?", [mapped])
                                else:
                                    all_terms = list(dict.fromkeys(values + [original_text]))
                                    like_clauses = [f"{field} LIKE ?" for _ in all_terms]
                                    _add_pred(et,
                                        f"({' OR '.join(like_clauses)})",
                                        [f"%{t}%" for t in all_terms])
                        else:
                            # cell_type: use IN() for performance, plus loose-alias
                            # widening + tissue-column fallback for anatomical cell
                            # types (Phase 22-D: pancreatic islet / CD8+ T cell etc.
                            # often live on the tissue column too in DB curation).
                            _ct_loose = {
                                "pancreatic islet": ["%pancreatic islet%", "%islet%"],
                                "pancreatic beta cell": ["%pancreatic beta%", "%beta cell%"],
                                "pancreatic alpha cell": ["%pancreatic alpha%", "%alpha cell%"],
                                "regulatory T cell": ["%regulatory T cell%", "%Treg%"],
                                "CD8+ T cell": ["%CD8% T cell%", "%CD8%T%", "%cytotoxic T%"],
                                "CD4+ T cell": ["%CD4% T cell%", "%CD4%T%", "%helper T%"],
                            }
                            _ct_also_tissue = {"pancreatic islet"}
                            placeholders = ", ".join("?" * len(values))
                            in_part = f"{field} IN ({placeholders})"
                            ct_params: list = list(values)
                            like_parts: list[str] = []
                            patterns = _ct_loose.get(normalized) or _ct_loose.get(original_text)
                            if patterns:
                                for p in patterns:
                                    like_parts.append(f"{field} LIKE ?")
                                    ct_params.append(p)
                            else:
                                like_parts.append(f"{field} LIKE ?")
                                ct_params.append(f"%{original_text}%")
                            if normalized in _ct_also_tissue or original_text.lower().strip() in _ct_also_tissue:
                                tissue_col = _vc("tissue", use_view)
                                like_parts.append(f"{tissue_col} LIKE ?")
                                ct_params.append(f"%{original_text}%")
                            _add_pred(et,
                                f"({in_part} OR " + " OR ".join(like_parts) + ")",
                                ct_params)

            # Phase 20-A: combine same-type predicates with OR; across-type
            # combination remains AND (handled by where_parts join in caller).
            for et, preds in _per_type_preds.items():
                pms = _per_type_params.get(et, [])
                if len(preds) == 1:
                    onto_parts.append(preds[0])
                else:
                    onto_parts.append("(" + " OR ".join(preds) + ")")
                onto_params.extend(pms)

        # Build WHERE from filters, excluding ontology-handled fields
        # But NEVER exclude fields that have exclusion conditions
        effective_exclude = set()
        if onto_fields:
            for f_name in onto_fields:
                if f_name == "tissue" and query.filters.exclude_tissues:
                    continue
                elif f_name == "disease" and query.filters.exclude_diseases:
                    continue
                elif f_name == "organism" and query.filters.exclude_organisms:
                    continue
                else:
                    effective_exclude.add(f_name)

        where_parts, params = self._build_where(
            query.filters, table, use_view,
            exclude_fields=effective_exclude if effective_exclude else None,
            strict_mode=query.strict_mode,
        )

        # Prepend ontology-expanded conditions (skip under strict_mode)
        if onto_parts and not query.strict_mode:
            where_parts = onto_parts + where_parts
            params = onto_params + params

        if not where_parts:
            if query.filters.free_text:
                t_col = _vc("tissue", use_view)
                d_col = _vc("disease", use_view)
                title_col = _vc("title", use_view)
                if use_view:
                    where_parts.append(
                        f"({t_col} LIKE ? OR {d_col} LIKE ? OR {title_col} LIKE ?)"
                    )
                    text = f"%{query.filters.free_text}%"
                    params.extend([text, text, text])
                else:
                    where_parts.append(f"({t_col} LIKE ? OR {d_col} LIKE ?)")
                    text = f"%{query.filters.free_text}%"
                    params.extend([text, text])
            elif query.sub_intent == "adversarial":
                # Refuse adversarial input — emit a predicate that matches
                # nothing so the executor returns an empty result set.
                where_parts.append("1=0")
            elif not query.aggregation:
                # No filters and no explicit aggregation — fall back to a
                # harmless empty predicate rather than scanning the whole DB.
                # The synthesizer can surface a "please be more specific"
                # suggestion.
                where_parts.append("1=0")

        where_sql = " AND ".join(where_parts) if where_parts else "1=1"

        # SELECT
        select = "*"
        if query.aggregation and query.aggregation.group_by:
            group = _vc(query.aggregation.group_by[0], use_view)
            select = f"{group}, COUNT(*) as count"
        elif query.aggregation:
            # Aggregation without group_by → scalar count. Render as a single
            # COUNT(*) so callers don't have to special-case this.
            select = "COUNT(*) as count"

        # ORDER BY — only when explicitly requested. A default ORDER BY pk DESC
        # on a LIKE-filtered query forces SQLite to scan + sort without index
        # support, which can turn a 0.5s query into a 20s one. Skip it unless
        # the caller asked for a specific order or an aggregation.
        order = ""
        if query.ordering:
            # Phase 23-C: when querying unified_series directly, translate
            # sample-level field names (n_cells) to their series-table
            # equivalent (cell_count). Otherwise the ORDER BY breaks the SQL.
            ord_field = query.ordering.field
            if table == "unified_series" and ord_field == "n_cells":
                ord_field = "cell_count"
            order = f" ORDER BY {_vc(ord_field, use_view)} {query.ordering.direction.upper()}"
        elif query.aggregation:
            order = " ORDER BY count DESC"

        # GROUP BY
        group_by = ""
        if query.aggregation and query.aggregation.group_by:
            group_by = f" GROUP BY {_vc(query.aggregation.group_by[0], use_view)}"

        # LIMIT — always bound the result set to avoid 20 GB result sets. The
        # agent surfaces total_count separately, so pagination is the view layer's
        # concern, not the SQL engine's.
        limit_clause = ""
        if not query.aggregation:  # aggregation produces few rows anyway
            # Fetch generously so the fusion stage has multi-source headroom
            # before pagination. The view layer truncates to query.limit. A
            # floor of 5k catches default-limit (100) searches that span many
            # sources — otherwise a 100-row SQL scan might hit only one DB.
            requested = max(query.limit or 100, 1)
            effective_limit = min(max(requested * 10, 5000), 20000)
            limit_clause = f" LIMIT {effective_limit}"

        sql = f"SELECT {select} FROM {table} WHERE {where_sql}{group_by}{order}{limit_clause}"

        # Stratified UNION ALL rewrite: for broad search queries that span many
        # sources, a plain LIMIT fills from whichever source SQLite scans first
        # (typically the one with earliest pks), starving other sources and
        # tanking fusion_quality. Rewrite into one SELECT per source_database
        # with a per-source cap — UNION ALL preserves indexed access paths.
        #
        # Heuristics (avoid stratifying when the cost outweighs the benefit):
        #   - Only when no ID lookup / no aggregation / no explicit ordering
        #   - Skip under strict_mode (LIKE-heavy, slow per branch)
        #   - Skip when the predicate is dominated by LIKE / NOT LIKE (no
        #     index support — each UNION branch would do a full scan)
        #   - Cap to the sources explicitly requested, else main sources only
        has_indexed_predicate = bool(
            query.filters.tissues or query.filters.diseases
            or query.filters.organisms or query.filters.source_databases
            or query.filters.sample_types or query.filters.disease_categories
            or query.filters.tissue_systems or query.filters.cell_types
            or query.filters.sex
        )
        has_slow_predicate = bool(
            query.filters.exclude_tissues or query.filters.exclude_diseases
            or query.filters.exclude_organisms or query.filters.exclude_source_databases
            or query.filters.free_text or query.filters.assays
        )
        stratify_eligible = (
            not query.aggregation and not query.filters.project_ids
            and not query.filters.sample_ids and not query.filters.pmids
            and not group_by and not query.strict_mode
            and not query.ordering
            and has_indexed_predicate
            and not has_slow_predicate
        )
        if stratify_eligible:
            source_col = "sample_source" if use_view else "source_database"
            if query.filters.source_databases:
                stratified_sources = [s for s in query.filters.source_databases
                                        if s and s != "unknown"]
            else:
                # Only the 5 main sources — the long tail (psychad, htan, hca)
                # has few rows and would waste query time on UNION branches
                # that almost always return empty.
                stratified_sources = ["geo", "ega", "ncbi", "ebi", "cellxgene"]
            if len(stratified_sources) > 1:
                per_source_cap = max(effective_limit // len(stratified_sources), 500)
                branches: list[str] = []
                strat_params: list = []
                for src in stratified_sources:
                    branches.append(
                        f"SELECT * FROM (SELECT {select} FROM {table} "
                        f"WHERE {where_sql} AND {source_col} = ? "
                        f"LIMIT {per_source_cap})"
                    )
                    strat_params.extend(params)
                    strat_params.append(src)
                strat_sql = (
                    "SELECT * FROM (" + " UNION ALL ".join(branches) + ") "
                    f"LIMIT {effective_limit}"
                )
                # Emit a separate COUNT SQL for the true total — the
                # stratified UNION's inner LIMITs would otherwise undercount.
                count_table = "unified_samples" if use_view else table
                count_where = where_sql
                if use_view:
                    count_where = count_where.replace(
                        "sample_source", "source_database"
                    ).replace("sample_pk", "pk")
                count_sql_str = f"SELECT COUNT(*) AS c FROM {count_table} WHERE {count_where}"
                return SQLCandidate(
                    sql=strat_sql, params=strat_params, method="rule",
                    count_sql=count_sql_str, count_params=list(params),
                )

        return SQLCandidate(sql=sql, params=params, method="rule")

    def _build_where(
        self, filters: QueryFilters, table: str,
        use_view: bool = False, exclude_fields: set | None = None,
        strict_mode: bool = False,
    ) -> tuple[list[str], list[Any]]:
        """构建WHERE条件 (use_view=True时自动映射视图列名)

        strict_mode=True disables disease_category umbrella widening (so
        "cancer" → disease LIKE '%cancer%' rather than disease_category='neoplasm')
        so the agent honours the user's literal request.
        """
        parts: list[str] = []
        params: list[Any] = []
        exclude = exclude_fields or set()
        # When the base table IS unified_series, the series-only columns
        # (assay/platform/has_h5ad/cell_count) are direct columns — emitting a
        # `series_pk IN (SELECT pk FROM unified_series …)` sub-select would
        # reference a nonexistent series_pk column and raise `no such column`.
        # Sample-table / view queries DO have series_pk, so they keep the
        # sub-select. (Phase 39 W2.1: previously only has_h5ad/cell_count were
        # guarded; assay/exclude_assays crashed series-target queries.)
        _on_series_table = table == "unified_series"

        def _like(field: str, values: list[str]):
            if not values or field in exclude:
                return
            col = _vc(field, use_view)
            or_clauses = [f"{col} LIKE ?" for _ in values]
            parts.append(f"({' OR '.join(or_clauses)})")
            params.extend(f"%{v}%" for v in values)

        def _in(field: str, values: list[str]):
            if not values or field in exclude:
                return
            col = _vc(field, use_view)
            placeholders = ", ".join("?" * len(values))
            parts.append(f"{col} IN ({placeholders})")
            params.extend(values)

        def _eq(field: str, value: Any):
            if value is None or field in exclude:
                return
            col = _vc(field, use_view)
            parts.append(f"{col} = ?")
            params.append(value)

        def _not_like(field: str, values: list[str]):
            """Generate NOT LIKE clauses for exclusion."""
            if not values or field in exclude:
                return
            col = _vc(field, use_view)
            for v in values:
                parts.append(f"({col} IS NULL OR {col} NOT LIKE ?)")
                params.append(f"%{v}%")

        def _not_in(field: str, values: list[str]):
            """Generate NOT IN clauses for exclusion."""
            if not values or field in exclude:
                return
            col = _vc(field, use_view)
            placeholders = ", ".join("?" * len(values))
            parts.append(f"{col} NOT IN ({placeholders})")
            params.extend(values)

        def _indexed_or_like(field: str, std_field: str, mapping: dict, values: list[str]):
            """Prefer indexed equality (col_standard = 'liver') over LIKE.

            For values present in the keyword→standard mapping, emit an IN()
            on the indexed *_standard / *_common column. The mapping is
            curated to canonicalised DB values, so we *replace* LIKE rather
            than OR-ing both — fewer rows scanned, indexes actually used.

            Mappings can be a single string or a list (e.g. "blood" → [blood,
            PBMC, peripheral blood]).

            Unmapped values fall back to LIKE on the raw column.
            """
            if not values or field in exclude:
                return
            indexed: list[str] = []
            unmapped: list[str] = []
            for v in values:
                k = v.lower().strip()
                m = mapping.get(k)
                if m is None:
                    unmapped.append(v)
                elif isinstance(m, list):
                    indexed.extend(m)
                else:
                    indexed.append(m)

            # Phase 19-C: when the user excluded values that overlap with the
            # umbrella expansion (e.g. "blood, no PBMC"), remove them so the
            # umbrella doesn't silently re-include the excluded tissue.
            if field == "tissue" and getattr(filters, "exclude_tissues", None):
                excl_set = {t.lower().strip()
                            for t in filters.exclude_tissues}
                indexed = [v for v in indexed if v.lower().strip() not in excl_set]
            if field == "disease" and getattr(filters, "exclude_diseases", None):
                excl_set = {t.lower().strip()
                            for t in filters.exclude_diseases}
                indexed = [v for v in indexed if v.lower().strip() not in excl_set]

            sub_clauses: list[str] = []
            if indexed:
                # Dedupe while preserving order
                indexed = list(dict.fromkeys(indexed))
                std_col = _vc(std_field, use_view)
                placeholders = ", ".join("?" * len(indexed))
                sub_clauses.append(f"{std_col} IN ({placeholders})")
                params.extend(indexed)
                # Phase 23-C: only emit a raw LIKE alongside the indexed
                # match for *anatomical-hierarchy* tissues whose DB rows
                # commonly carry sub-region values that the standardiser
                # missed ("frontal cortex of brain", "brain organoid").
                # Indiscriminate LIKE for every tissue over-retrieves the
                # curation noise users didn't ask for.
                if field == "tissue" and not strict_mode:
                    _hierarchical = {"brain", "intestine", "spinal cord"}
                    raw_terms = list(dict.fromkeys(
                        v.lower().strip() for v in values
                        if v.lower().strip() in _hierarchical
                    ))
                    if raw_terms:
                        raw_col = _vc(field, use_view)
                        like_clauses = [f"{raw_col} LIKE ?" for _ in raw_terms]
                        sub_clauses.append("(" + " OR ".join(like_clauses) + ")")
                        params.extend(f"%{v}%" for v in raw_terms)
            if unmapped:
                col = _vc(field, use_view)
                or_clauses = [f"{col} LIKE ?" for _ in unmapped]
                sub_clauses.append("(" + " OR ".join(or_clauses) + ")")
                params.extend(f"%{v}%" for v in unmapped)
            if sub_clauses:
                if len(sub_clauses) == 1:
                    parts.append(sub_clauses[0])
                else:
                    parts.append("(" + " OR ".join(sub_clauses) + ")")

        # Tissue → canonical roll-up fast path (Phase 38). Organ-level terms hit
        # tissue_standard_l1 (captures all subregions, drops raw-LIKE noise);
        # specific tissues (subregions, anything not in the L1 map) keep the
        # tissue_standard + curated-LIKE path. Strict mode honours the literal
        # request, so it stays on tissue_standard rather than the organ roll-up.
        if filters.tissues and "tissue" not in exclude and not strict_mode:
            l1_vals: list[str] = []
            other_tissue: list[str] = []
            for v in filters.tissues:
                l1 = _TISSUE_KEYWORD_TO_L1.get(v.lower().strip())
                (l1_vals.append(l1) if l1 else other_tissue.append(v))
            if getattr(filters, "exclude_tissues", None):
                excl = {t.lower().strip() for t in filters.exclude_tissues}
                l1_vals = [v for v in l1_vals if v.lower().strip() not in excl]
            if l1_vals:
                l1_vals = list(dict.fromkeys(l1_vals))
                l1_col = _vc("tissue_standard_l1", use_view)
                ph = ", ".join("?" * len(l1_vals))
                parts.append(f"{l1_col} IN ({ph})")
                params.extend(l1_vals)
            if other_tissue:
                _indexed_or_like("tissue", "tissue_standard",
                                 _TISSUE_KEYWORD_TO_STANDARD, other_tissue)
        else:
            _indexed_or_like("tissue", "tissue_standard",
                             _TISSUE_KEYWORD_TO_STANDARD, filters.tissues)
        # Disease handling — try disease_category first (broader umbrella like
        # 'neoplasm' matches more rows than disease_standard='cancer'). Under
        # strict_mode, skip the umbrella widening and use LIKE on the raw
        # disease column so results match the user's literal term.
        # Phase 23-C: specific diseases (covid, alzheimer, diabetes, leukemia
        # …) route to (disease_standard OR LIKE) instead of the whole
        # disease_category — asking for "COVID" should not return all
        # infectious diseases. Only true umbrella terms (cancer / neurological
        # / autoimmune) use the category path.
        if filters.diseases and "disease" not in exclude:
            if strict_mode:
                col = _vc("disease", use_view)
                or_clauses = [f"{col} LIKE ?" for _ in filters.diseases]
                parts.append("(" + " OR ".join(or_clauses) + ")")
                params.extend(f"%{v}%" for v in filters.diseases)
            else:
                cat_vals: list[str] = []
                std_vals: list[str] = []
                like_tokens: list[str] = []
                unmapped: list[str] = []
                for d in filters.diseases:
                    k = d.lower().strip()
                    if k in _SPECIFIC_DISEASE_LIKE:
                        # Specific disease — use standard mapping if any +
                        # LIKE on the curated keyword. Skip category widening.
                        if k in _DISEASE_KEYWORD_TO_STANDARD:
                            std_vals.append(_DISEASE_KEYWORD_TO_STANDARD[k])
                        like_tokens.append(_SPECIFIC_DISEASE_LIKE[k])
                    elif k in _DISEASE_KEYWORD_TO_CATEGORY:
                        cat_vals.append(_DISEASE_KEYWORD_TO_CATEGORY[k])
                    elif k in _DISEASE_KEYWORD_TO_STANDARD:
                        std_vals.append(_DISEASE_KEYWORD_TO_STANDARD[k])
                    else:
                        unmapped.append(d)
                sub: list[str] = []
                if cat_vals:
                    cat_vals = list(dict.fromkeys(cat_vals))
                    placeholders = ", ".join("?" * len(cat_vals))
                    sub.append(f"{_vc('disease_category', use_view)} IN ({placeholders})")
                    params.extend(cat_vals)
                if std_vals:
                    std_vals = list(dict.fromkeys(std_vals))
                    placeholders = ", ".join("?" * len(std_vals))
                    sub.append(f"{_vc('disease_standard', use_view)} IN ({placeholders})")
                    params.extend(std_vals)
                if like_tokens:
                    like_tokens = list(dict.fromkeys(like_tokens))
                    col = _vc("disease", use_view)
                    or_clauses = [f"{col} LIKE ?" for _ in like_tokens]
                    sub.append("(" + " OR ".join(or_clauses) + ")")
                    params.extend(f"%{t}%" for t in like_tokens)
                if unmapped:
                    col = _vc("disease", use_view)
                    or_clauses = [f"{col} LIKE ?" for _ in unmapped]
                    sub.append("(" + " OR ".join(or_clauses) + ")")
                    params.extend(f"%{v}%" for v in unmapped)
                if sub:
                    parts.append("(" + " OR ".join(sub) + ")" if len(sub) > 1 else sub[0])
        # Phase 20-A: cell_type LIKE — for canonical names with markers
        # like "+" or compound words, emit a wildcarded pattern that
        # tolerates DB-curation variants. For some anatomical cell types
        # (pancreatic islet, islets of langerhans) ALSO check the tissue
        # column since DB curation splits these across tissue / cell_type.
        if filters.cell_types and "cell_type" not in exclude:
            ct_col = _vc("cell_type", use_view)
            tissue_col = _vc("tissue", use_view)
            _loose = {
                "pancreatic islet": ["%pancreatic islet%", "%islet%"],
                "pancreatic beta cell": ["%pancreatic beta%", "%beta cell%"],
                "pancreatic alpha cell": ["%pancreatic alpha%", "%alpha cell%"],
                "regulatory T cell": ["%regulatory T cell%", "%Treg%"],
            }
            _also_tissue = {"pancreatic islet"}
            or_clauses: list[str] = []
            ct_params: list = []
            for v in filters.cell_types:
                raw = v.strip()
                if raw in _loose:
                    patterns = _loose[raw]
                else:
                    pattern = raw.replace("+ ", "% ").replace("+", "%")
                    patterns = [f"%{pattern}%"]
                for p in patterns:
                    or_clauses.append(f"{ct_col} LIKE ?")
                    ct_params.append(p)
                if raw in _also_tissue:
                    or_clauses.append(f"{tissue_col} LIKE ?")
                    ct_params.append(f"%{raw}%")
            if len(or_clauses) == 1:
                parts.append(or_clauses[0])
            else:
                parts.append("(" + " OR ".join(or_clauses) + ")")
            params.extend(ct_params)
        _in("source_database", filters.source_databases)
        # Phase 20-A: assay/platform on unified_series. Emit a sub-select
        # so both columns are checked AND short tokens like "10x" widen
        # to canonical variants. Use the LAST whitespace-separated token
        # of the canonical form (e.g. "10x 3' v3" → "10x") to keep the
        # LIKE generous for the typical user phrasing.
        if filters.assays and "assay" not in exclude:
            assay_tokens: list[str] = []
            for a in filters.assays:
                head = a.split()[0] if a else a
                if head and head not in assay_tokens:
                    assay_tokens.append(head)
                if a and a not in assay_tokens:
                    assay_tokens.append(a)
                # Phase 27: a platform-family stem so collapsed LLM forms
                # ("10xv3") still match the DB's spaced canonical values
                # ("10x 3' v3"). Without this, `assay LIKE '%10xv3%'` returned
                # 0 rows when 844 lung+normal 10x samples exist.
                fam = _assay_family_stem(a)
                if fam and fam not in assay_tokens:
                    assay_tokens.append(fam)
            or_clauses = []
            sub_params = []
            for t in assay_tokens:
                or_clauses.append("assay LIKE ? OR platform LIKE ?")
                sub_params.extend([f"%{t}%", f"%{t}%"])
            if _on_series_table:
                parts.append("(" + " OR ".join(or_clauses) + ")")
            else:
                parts.append(
                    "series_pk IN (SELECT pk FROM unified_series WHERE "
                    + " OR ".join(or_clauses) + ")"
                )
            params.extend(sub_params)
        # Phase 23-C: negated assay → exclude via NOT IN. A sample is
        # excluded if its series matches the assay; tolerate NULL series.
        if getattr(filters, "exclude_assays", None) and "assay" not in exclude:
            ex_tokens: list[str] = []
            for a in filters.exclude_assays:
                head = a.split()[0] if a else a
                if head and head not in ex_tokens:
                    ex_tokens.append(head)
                if a and a not in ex_tokens:
                    ex_tokens.append(a)
                fam = _assay_family_stem(a)
                if fam and fam not in ex_tokens:
                    ex_tokens.append(fam)
            or_clauses = []
            sub_params = []
            for t in ex_tokens:
                or_clauses.append("assay LIKE ? OR platform LIKE ?")
                sub_params.extend([f"%{t}%", f"%{t}%"])
            if _on_series_table:
                # COALESCE so NULL assay/platform (≈92% of series) are KEPT by
                # the exclusion, not dropped by NULL three-valued logic.
                ex = " OR ".join(
                    "COALESCE(assay,'') LIKE ? OR COALESCE(platform,'') LIKE ?"
                    for _ in ex_tokens
                )
                parts.append("NOT (" + ex + ")")
            else:
                parts.append(
                    "(series_pk IS NULL OR series_pk NOT IN "
                    "(SELECT pk FROM unified_series WHERE "
                    + " OR ".join(or_clauses) + "))"
                )
            params.extend(sub_params)
        # Organism: prefer organism_common (indexed) for canonical names
        if filters.organisms and "organism" not in exclude:
            commons: list[str] = []
            unmapped_org: list[str] = []
            for o in filters.organisms:
                k = o.lower().strip()
                mapped = _ORGANISM_KEYWORD_TO_COMMON.get(k)
                if mapped:
                    commons.append(mapped)
                else:
                    unmapped_org.append(o)
            sub: list[str] = []
            if commons:
                placeholders = ", ".join("?" * len(commons))
                sub.append(f"organism_common IN ({placeholders})")
                params.extend(commons)
            if unmapped_org:
                or_clauses = ["organism LIKE ?" for _ in unmapped_org]
                sub.append("(" + " OR ".join(or_clauses) + ")")
                params.extend(f"%{o}%" for o in unmapped_org)
            if len(sub) == 1:
                parts.append(sub[0])
            elif len(sub) > 1:
                parts.append("(" + " OR ".join(sub) + ")")
        # Use sex_normalized (indexed) for canonical sex values (male/female);
        # fall back to sex for raw values.
        if filters.sex and "sex" not in exclude:
            if filters.sex in ("male", "female"):
                parts.append("sex_normalized = ?")
                params.append(filters.sex)
            else:
                parts.append("sex = ?")
                params.append(filters.sex)
        _in("pmid", filters.pmids)

        # Normalised/categorical fields — exact match via IN()
        if filters.sample_types and "sample_type" not in exclude:
            # Phase 19-G: iPSC/PSC are aliases in curation — when one is
            # requested, widen to both AND OR cell_line_name LIKE '%iPSC%'.
            expanded = list(filters.sample_types)
            if "iPSC_derived" in expanded and "PSC_derived" not in expanded:
                expanded.append("PSC_derived")
            elif "PSC_derived" in expanded and "iPSC_derived" not in expanded:
                expanded.append("iPSC_derived")
            placeholders = ", ".join("?" * len(expanded))
            if "iPSC_derived" in expanded or "PSC_derived" in expanded:
                parts.append(
                    f"(sample_type IN ({placeholders}) "
                    f"OR cell_line_name LIKE '%iPSC%')"
                )
            else:
                parts.append(f"sample_type IN ({placeholders})")
            params.extend(expanded)
        if filters.disease_categories and "disease_category" not in exclude:
            placeholders = ", ".join("?" * len(filters.disease_categories))
            parts.append(f"disease_category IN ({placeholders})")
            params.extend(filters.disease_categories)
        if filters.tissue_systems and "tissue_system" not in exclude:
            placeholders = ", ".join("?" * len(filters.tissue_systems))
            parts.append(f"tissue_system IN ({placeholders})")
            params.extend(filters.tissue_systems)
        # Phase 33: developmental-stage filter (dev_stage_category values).
        if filters.development_stages and "development_stage" not in exclude:
            placeholders = ", ".join("?" * len(filters.development_stages))
            parts.append(f"dev_stage_category IN ({placeholders})")
            params.extend(filters.development_stages)

        # Sex via normalized column when searching via view
        if filters.sex and "sex_normalized" not in exclude and use_view:
            # Rely on _eq above if view contains sex col; else add the
            # normalized variant as well when available.
            pass

        # Exclusion conditions
        _not_like("tissue", filters.exclude_tissues)
        # Phase 23-C: if user excludes an umbrella disease (cancer, autoimmune,
        # neurological…), also exclude the corresponding disease_category so
        # rows like 'melanoma' / 'leukemia' get filtered even though they
        # don't contain the literal word "cancer".
        if filters.exclude_diseases:
            categories_to_exclude: list[str] = []
            for d in filters.exclude_diseases:
                k = d.lower().strip()
                if k in _DISEASE_KEYWORD_TO_CATEGORY and k not in _SPECIFIC_DISEASE_LIKE:
                    categories_to_exclude.append(_DISEASE_KEYWORD_TO_CATEGORY[k])
            _not_like("disease", filters.exclude_diseases)
            if categories_to_exclude and "disease_category" not in exclude:
                cats = list(dict.fromkeys(categories_to_exclude))
                placeholders = ", ".join("?" * len(cats))
                parts.append(
                    f"(disease_category IS NULL OR disease_category NOT IN ({placeholders}))"
                )
                params.extend(cats)
        _not_like("organism", filters.exclude_organisms)
        _not_in("source_database", filters.exclude_source_databases)
        if filters.exclude_sample_types and "sample_type" not in exclude:
            placeholders = ", ".join("?" * len(filters.exclude_sample_types))
            parts.append(f"sample_type NOT IN ({placeholders})")
            params.extend(filters.exclude_sample_types)
        if filters.exclude_disease_categories and "disease_category" not in exclude:
            # Note: also need IS NULL tolerance ("brain not tumor" should
            # include samples where disease_category is null)
            placeholders = ", ".join("?" * len(filters.exclude_disease_categories))
            parts.append(
                f"(disease_category IS NULL OR disease_category NOT IN ({placeholders}))"
            )
            params.extend(filters.exclude_disease_categories)

        if filters.min_cells is not None and "n_cells" not in exclude:
            parts.append("n_cells >= ?")
            params.append(filters.min_cells)
        if filters.min_citation_count is not None and "citation_count" not in exclude:
            col = _vc("citation_count", use_view)
            parts.append(f"{col} >= ?")
            params.append(filters.min_citation_count)

        # has_h5ad lives on unified_series — emit a sub-select predicate
        # on series_pk (the base table only joins to series via series_pk).
        # Phase 23-C: when the base table is already unified_series (target=
        # series queries), the column is just `has_h5ad` / `cell_count` —
        # no subquery needed. (_on_series_table is defined once at the top.)
        if filters.has_h5ad is not None and "has_h5ad" not in exclude:
            target = 1 if filters.has_h5ad else 0
            if _on_series_table:
                parts.append("has_h5ad = ?")
            else:
                parts.append(
                    "series_pk IN (SELECT pk FROM unified_series WHERE has_h5ad = ?)"
                )
            params.append(target)

        # series.cell_count (dataset-level total) — sub-select on series_pk.
        if filters.min_series_cells is not None and "min_series_cells" not in exclude:
            if _on_series_table:
                parts.append("cell_count >= ?")
            else:
                parts.append(
                    "series_pk IN (SELECT pk FROM unified_series WHERE cell_count >= ?)"
                )
            params.append(filters.min_series_cells)

        # Phase 19-G: treatment-present filter
        if getattr(filters, "treatment_present", None) is True \
                and "treatment_present" not in exclude:
            t_col = _vc("treatment", use_view)
            parts.append(f"({t_col} IS NOT NULL AND {t_col} != '')")

        # Phase 19-G: require_disease — strict "samples WHERE disease_category
        # IS NOT NULL". Pairs with exclude_disease_categories=['normal'] for
        # the full "diseased samples" semantic.
        if getattr(filters, "require_disease", None) is True \
                and "require_disease" not in exclude:
            dc_col = _vc("disease_category", use_view)
            parts.append(f"({dc_col} IS NOT NULL)")

        # Phase 32: require_pmid/doi/h5ad — let queries like "samples with
        # PMID" / "linked to a paper" map to a clean predicate rather than
        # collapsing to `WHERE 1=0`.
        if getattr(filters, "require_pmid", None) is True \
                and "require_pmid" not in exclude:
            # pmid lives on projects in this schema — use the join column.
            pm_col = _vc("pmid", use_view) if use_view else "p.pmid"
            parts.append(f"({pm_col} IS NOT NULL AND {pm_col} != '')")

        if getattr(filters, "require_doi", None) is True \
                and "require_doi" not in exclude:
            doi_col = _vc("doi", use_view) if use_view else "p.doi"
            parts.append(f"({doi_col} IS NOT NULL AND {doi_col} != '')")

        if getattr(filters, "require_h5ad", None) is True \
                and "require_h5ad" not in exclude:
            h_col = _vc("has_h5ad", use_view)
            parts.append(f"({h_col} = 1)")

        # Phase 32 F13: age_range filter — applied against age_numeric_min /
        # age_numeric_max which are populated for ~125k samples. Unit is
        # already standardised to years by the parser (_extract_age_range).
        # Semantics: a sample matches if its age range overlaps the query
        # range. For point ages (min == max) this collapses to a simple
        # range check. NULL ages drop out of the result set, which is the
        # right behaviour — you can't honour an age filter on a sample
        # whose age we don't know.
        age_range = getattr(filters, "age_range", None)
        if age_range and "age_range" not in exclude:
            lo, hi = age_range
            age_min_col = _vc("age_numeric_min", use_view)
            age_max_col = _vc("age_numeric_max", use_view)
            unit_col = _vc("age_unit_normalized", use_view)
            # Match only year-unit rows (the dominant unit; 4k weeks etc.
            # are mostly fetal samples that should be filtered separately).
            range_pred = (
                f"({age_min_col} IS NOT NULL AND {age_max_col} IS NOT NULL "
                f"AND {age_max_col} >= ? AND {age_min_col} <= ? "
                f"AND ({unit_col} = 'year' OR {unit_col} IS NULL))"
            )
            parts.append(range_pred)
            params.extend([lo, hi])

        # Temporal — publication_date lives on unified_projects, so emit a
        # subquery predicate on project_pk. Cheap because project_pk is the
        # primary key on the projects side.
        if filters.published_after or filters.published_before:
            proj_pk_col = "project_pk"
            sub_parts: list[str] = []
            sub_params: list = []
            if filters.published_after:
                sub_parts.append("publication_date >= ?")
                sub_params.append(filters.published_after)
            if filters.published_before:
                sub_parts.append("publication_date <= ?")
                sub_params.append(filters.published_before)
            sub_where = " AND ".join(sub_parts)
            parts.append(
                f"{proj_pk_col} IN (SELECT pk FROM unified_projects WHERE {sub_where})"
            )
            params.extend(sub_params)

        return parts, params

    # ---------- LLM生成 ----------

    async def _from_llm(
        self, query: ParsedQuery, entities: list[ResolvedEntity] | None, plan: JoinPlan,
    ) -> SQLCandidate | None:
        """LLM生成SQL"""
        if not self.llm:
            return None

        ddl = self.dal.schema_inspector.get_ddl_summary()
        prompt = f"""Generate a SQLite query for this request.

Schema:
{ddl}

View {self._main_view} joins samples+series+projects. Use it for simple queries.

User intent: {query.intent.name}
Target: {query.target_level}
Filters: tissues={query.filters.tissues}, diseases={query.filters.diseases}, organisms={query.filters.organisms}, assays={query.filters.assays}, cell_types={query.filters.cell_types}, sex={query.filters.sex}, sources={query.filters.source_databases}, free_text={query.filters.free_text}
Aggregation: {query.aggregation}

Rules:
- Use parameterized queries (?) for values
- Use LIKE '%term%' for text matching
- For text matching use COLLATE NOCASE or LOWER()
- Return ONLY the SQL, no explanation

SQL:"""

        response = await self.llm.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=1.0,
            max_tokens=512,
        )

        sql = response.content.strip()
        # 清理
        if sql.startswith("```"):
            sql = sql.split("```")[1].strip()
            if sql.startswith("sql"):
                sql = sql[3:].strip()
        sql = sql.rstrip(";")

        if not sql.upper().startswith("SELECT"):
            return None

        return SQLCandidate(sql=sql, params=[], method="llm")


class ParallelSQLExecutor:
    """
    并行SQL执行 + 渐进降级

    策略:
    1. 并行执行所有候选
    2. 第一个返回合理结果的候选胜出
    3. 全部失败 → 渐进放宽条件
    """

    CANDIDATE_TIMEOUT = 30.0  # 单候选超时(秒) — WSL+NTFS-backed SQLite needs headroom

    def __init__(self, dal: DatabaseAbstractionLayer, *, fallback_view: str = "v_sample_with_hierarchy"):
        self.dal = dal
        self._fallback_view = fallback_view

    async def execute(self, candidates: list[SQLCandidate]) -> ExecutionResult:
        """并行执行候选SQL"""
        if not candidates:
            return ExecutionResult.empty(["No SQL candidates"])

        # 创建并行任务
        tasks = [
            asyncio.create_task(self._execute_one(c))
            for c in candidates
        ]

        # as_completed: 第一个合理结果即返回
        errors: list[str] = []
        for coro in asyncio.as_completed(tasks, timeout=self.CANDIDATE_TIMEOUT + 12):
            try:
                result = await coro
                if result and result.validation.is_valid:
                    # 取消其余任务
                    for t in tasks:
                        if not t.done():
                            t.cancel()
                    return result
                elif result:
                    errors.append(f"{result.method}: {result.validation.issue}")
            except asyncio.TimeoutError:
                errors.append("timeout")
            except asyncio.CancelledError:
                pass
            except Exception as e:
                errors.append(str(e))

        # 全部失败 → 渐进降级
        return await self._fallback(candidates, errors)

    async def _execute_one(self, candidate: SQLCandidate) -> ExecutionResult | None:
        """执行单个候选 — wraps the sync SQL call in a thread so timeouts work."""
        try:
            t0 = time.perf_counter()
            # Run the blocking sqlite execute off the event loop so the outer
            # as_completed timeout can actually interrupt it.
            result = await asyncio.wait_for(
                asyncio.to_thread(self.dal.execute, candidate.sql, candidate.params),
                timeout=self.CANDIDATE_TIMEOUT,
            )
            elapsed = (time.perf_counter() - t0) * 1000

            # If the query hit the LIMIT, run a cheap COUNT(*) against the same
            # WHERE clause so the agent reports the true total. This lets the
            # caller distinguish "all 6415 results" from "first 100 results of
            # 6415" — important for benchmark limit-aware recall.
            true_total = len(result.rows)

            # Phase 19-B: aggregation queries (GROUP BY) — total_count should
            # reflect the sample-level total (sum across groups), not the number
            # of groups. Sum the 'count' column when present.
            sql_upper_check = candidate.sql.upper()
            if "GROUP BY" in sql_upper_check and result.rows:
                first_row = result.rows[0]
                if isinstance(first_row, dict) and "count" in first_row:
                    try:
                        true_total = sum(int(r.get("count") or 0)
                                         for r in result.rows)
                    except (TypeError, ValueError):
                        pass
            # Candidate may supply an explicit count_sql (stratified queries
            # set this because the automatic LIMIT-strip rewrite undercounts
            # inner UNION branches).
            if candidate.count_sql:
                try:
                    count_result = await asyncio.wait_for(
                        asyncio.to_thread(
                            self.dal.execute, candidate.count_sql,
                            candidate.count_params or candidate.params,
                        ),
                        timeout=self.CANDIDATE_TIMEOUT,
                    )
                    if count_result.rows:
                        true_total = int(count_result.rows[0]["c"])
                except asyncio.TimeoutError:
                    pass
                except Exception as ex:
                    logger.debug("Explicit count_sql failed: %s", ex)
            else:
                sql_upper = candidate.sql.upper()
                if "LIMIT" in sql_upper and len(result.rows) >= 1:
                    try:
                        # Extract the LAST LIMIT clause (outermost query). Use regex
                        # to handle whitespace variations (\n, \t, multiple spaces).
                        import re
                        matches = list(re.finditer(r"\bLIMIT\s+(\d+)", sql_upper))
                        if matches:
                            last = matches[-1]
                            limit_value = int(last.group(1))
                            if len(result.rows) >= limit_value:
                                base_sql = candidate.sql[:last.start()]
                                # Strip trailing ORDER BY — it doesn't change COUNT
                                order_match = re.search(r"\bORDER\s+BY\s+", base_sql, re.IGNORECASE)
                                if order_match:
                                    base_sql = base_sql[:order_match.start()]
                                # Optimisation: if the SELECT scans the view, the COUNT(*)
                                # wrapper has to JOIN samples+series+projects which is
                                # usually 5-10x slower than COUNT on the base table.
                                # Rewrite `FROM v_sample_with_hierarchy` →
                                # `FROM unified_samples` for the COUNT alias only;
                                # the column predicates we use (tissue_standard,
                                # disease_category, sample_type, organism_common,
                                # sex_normalized) all live on the base table.
                                count_base = base_sql
                                if self._fallback_view in count_base and "JOIN" not in count_base.upper():
                                    # Map view-only column names back to base table
                                    count_base = count_base.replace(
                                        f"FROM {self._fallback_view}", "FROM unified_samples"
                                    ).replace("sample_pk", "pk").replace("sample_source", "source_database")
                                count_sql = f"SELECT COUNT(*) AS c FROM ({count_base})"
                                try:
                                    count_result = await asyncio.wait_for(
                                        asyncio.to_thread(
                                            self.dal.execute, count_sql, candidate.params,
                                        ),
                                        timeout=self.CANDIDATE_TIMEOUT,
                                    )
                                    if count_result.rows:
                                        true_total = int(count_result.rows[0]["c"])
                                except asyncio.TimeoutError:
                                    # COUNT was too slow — fall back to len(rows).
                                    pass
                                except Exception as ex:
                                    logger.debug("COUNT rewrite failed: %s", ex)
                    except Exception as ex:
                        logger.debug("True-total COUNT wrap failed: %s", ex)

            # 验证
            validation = self._validate(result, candidate)

            return ExecutionResult(
                rows=result.rows,
                columns=result.columns,
                sql=candidate.sql,
                params=candidate.params,
                method=candidate.method,
                exec_time_ms=round(elapsed, 2),
                row_count=true_total,  # report the TRUE total, not len(rows)
                validation=validation,
                metadata={"fetched_rows": len(result.rows)},
            )
        except asyncio.TimeoutError:
            logger.warning("SQL execution timeout [%s] after %.1fs", candidate.method, self.CANDIDATE_TIMEOUT)
            return ExecutionResult(
                sql=candidate.sql,
                method=candidate.method,
                validation=ValidationResult(is_valid=False, issue="timeout"),
            )
        except Exception as e:
            logger.warning("SQL execution failed [%s]: %s", candidate.method, e)
            return ExecutionResult(
                sql=candidate.sql,
                method=candidate.method,
                validation=ValidationResult(is_valid=False, issue=str(e)),
            )

    def _validate(self, result, candidate: SQLCandidate) -> ValidationResult:
        """结果验证"""
        if not result.rows:
            return ValidationResult(
                is_valid=False, issue="zero_results",
                suggestion="try_broader_query",
            )
        if len(result.rows) > 10000:
            return ValidationResult(
                is_valid=True,
                note=f"Large result set: {len(result.rows)} rows",
            )
        return ValidationResult(is_valid=True)

    async def _fallback(self, candidates: list[SQLCandidate], errors: list[str]) -> ExecutionResult:
        """渐进降级 — Level 1: `=`→`LIKE`; Level 1b (Phase 28.D): `IN (?,…)`
        → `(LOWER(col) LIKE ? OR …)` for string params; Level 2: empty.
        """
        if not candidates:
            return ExecutionResult.empty(errors)

        base = candidates[0]

        # Level 1: 同时处理 `=` 和 `IN (?, ?, …)` —— 多实体查询用 IN，
        # 所以单独的 `=` → `LIKE` 兜不到 ontology-expanded 路径。
        relaxed, params = _relax_sql_for_fuzzy(base.sql, base.params or [])
        try:
            result = self.dal.execute(relaxed, params)
            if result.rows:
                return ExecutionResult(
                    rows=result.rows,
                    columns=result.columns,
                    sql=relaxed,
                    params=params,
                    method="fallback_fuzzy",
                    exec_time_ms=result.execution_time_ms,
                    row_count=len(result.rows),
                    validation=ValidationResult(
                        is_valid=True,
                        note="降级到模糊匹配获得结果",
                    ),
                )
        except Exception as e:
            logger.warning("fallback_fuzzy execution failed: %s", e)

        # Level 2: If the relaxed query also fails, return an empty result with
        # a note — DO NOT return the first 10 000 rows of the database. That
        # "explore" fallback looks helpful in theory but is actively harmful
        # for safety (injection / nonsense queries are silently rewarded with
        # the whole dataset). Callers can still surface a suggestion to the
        # user to broaden their query.
        return ExecutionResult(
            rows=[],
            columns=[],
            sql=base.sql,
            params=base.params,
            method="no_match",
            exec_time_ms=0.0,
            row_count=0,
            validation=ValidationResult(
                is_valid=True,
                note="查询无结果 - 未触发探索式回退",
            ),
        )
