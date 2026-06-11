"""Lightweight UBERON/MONDO-style synonym map for biomedical terms.

The agent's headline failure mode in BASELINE_v1 was the gap between user
phrasing ("PFC", "AD") and the canonical metadata phrasing
("prefrontal cortex", "Alzheimer disease"). A real solution needs a
proper UBERON/MONDO ontology lookup; this module is the
**lightweight precursor** — a hand-curated synonym dictionary covering
the abbreviations and lay-name → canonical mappings that show up in
queries from working scientists.

Usage::

    from src.synonym_map import expand_intent_terms
    expanded = expand_intent_terms(intent)
    # expanded.disease may now contain ["Alzheimer disease", "AD"]
    # expanded.tissue may now contain ["prefrontal cortex", "PFC", "frontal cortex"]

Design notes:

- **Bidirectional**: query "PFC" expands to also include "prefrontal
  cortex"; query "Alzheimer disease" expands to include "AD". This way
  whichever side has metadata in canonical form can match.
- **Idempotent**: expanding twice yields the same set.
- **Conservative**: only mappings that are unambiguous in single-cell
  context. We do NOT map every shared substring.
- **Bilingual**: Chinese terms map to their canonical English forms via
  ``intent_parser._fallback_parse``; this module then expands to other
  English variants of the same concept.
"""

from __future__ import annotations

from src.discovery.models import QueryIntent

# Disease aliases. Each line: canonical → list of aliases that should
# co-exist in the disease field. We add the canonical *and* the aliases
# whenever any of them is present.
_DISEASE_GROUPS: list[set[str]] = [
    # Neurodegenerative
    {"Alzheimer disease", "AD", "Alzheimer's", "Alzheimer's disease",
     "Alzheimer", "AD dementia"},
    {"Parkinson disease", "PD", "Parkinson's", "Parkinson's disease",
     "Parkinson"},
    {"Huntington disease", "HD", "Huntington's"},
    {"amyotrophic lateral sclerosis", "ALS", "Lou Gehrig's disease",
     "motor neuron disease"},
    {"multiple sclerosis", "MS"},

    # Metabolic
    {"type 2 diabetes", "T2D", "T2DM", "type II diabetes",
     "type 2 diabetes mellitus", "diabetes mellitus type 2"},
    {"type 1 diabetes", "T1D", "T1DM", "type I diabetes",
     "type 1 diabetes mellitus"},

    # Infectious
    {"COVID-19", "COVID", "SARS-CoV-2 infection", "coronavirus disease 2019"},

    # Cancers
    {"glioblastoma", "GBM", "glioblastoma multiforme"},
    {"renal cell carcinoma", "RCC", "ccRCC", "clear cell RCC",
     "kidney cancer"},
    {"hepatocellular carcinoma", "HCC", "liver cancer", "primary liver cancer"},
    {"breast cancer", "BRCA-cancer", "mammary carcinoma", "breast carcinoma"},
    {"pancreatic cancer", "PDAC", "pancreatic ductal adenocarcinoma"},
    {"colorectal cancer", "CRC", "colon cancer"},
    {"melanoma", "cutaneous melanoma", "metastatic melanoma"},
    {"non-small cell lung cancer", "NSCLC", "lung adenocarcinoma", "LUAD"},

    # GI / IBD
    {"inflammatory bowel disease", "IBD",
     "Crohn disease", "Crohn's disease", "CD",
     "ulcerative colitis", "UC"},

    # Other
    {"atrial fibrillation", "AFib", "AF"},
    {"age-related macular degeneration", "AMD", "macular degeneration"},
    {"systemic lupus erythematosus", "SLE", "lupus"},
    {"rheumatoid arthritis", "RA"},
]

# Tissue / anatomy aliases (UBERON-flavoured).
_TISSUE_GROUPS: list[set[str]] = [
    # Brain regions
    {"prefrontal cortex", "PFC", "frontal cortex", "dorsolateral prefrontal cortex",
     "DLPFC"},
    {"entorhinal cortex", "EC"},
    {"hippocampus", "hippocampal formation"},
    {"substantia nigra", "SN", "SNc", "substantia nigra pars compacta"},
    {"cerebral cortex", "cortex", "neocortex"},
    # Brain: include common anatomical sub-regions so a "brain"
    # query reaches collections whose tissue labels are sub-parts
    # (CellXGene zebrafish atlases label tissues as ``forebrain`` /
    # ``midbrain`` / ``hindbrain`` rather than the umbrella ``brain``).
    {"brain", "encephalon", "forebrain", "midbrain", "hindbrain",
     "cerebrum", "telencephalon", "diencephalon",
     "ganglionic layer of retina"},
    {"spinal cord", "spinal column"},
    {"striatum", "corpus striatum", "neostriatum"},
    {"cerebellum"},

    # Cardiovascular
    {"heart", "myocardium", "cardiac tissue", "cardiac muscle"},
    {"atrium", "atria", "left atrium", "right atrium"},
    {"ventricle", "left ventricle", "right ventricle"},

    # Respiratory
    {"lung", "pulmonary tissue", "lung tissue"},
    {"bronchoalveolar lavage", "BAL", "bronchoalveolar lavage fluid", "BALF"},
    {"nasal mucosa", "nasopharynx", "nasal epithelium"},

    # Digestive
    {"liver", "hepatic tissue", "hepatocyte tissue"},
    {"pancreas", "pancreatic tissue"},
    {"pancreatic islet", "islet of Langerhans", "islets of Langerhans",
     "pancreatic islets"},
    # GI tract: merged so a "gut" intent reaches collections labelled
    # "small intestine" / "colon" / "ileum" etc. Anatomically these are
    # all parts of the same tract.
    {"gut", "intestinal tract", "GI tract", "gastrointestinal tract",
     "intestine", "small intestine", "large intestine", "ileum",
     "jejunum", "duodenum", "colon", "large bowel", "sigmoid colon",
     "rectum"},
    {"stomach", "gastric tissue", "gastric mucosa"},
    {"esophagus", "oesophagus"},

    # Hematopoietic / immune
    {"peripheral blood", "blood", "PBMC", "peripheral blood mononuclear cells"},
    {"bone marrow", "BM", "marrow"},
    {"thymus"},
    {"spleen", "splenic tissue"},
    {"lymph node", "LN"},

    # Renal / urinary
    {"kidney", "renal tissue", "renal cortex", "renal medulla"},

    # Reproductive
    {"breast", "mammary gland", "mammary tissue"},
    {"ovary", "ovarian tissue"},

    # Musculoskeletal / skin / etc.
    {"skin", "epidermis", "dermis", "cutaneous tissue"},
    {"muscle", "skeletal muscle"},
    {"adipose tissue", "adipose", "fat tissue"},
    {"retina", "retinal tissue"},
    {"cornea", "corneal tissue"},
    {"pituitary gland", "pituitary"},
    {"adrenal gland", "adrenal", "adrenal cortex", "adrenal medulla"},
]

# Technology aliases.
_TECH_GROUPS: list[set[str]] = [
    {"scRNA-seq", "scRNA", "single-cell RNA sequencing", "single cell RNA-seq",
     "single-cell RNA-seq", "single cell transcriptomics"},
    {"snRNA-seq", "snRNA", "single-nucleus RNA sequencing",
     "single nucleus RNA-seq", "single-nucleus RNA-seq"},
    {"10x Genomics", "10x Chromium", "10X", "Chromium",
     "10x Genomics Chromium"},
    {"Smart-seq2", "SMART-seq2", "smart-seq2"},
    {"Smart-seq3", "SMART-seq3", "smart-seq3"},
    {"Smart-seq", "SMART-seq", "smart-seq"},
    {"CITE-seq", "cite-seq"},
    {"scATAC-seq", "single-cell ATAC-seq", "single cell ATAC-seq"},
    {"snATAC-seq", "single-nucleus ATAC-seq"},
    {"Visium", "10x Visium", "spatial transcriptomics", "Spatial Transcriptomics"},
    {"Slide-seq", "slide-seq", "Slide-seqV2"},
    {"MERFISH", "merfish"},
    {"Perturb-seq", "perturb-seq", "CRISPR perturb-seq"},
    {"bulk RNA-seq", "RNA-seq", "RNA sequencing"},  # NOTE: "RNA-seq" is ambiguous
]


def _build_lookup(groups: list[set[str]]) -> dict[str, set[str]]:
    """Each lowercase synonym → the full alias set it belongs to."""
    out: dict[str, set[str]] = {}
    for g in groups:
        canonical = g
        for term in g:
            out[term.lower()] = canonical
    return out


_DISEASE_LOOKUP = _build_lookup(_DISEASE_GROUPS)
_TISSUE_LOOKUP = _build_lookup(_TISSUE_GROUPS)
_TECH_LOOKUP = _build_lookup(_TECH_GROUPS)


def _expand_field(values: list[str], lookup: dict[str, set[str]]) -> list[str]:
    """Return ``values`` plus any synonyms from the lookup table.

    Preserves order and uniqueness. Unknown terms pass through unchanged.
    """
    result: list[str] = []
    seen: set[str] = set()

    def _add(term: str) -> None:
        key = term.strip()
        low = key.lower()
        if low and low not in seen:
            seen.add(low)
            result.append(key)

    for v in values or []:
        _add(v)
        synonyms = lookup.get(v.strip().lower())
        if synonyms:
            for s in synonyms:
                _add(s)
    return result


def expand_intent_terms(intent: QueryIntent) -> QueryIntent:
    """Return a copy of ``intent`` with disease/tissue/tech expanded by
    the synonym map. Other fields pass through unchanged.
    """
    return QueryIntent(
        disease=_expand_field(intent.disease, _DISEASE_LOOKUP),
        tissue=_expand_field(intent.tissue, _TISSUE_LOOKUP),
        tech=_expand_field(intent.tech, _TECH_LOOKUP),
        species=list(intent.species),
        keywords=list(intent.keywords),
        time_hint=intent.time_hint,
        restrict_sources=(
            list(intent.restrict_sources) if intent.restrict_sources else None
        ),
        negative_terms=list(intent.negative_terms),
    )
