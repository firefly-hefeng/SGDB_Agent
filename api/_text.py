"""Best-effort repair of UTF-8↔CP1252 "mojibake" in source metadata.

A subset of ingested records had their UTF-8 bytes decoded as CP1252/Latin-1,
leaving artefacts like ``â€“`` (en-dash), ``â€™`` (apostrophe), ``Ã©`` (é). We
reverse it by re-encoding as CP1252 and decoding as UTF-8 — but ONLY when the
string shows a mojibake marker AND the round-trip succeeds, so clean ASCII,
already-correct accented text, and non-Latin scripts (e.g. CJK) are never
altered.

Phase 34: surfaced in dataset-detail titles and featured-collection cards
("Alzheimerâ€™s disease"). This is a display-side repair (non-destructive,
survives DB rebuilds); the ingestion pipeline should ultimately fix the source.
"""
from __future__ import annotations

# Lead characters of UTF-8 multibyte sequences misdecoded as a single-byte
# codec: Ã (0xC3), Â (0xC2), â (0xE2). Cheap pre-filter — the encode/decode
# round-trip below is what actually proves a string is mojibake.
_MOJIBAKE_MARKERS = ("Ã", "Â", "â")


def fix_mojibake(s: str | None) -> str | None:
    """Return ``s`` with UTF-8↔single-byte-codec mojibake repaired, or unchanged
    if it is clean / can't be safely repaired.

    Source data shows two flavours, depending on which codec mangled the bytes:
      * CP1252  — e.g. ``â€“`` (en-dash), ``â€™`` (apostrophe)
      * Latin-1 — e.g. ``â\\x80\\x99`` (apostrophe), where 0x80/0x99 aren't valid
        CP1252 code points.
    We try CP1252 first, then Latin-1 (which round-trips any 0x00–0xFF byte).
    A repair is accepted only if the round-trip yields valid UTF-8; otherwise the
    original is returned — so clean ASCII, already-correct accents, and non-Latin
    scripts (CJK) are never altered.
    """
    if not s or not isinstance(s, str):
        return s
    if not any(m in s for m in _MOJIBAKE_MARKERS):
        return s
    for codec in ("cp1252", "latin-1"):
        try:
            repaired = s.encode(codec).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        # Only accept if it actually changed something and removed the markers.
        if repaired != s:
            return repaired
    return s
