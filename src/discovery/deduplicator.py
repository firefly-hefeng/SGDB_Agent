"""Cross-source duplicate detection.

Same single-cell study often shows up in multiple databases under different
accession formats:

- GEO   : ``GSE12345``
- EBI   : ``E-GEOD-12345`` (ArrayExpress mirror) or ``S-GEOD-12345``
- SCEA  : ``E-GEOD-12345`` again

We extract a canonical key from each accession; results sharing a key are
the same study. Rather than collapsing rows (which would distort per-source
counts and metrics), we annotate each result with ``mirrors`` — pointers to
the same study in other sources. The UI can then render a "also in EBI/SCEA"
badge.
"""

from __future__ import annotations

import re
from collections import defaultdict

from src.discovery.models import DiscoveryResult, MirrorRef

# Canonical-key extractors. Order matters for output: the first regex that
# matches an accession also names the canonical-source preference.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("GEO", re.compile(r"^GSE(\d+)$", re.IGNORECASE)),
    ("GEO", re.compile(r"^E-GEOD-(\d+)$", re.IGNORECASE)),
    ("GEO", re.compile(r"^S-GEOD-(\d+)$", re.IGNORECASE)),
    ("MTAB", re.compile(r"^E-MTAB-(\d+)$", re.IGNORECASE)),
    ("MTAB", re.compile(r"^S-BSST-?(\d+)$", re.IGNORECASE)),
    ("ANND", re.compile(r"^E-ANND-(\d+)$", re.IGNORECASE)),
]


def canonical_key(accession: str) -> str | None:
    """Return a cross-source canonical key for an accession, or ``None``.

    Two accessions that map to the same key refer to the same study.
    Accessions we don't recognise return ``None`` and are not deduped.
    """
    for family, pat in _PATTERNS:
        m = pat.match(accession or "")
        if m:
            return f"{family}:{m.group(1)}"
    return None


def annotate_mirrors(sources: list[DiscoveryResult]) -> None:
    """Mutate ``sources`` in place: fill ``DatasetResult.mirrors`` for any
    result that shares a canonical key with a result in another source.

    Stable: ``mirrors`` lists are sorted by ``source_db`` so output is
    deterministic across runs.
    """
    # key → list of (source_db, id, source_url)
    groups: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for src in sources:
        for r in src.results:
            key = canonical_key(r.id)
            if key:
                groups[key].append((r.source_db, r.id, r.source_url))

    if not groups:
        return

    # Pre-build the mirror list once per key (excluding self at lookup time).
    for src in sources:
        for r in src.results:
            key = canonical_key(r.id)
            if key is None:
                continue
            siblings = groups[key]
            if len(siblings) <= 1:
                continue
            mirrors = [
                MirrorRef(source_db=db, id=acc, source_url=url)
                for (db, acc, url) in siblings
                if not (db == r.source_db and acc == r.id)
            ]
            mirrors.sort(key=lambda m: (m.source_db, m.id))
            r.mirrors = mirrors
