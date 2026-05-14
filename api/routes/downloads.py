"""
Download routes — download options and bulk manifest generation.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import io
import logging

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.deps import get_dal
from api.services.download_resolver import DownloadOption, DownloadResolver
from api.services.ena_resolver import human_bytes

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/scdbAPI", tags=["downloads"])

_resolver = DownloadResolver()

# How many datasets to resolve against ENA/GEO concurrently. ENA is the bottleneck
# (~0.5-2 s/accession cold, ~0 cached); 8 keeps us well under ENA's fair-use limits.
_DEEP_CONCURRENCY = 8
# Cap on datasets per manifest. Deep resolution is bounded by this × per-call timeout.
_MANIFEST_CAP = 300


class ManifestEntryIn(BaseModel):
    """A manifest entry carried from the client (localStorage). Used so that
    Discover-sourced datasets — which are NOT in the local catalog and thus
    can't be re-resolved by id server-side — still land in the generated
    script via the URL the client already has (Phase 27 D3/Issue 5)."""
    id: str
    source_db: str = ""
    url: str | None = None
    file_type: str | None = None
    title: str | None = None


class ManifestRequest(BaseModel):
    entity_ids: list[str] = []
    # Phase 27: optional inline manifest entries (with their known URLs). When
    # an id can't be resolved from the local catalog, we fall back to the URL
    # the client supplied here instead of silently dropping the dataset.
    entries: list[ManifestEntryIn] = []
    file_types: list[str] = ["fastq"]
    # Phase 27: tsv | bash | aria2 | snakemake | python. The bash/python/
    # snakemake generators are now production-grade (dependency checks, retry,
    # logging, per-dataset directories, success/failure tracking).
    format: str = "tsv"
    # Phase 36: resolve the *exact* files (with sizes + MD5) from ENA/GEO live,
    # instead of just emitting directory/page pointers. On by default — it is the
    # whole point of the downloader — but can be turned off for an instant manifest.
    deep: bool = True


class EstimateRequest(BaseModel):
    entity_ids: list[str] = []
    entries: list[ManifestEntryIn] = []
    file_types: list[str] = ["fastq", "bam", "h5ad", "rds", "matrix", "supplementary"]
    deep: bool = True


def _option_to_dict(o: DownloadOption) -> dict:
    return {
        "file_type": o.file_type, "label": o.label, "url": o.url,
        "instructions": o.instructions, "source": o.source,
        "file_size_human": o.file_size_human, "checksum_note": o.checksum_note,
        "bytes": o.bytes, "aspera_url": o.aspera_url, "md5": o.md5, "run": o.run,
    }


def _load_context(dal, entity, entity_data) -> tuple[dict | None, list[dict]]:
    """Load the project row + up to 50 series rows for an entity.

    `get_entity_by_id` returns a raw table row with no `_type` marker, so we infer
    the row kind from its columns: a *project* row has no `project_pk` column,
    whereas *sample*/*series* rows do. (Before Phase 36 this used a non-existent
    `_type` field, so project look-ups never loaded their series — and CellXGene
    h5ad downloads silently never appeared.)"""
    if "project_pk" in entity_data:           # sample or series row
        project_pk = entity_data.get("project_pk")
    else:                                      # project row
        project_pk = entity_data.get("pk")
    project_data = None
    series_list: list[dict] = []
    if project_pk:
        result = dal.execute("SELECT * FROM unified_projects WHERE pk = ?", [project_pk])
        if result.rows:
            project_data = result.rows[0]
        # Downloads need the *whole* collection (one h5ad per CellXGene series),
        # so cap higher than the usual 50 — a user bulk-downloading a 138-dataset
        # atlas should get all of it, not an arbitrary first 50.
        result = dal.execute(
            "SELECT * FROM unified_series WHERE project_pk = ? LIMIT 500", [project_pk]
        )
        series_list = [dict(r) for r in result.rows]
    return project_data, series_list


@router.get("/downloads/{id_value}")
async def get_downloads(id_value: str, deep: bool = False):
    """Get download options for an entity.

    `deep=true` resolves the exact files (with sizes + MD5 + Aspera paths) live
    from ENA / GEO, instead of just returning directory/page pointers."""
    dal = get_dal()
    if dal is None:
        raise HTTPException(status_code=503, detail="Database not available")

    entity = dal.get_entity_by_id(id_value)
    if entity is None:
        # Phase 32: avoid echoing arbitrary user input in error bodies.
        raise HTTPException(status_code=404, detail="Entity not found")

    entity_data = {k: v for k, v in entity.items() if not k.startswith("_")}
    project_data, series_list = _load_context(dal, entity, entity_data)

    if deep:
        options = await _resolver.resolve_deep(entity_data, series_list, project_data)
    else:
        options = _resolver.resolve(entity_data, series_list, project_data)

    total_bytes = sum(o.bytes or 0 for o in options if o.bytes)
    return {
        "entity_id": id_value,
        "source_database": entity_data.get("source_database", ""),
        "deep": deep,
        "total_bytes": total_bytes or None,
        "total_size_human": human_bytes(total_bytes),
        "downloads": [_option_to_dict(o) for o in options],
    }


def _dedupe_ids(entity_ids: list[str], entry_by_id: dict) -> list[str]:
    all_ids: list[str] = []
    for eid in list(entity_ids) + list(entry_by_id.keys()):
        if eid and eid not in all_ids:
            all_ids.append(eid)
    return all_ids


async def _collect_downloads(
    dal, entity_ids: list[str], entries: list, file_types: list[str], deep: bool
) -> tuple[list[dict], dict, set[str]]:
    """Resolve a set of ids into a flat list of download dicts (with sizes + md5).

    Returns (all_downloads, notes, available_types). Shared by /manifest and
    /estimate. When deep=True, ENA/GEO resolution runs concurrently behind one
    httpx client + a bounded semaphore."""
    entry_by_id = {e.id: e for e in entries if e.id}
    all_ids = _dedupe_ids(entity_ids, entry_by_id)[:_MANIFEST_CAP]

    # Phase: gather DB context for every id first (fast on ext4). Each item is
    # (eid, entity_data | None, series_list, project_data).
    contexts: list[tuple[str, dict | None, list[dict], dict | None]] = []
    for eid in all_ids:
        entity = dal.get_entity_by_id(eid)
        if not entity:
            contexts.append((eid, None, [], None))
            continue
        entity_data = {k: v for k, v in entity.items() if not k.startswith("_")}
        project_data, series_list = _load_context(dal, entity, entity_data)
        contexts.append((eid, entity_data, series_list, project_data))

    # Phase: resolve options (deep = live ENA/GEO, concurrent; else instant).
    resolved: dict[str, list[DownloadOption]] = {}
    deep_ctxs = [c for c in contexts if c[1] is not None]
    if deep and deep_ctxs:
        sem = asyncio.Semaphore(_DEEP_CONCURRENCY)
        async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
            async def _one(eid, ed, sl, pd):
                async with sem:
                    try:
                        resolved[eid] = await _resolver.resolve_deep(ed, sl, pd, client=client)
                    except Exception as exc:  # never let one bad id sink the batch
                        logger.warning("deep resolve failed for %s: %s", eid, exc)
                        resolved[eid] = _resolver.resolve(ed, sl, pd)
            await asyncio.gather(*(_one(eid, ed, sl, pd) for eid, ed, sl, pd in deep_ctxs))
    else:
        for eid, ed, sl, pd in deep_ctxs:
            resolved[eid] = _resolver.resolve(ed, sl, pd)

    # Phase: flatten to download dicts + build the why-skipped diagnostics.
    all_downloads: list[dict] = []
    unresolved: list[str] = []
    unmatched: dict[str, list[str]] = {}
    available_types: set[str] = set()

    def _inline_fallback(eid: str) -> bool:
        inline = entry_by_id.get(eid)
        if inline and inline.url and not any(d["entity_id"] == eid for d in all_downloads):
            all_downloads.append({
                "entity_id": eid, "file_type": inline.file_type or "file",
                "url": inline.url, "label": inline.title or eid, "instructions": "",
                "bytes": None, "md5": None, "aspera_url": None, "run": None,
            })
            return True
        return False

    for eid, entity_data, _sl, _pd in contexts:
        if entity_data is None:
            if not _inline_fallback(eid):
                unresolved.append(eid)
            continue
        options = resolved.get(eid, [])
        matched_here = 0
        offered_here: list[str] = []
        for o in options:
            if o.url:
                available_types.add(o.file_type)
                offered_here.append(o.file_type)
            if o.url and o.file_type in file_types:
                matched_here += 1
                all_downloads.append({
                    "entity_id": eid, "file_type": o.file_type, "url": o.url,
                    "label": o.label, "instructions": o.instructions,
                    "bytes": o.bytes, "md5": o.md5, "aspera_url": o.aspera_url,
                    "run": o.run,
                })
        if matched_here == 0 and not _inline_fallback(eid) and offered_here:
            unmatched[eid] = sorted(set(offered_here))

    notes = {"unresolved": unresolved, "unmatched": unmatched,
             "requested_types": file_types}
    return all_downloads, notes, available_types


@router.post("/downloads/manifest")
async def generate_manifest(req: ManifestRequest):
    """Generate a bulk download manifest file (TSV, bash, aria2, Snakemake, Python).

    Phase 36: deep=True (default) resolves the exact files with sizes + MD5 from
    ENA / GEO, so the script downloads real files and verifies their checksums —
    not just a directory pointer."""
    dal = get_dal()
    if dal is None:
        raise HTTPException(status_code=503, detail="Database not available")

    entry_by_id = {e.id: e for e in req.entries if e.id}
    if not _dedupe_ids(req.entity_ids, entry_by_id):
        raise HTTPException(status_code=400, detail="No entity IDs provided")

    all_downloads, notes, available_types = await _collect_downloads(
        dal, req.entity_ids, req.entries, req.file_types, req.deep
    )

    if not all_downloads:
        # D2: an honest, actionable error instead of a bare "not found".
        avail = ", ".join(sorted(available_types)) or "none"
        raise HTTPException(
            status_code=404,
            detail=(
                f"No files of type [{', '.join(req.file_types)}] for the given IDs. "
                f"Available types for these datasets: [{avail}]. "
                f"{len(notes['unresolved'])} ID(s) were not found in the catalog."
            ),
        )

    if req.format == "bash":
        return _generate_bash(all_downloads, notes)
    elif req.format == "aria2":
        return _generate_aria2(all_downloads, notes)
    elif req.format == "snakemake":
        return _generate_snakemake(all_downloads, notes)
    elif req.format == "python":
        return _generate_python(all_downloads, notes)
    else:
        return _generate_tsv(all_downloads)


@router.post("/downloads/estimate")
async def estimate_downloads(req: EstimateRequest):
    """Estimate the size of a download set before committing.

    Returns the resolved file count, total bytes, a human total, a per-source
    breakdown, and which ids could not be resolved — so the UI can warn before a
    user kicks off a multi-terabyte pull."""
    dal = get_dal()
    if dal is None:
        raise HTTPException(status_code=503, detail="Database not available")

    entry_by_id = {e.id: e for e in req.entries if e.id}
    all_ids = _dedupe_ids(req.entity_ids, entry_by_id)
    if not all_ids:
        raise HTTPException(status_code=400, detail="No entity IDs provided")

    all_downloads, notes, available_types = await _collect_downloads(
        dal, req.entity_ids, req.entries, req.file_types, req.deep
    )

    total_bytes = sum(d.get("bytes") or 0 for d in all_downloads)
    sized = sum(1 for d in all_downloads if d.get("bytes"))
    by_source: dict[str, dict] = {}
    datasets = set()
    for d in all_downloads:
        datasets.add(d["entity_id"])
        # derive source from the url host (best-effort) for the breakdown
        url = d.get("url") or ""
        if "sra.ebi.ac.uk" in url or "ena" in url:
            src = "ENA/SRA"
        elif "ncbi.nlm.nih.gov/geo" in url:
            src = "GEO"
        elif "cellxgene" in url:
            src = "CellXGene"
        elif "ebi.ac.uk" in url:
            src = "EBI"
        else:
            src = "other"
        b = by_source.setdefault(src, {"files": 0, "bytes": 0})
        b["files"] += 1
        b["bytes"] += d.get("bytes") or 0

    return {
        "dataset_count": len(datasets),
        "file_count": len(all_downloads),
        "sized_file_count": sized,
        "total_bytes": total_bytes or None,
        "total_size_human": human_bytes(total_bytes),
        "size_is_partial": sized < len(all_downloads),  # some files have unknown size
        "by_source": [
            {"source": k, "files": v["files"], "bytes": v["bytes"] or None,
             "size_human": human_bytes(v["bytes"])}
            for k, v in sorted(by_source.items(), key=lambda kv: -kv[1]["bytes"])
        ],
        "unresolved": notes["unresolved"],
        "unmatched_count": len(notes["unmatched"]),
        "available_types": sorted(available_types),
    }


# ── Download script generators (Phase 27, production-grade) ──

import re as _re

_PAGE_TYPES = frozenset({
    "page", "geo_page", "sra_page", "bioproject_page", "arrayexpress_page",
    "explorer", "hca_portal", "ega_metadata",
})


def _safe_name(eid: str) -> str:
    """Filesystem-safe per-dataset directory name."""
    return _re.sub(r"[^A-Za-z0-9._-]", "_", eid)[:80] or "dataset"


def _sra_run_from_url(url: str | None) -> str | None:
    """Extract an SRR/ERR/DRR run id from an EBI FASTQ FTP path."""
    if not url:
        return None
    last = url.rstrip("/").split("/")[-1]
    return last if _re.fullmatch(r"[SED]RR\d+", last or "") else None


def _group_by_entity(downloads: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for d in downloads:
        grouped.setdefault(d["entity_id"], []).append(d)
    return grouped


def _notes_comment_lines(notes: dict | None, prefix: str = "# ") -> list[str]:
    """Render the unresolved/unmatched diagnostics as comment lines so the
    user understands why a dataset isn't in the script (Phase 27 D2)."""
    if not notes:
        return []
    out: list[str] = []
    req = ", ".join(notes.get("requested_types") or [])
    for eid, types in (notes.get("unmatched") or {}).items():
        out.append(f"{prefix}note: {eid} has no [{req}] files (offers: {', '.join(types)}) — skipped")
    for eid in (notes.get("unresolved") or []):
        out.append(f"{prefix}note: {eid} was not found in the catalog — skipped")
    return out


def _stream(content: str, media_type: str, filename: str) -> StreamingResponse:
    return StreamingResponse(
        iter([content]),
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def _total_bytes(downloads: list[dict]) -> int:
    return sum(d.get("bytes") or 0 for d in downloads)


def _generate_tsv(downloads: list[dict]) -> StreamingResponse:
    output = io.StringIO()
    output.write("# Singligent download manifest\n")
    output.write(f"# Generated: {_dt.datetime.now(tz=_dt.timezone.utc).isoformat(timespec='seconds')}\n")
    tot = _total_bytes(downloads)
    output.write(f"# Files: {len(downloads)}   Total size: {human_bytes(tot) or 'unknown'}\n")
    output.write("entity_id\tfile_type\turl\tbytes\tsize_human\tmd5\tlabel\n")
    for d in downloads:
        b = d.get("bytes") or ""
        output.write(
            f"{d['entity_id']}\t{d['file_type']}\t{d['url']}\t{b}\t"
            f"{human_bytes(d.get('bytes')) or ''}\t{d.get('md5') or ''}\t{d['label']}\n"
        )
    output.seek(0)
    return _stream(output.getvalue(), "text/tab-separated-values", "singligent_downloads.tsv")


_BASH_HELPERS = r"""
_retry() { local n="$1"; shift; local i=1; until "$@"; do [ "$i" -ge "$n" ] && return 1; echo "  retry $i/$n…"; i=$((i+1)); sleep $((i*3)); done; }
_ok()   { SUCCESS=$((SUCCESS+1)); echo "  ✓ done: $1"; }
_fail() { FAILED=$((FAILED+1)); echo "$1" >> "$FAILED_FILE"; echo "  ✗ FAILED: $1"; }

download_sra() {  # run_id  outdir — prefetch + fasterq-dump + pigz
  local run="$1" dir="$2"; mkdir -p "$dir/tmp"
  if _retry "$RETRIES" prefetch "$run" -O "$dir" --max-size 100G \
     && _retry "$RETRIES" fasterq-dump "$dir/$run" -O "$dir" -e "$THREADS" -t "$dir/tmp"; then
    pigz -p "$THREADS" "$dir"/*.fastq 2>/dev/null || true; _ok "$run"
  else _fail "$run"; fi
  rm -rf "$dir/tmp"
}
download_url() {  # url  outdir  [md5] — single file, resumable, optional checksum verify
  local url="$1" dir="$2" md5="${3:-}"; mkdir -p "$dir"
  local fname; fname="$(basename "$url")"
  if ! _retry "$RETRIES" wget -c -P "$dir" "$url"; then _fail "$url"; return; fi
  if [ -n "$md5" ] && command -v md5sum >/dev/null 2>&1; then
    local got; got="$(md5sum "$dir/$fname" | cut -d' ' -f1)"
    if [ "$got" != "$md5" ]; then _fail "$url (md5 mismatch: got $got want $md5)"; return; fi
    echo "  ✓ md5 ok: $fname"
  fi
  _ok "$url"
}
mirror_dir() {   # url  outdir — recursive listing (GEO suppl / EBI FTP dir)
  local url="$1" dir="$2"; mkdir -p "$dir"
  if _retry "$RETRIES" wget -c -r -np -nH --cut-dirs=99 -R "index.html*" -P "$dir" "$url"; then _ok "$url"; else _fail "$url"; fi
}
"""


def _generate_bash(downloads: list[dict], notes: dict | None = None) -> StreamingResponse:
    by_entity = _group_by_entity(downloads)
    ftypes = {d["file_type"] for d in downloads}
    # Phase 36: with concrete ENA file URLs (…_1.fastq.gz), FASTQ downloads via
    # plain wget — SRA Toolkit is only needed for the legacy bare-run-directory
    # form. Detect each tool from the *actual* targets, not just the type set.
    need_sra = any(d["file_type"] == "fastq" and _sra_run_from_url(d.get("url"))
                   for d in downloads)
    need_aspera = "fastq_aspera" in ftypes
    need_wget = any((d.get("url") or "") and not _sra_run_from_url(d.get("url"))
                    and d["file_type"] not in _PAGE_TYPES for d in downloads)

    L: list[str] = []
    a = L.append
    a("#!/usr/bin/env bash")
    a("# Singligent — Bulk Download Script")
    a(f"# Generated: {_dt.datetime.now(tz=_dt.timezone.utc).isoformat(timespec='seconds')}")
    tot = _total_bytes(downloads)
    a(f"# Datasets: {len(by_entity)}   Download targets: {len(downloads)}   "
      f"Total size: {human_bytes(tot) or 'unknown'}")
    a("# Override defaults via env, e.g.:  THREADS=16 OUTPUT_DIR=/data ./singligent_download.sh")
    L.extend(_notes_comment_lines(notes))
    a("")
    a("set -euo pipefail")
    a("")
    a('THREADS="${THREADS:-8}"')
    a('RETRIES="${RETRIES:-3}"')
    a('OUTPUT_DIR="${OUTPUT_DIR:-./singligent_downloads_$(date +%Y%m%d_%H%M%S)}"')
    a('LOG_FILE="${OUTPUT_DIR}/download.log"')
    a('FAILED_FILE="${OUTPUT_DIR}/failed.txt"')
    a("")
    a("# ── dependency checks ──")
    a("MISSING=0")
    a('_need() { command -v "$1" >/dev/null 2>&1 || { echo "MISSING: $1 — $2" >&2; MISSING=1; }; }')
    if need_sra:
        a('_need prefetch "SRA Toolkit https://github.com/ncbi/sra-tools"')
        a('_need fasterq-dump "SRA Toolkit"')
        a('_need pigz "pigz (conda install -c conda-forge pigz)"')
    if need_aspera:
        a('_need ascp "Aspera CLI (conda install -c hcc aspera-cli)"')
    if need_wget:
        a('_need wget "wget"')
    a('[ "$MISSING" = 1 ] && { echo "Install the tools above, then re-run." >&2; exit 1; }')
    a("")
    a('mkdir -p "$OUTPUT_DIR"')
    a('exec > >(tee -a "$LOG_FILE") 2>&1')
    a('echo "=== Singligent download started $(date) → $OUTPUT_DIR (threads=$THREADS) ==="')
    a("SUCCESS=0; FAILED=0")
    a(_BASH_HELPERS)
    for eid, items in by_entity.items():
        a(f'echo "── {eid} ──"')
        a(f'DSDIR="$OUTPUT_DIR/{_safe_name(eid)}"')
        for d in items:
            ft = d["file_type"]
            url = d.get("url") or ""
            md5 = d.get("md5") or ""
            size = human_bytes(d.get("bytes"))
            a(f'# {d.get("label", ft)}' + (f'  [{size}]' if size else ""))
            if ft in _PAGE_TYPES:
                a(f'#   manual / web portal — open in a browser: {url}')
            elif ft == "fastq_aspera":
                for ln in (d.get("instructions") or "").split("\n"):
                    if ln.strip().startswith("ascp"):
                        a(ln.strip().rstrip("\\").strip())
            elif not url:
                continue
            elif url.endswith("/"):
                a(f'mirror_dir "{url}" "$DSDIR"')
            else:
                run = _sra_run_from_url(url)
                if ft == "fastq" and run:
                    # Legacy bare-run directory — fall back to SRA Toolkit.
                    a(f'download_sra "{run}" "$DSDIR"')
                elif md5:
                    a(f'download_url "{url}" "$DSDIR" "{md5}"')
                else:
                    a(f'download_url "{url}" "$DSDIR"')
                if d.get("aspera_url"):
                    a(f'#   ↑ or 10-100x faster via Aspera: '
                      f'ascp -QT -l 300m -P33001 -i <asperaweb_id_dsa.openssh> '
                      f'{d["aspera_url"]} "$DSDIR"')
        a("")
    a('echo "=== Done. Success: $SUCCESS  Failed: $FAILED ==="')
    a('[ -f "$FAILED_FILE" ] && echo "Failed targets logged to: $FAILED_FILE"')
    a("")
    return _stream("\n".join(L), "text/x-shellscript", "singligent_download.sh")


def _generate_aria2(downloads: list[dict], notes: dict | None = None) -> StreamingResponse:
    lines = [
        "# Singligent — aria2c input file",
        f"# Generated: {_dt.datetime.now(tz=_dt.timezone.utc).isoformat(timespec='seconds')}",
        "# Usage: aria2c -i singligent_downloads.aria2 -j4   (4 parallel downloads)",
    ]
    tot = _total_bytes(downloads)
    lines.append(f"# Files: {len(downloads)}   Total size: {human_bytes(tot) or 'unknown'}")
    lines.extend(_notes_comment_lines(notes))
    lines.append("")
    for d in downloads:
        url = d.get("url") or ""
        if not url or d["file_type"] in _PAGE_TYPES or url.endswith("/"):
            # aria2 can't mirror a directory listing or a web page.
            if d["file_type"] in _PAGE_TYPES:
                lines.append(f"# manual: {url}")
            elif url.endswith("/"):
                lines.append(f"# directory (use wget -r): {url}")
            continue
        filename = url.rstrip("/").split("/")[-1] or f"{d['entity_id']}.{d['file_type']}"
        size = human_bytes(d.get("bytes"))
        if size:
            lines.append(f"# {filename} ({size})")
        lines.append(url)
        lines.append(f"  dir={_safe_name(d['entity_id'])}")
        lines.append(f"  out={filename}")
        lines.append("  continue=true")
        lines.append("  max-connection-per-server=16")
        lines.append("  split=16")
        lines.append("  min-split-size=1M")
        if d.get("md5"):
            # aria2 verifies natively and re-downloads on mismatch.
            lines.append(f"  checksum=md5={d['md5']}")
        lines.append("")
    return _stream("\n".join(lines), "text/plain", "singligent_downloads.aria2")


def _generate_snakemake(downloads: list[dict], notes: dict | None = None) -> StreamingResponse:
    """A self-contained Snakemake workflow with the manifest inlined."""
    import json as _json
    by_entity = _group_by_entity(downloads)
    # Build a flat list of (dataset, kind, url, run) targets.
    targets: list[dict] = []
    for eid, items in by_entity.items():
        for d in items:
            ft, url = d["file_type"], (d.get("url") or "")
            if ft in _PAGE_TYPES or not url:
                continue
            run = _sra_run_from_url(url)
            kind = "sra" if ft == "fastq" and run else ("dir" if url.endswith("/") else "file")
            targets.append({"dataset": _safe_name(eid), "kind": kind, "url": url,
                            "run": run or "", "md5": d.get("md5") or ""})
    manifest_json = _json.dumps(targets, indent=2)
    header = _notes_comment_lines(notes)
    content = '''# Singligent — Snakemake download workflow
# Generated: {ts}
# Run:  snakemake --cores 8   (add --dry-run to preview)
{notes}
import os

THREADS = int(os.environ.get("THREADS", "8"))
TARGETS = {manifest}

def _flag(t, i):
    return f"data/{{t['dataset']}}/.done_{{i}}"

rule all:
    input: [ _flag(t, i) for i, t in enumerate(TARGETS) ]

for _i, _t in enumerate(TARGETS):
    rule:
        name: f"fetch_{{_t['dataset']}}_{{_i}}"
        output: touch(_flag(_t, _i))
        params: t=_t
        threads: THREADS
        run:
            t = params.t; d = f"data/{{t['dataset']}}"
            os.makedirs(d, exist_ok=True)
            if t["kind"] == "sra":
                shell(f"prefetch {{t['run']}} -O {{d}} --max-size 100G")
                shell(f"fasterq-dump {{d}}/{{t['run']}} -O {{d}} -e {{threads}} && pigz -p {{threads}} {{d}}/*.fastq || true")
            elif t["kind"] == "dir":
                shell(f"wget -c -r -np -nH --cut-dirs=99 -R 'index.html*' -P {{d}} '{{t['url']}}'")
            else:
                shell(f"wget -c -P {{d}} '{{t['url']}}'")
                if t.get("md5"):
                    fn = os.path.join(d, os.path.basename(t["url"]))
                    shell(f"echo '{{t['md5']}}  {{fn}}' | md5sum -c -")
'''.format(
        ts=_dt.datetime.now(tz=_dt.timezone.utc).isoformat(timespec="seconds"),
        notes=("\n".join(header) + "\n") if header else "",
        manifest=manifest_json,
    )
    return _stream(content, "text/x-python", "Snakefile")


def _generate_python(downloads: list[dict], notes: dict | None = None) -> StreamingResponse:
    """A dependency-light Python downloader (stdlib + optional tqdm)."""
    import json as _json
    by_entity = _group_by_entity(downloads)
    manifest: list[dict] = []
    for eid, items in by_entity.items():
        for d in items:
            ft, url = d["file_type"], (d.get("url") or "")
            if ft in _PAGE_TYPES or not url:
                continue
            manifest.append({
                "dataset": _safe_name(eid), "file_type": ft, "url": url,
                "is_dir": url.endswith("/"), "sra_run": _sra_run_from_url(url) or "",
                "md5": d.get("md5") or "", "bytes": d.get("bytes") or 0,
            })
    header = _notes_comment_lines(notes, prefix="# ")
    content = '''#!/usr/bin/env python3
"""Singligent download manifest.
Generated: {ts}
Usage:  python singligent_download.py [--out DIR] [--retries N]
Plain files download via urllib (stdlib). SRA runs and directory listings
print the recommended external command (prefetch / wget -r).
"""
{notes}
import argparse, hashlib, os, sys, urllib.request

MANIFEST = {manifest}

def _md5(path):
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def fetch_file(url, dest, retries, md5="", want_bytes=0):
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        if (not want_bytes or os.path.getsize(dest) == want_bytes) and \\
           (not md5 or _md5(dest) == md5):
            print(f"  skip (exists, verified): {{dest}}"); return True
    for attempt in range(1, retries + 1):
        try:
            print(f"  GET {{url}} -> {{dest}} (try {{attempt}}/{{retries}})")
            urllib.request.urlretrieve(url, dest)
            if md5:
                got = _md5(dest)
                if got != md5:
                    print(f"  ! md5 mismatch (got {{got}} want {{md5}})"); continue
                print(f"  ✓ md5 ok")
            return True
        except Exception as e:
            print(f"  ! {{e}}")
    return False

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="singligent_downloads")
    ap.add_argument("--retries", type=int, default=3)
    args = ap.parse_args()
    ok = fail = 0
    for m in MANIFEST:
        d = os.path.join(args.out, m["dataset"]); os.makedirs(d, exist_ok=True)
        if m["sra_run"]:
            print(f"[SRA] {{m['sra_run']}} — run: prefetch {{m['sra_run']}} -O {{d}} && fasterq-dump {{d}}/{{m['sra_run']}} -O {{d}}")
            continue
        if m["is_dir"]:
            print(f"[DIR] {{m['url']}} — run: wget -c -r -np -nH --cut-dirs=99 -R 'index.html*' -P {{d}} '{{m['url']}}'")
            continue
        name = m["url"].rstrip("/").split("/")[-1] or "download"
        if fetch_file(m["url"], os.path.join(d, name), args.retries,
                      m.get("md5", ""), m.get("bytes", 0)): ok += 1
        else: fail += 1
    print(f"=== Done. Success: {{ok}}  Failed: {{fail}} ===")
    sys.exit(1 if fail else 0)

if __name__ == "__main__":
    main()
'''.format(
        ts=_dt.datetime.now(tz=_dt.timezone.utc).isoformat(timespec="seconds"),
        notes=("\n".join(header)) if header else "",
        # Inline as a PYTHON literal (repr), not JSON — json.dumps emits
        # true/false/null which are NameErrors in Python source and crashed the
        # generated script at import. repr() yields valid Python (True/False/None).
        manifest=repr(manifest),
    )
    return _stream(content, "text/x-python", "singligent_download.py")


# ── Metadata download ──

class MetadataDownloadRequest(BaseModel):
    sample_pks: list[int] = []
    format: str = "csv"  # csv | json
    limit: int = 1000


METADATA_FIELDS = [
    "s.sample_id", "s.tissue", "s.disease", "s.cell_type", "s.organism",
    "s.sex", "s.n_cells", "s.source_database",
    "sr.series_id", "sr.assay",
    "p.project_id", "p.title as project_title", "p.pmid", "p.doi",
]


def _build_provenance(dal) -> dict:
    """Phase 31.D — provenance block for export headers. Same shape
    as /scdbAPI/version but minimised for embedding in CSV/JSON."""
    prov: dict = {
        "service": "SGDB Agent",
        "app_version": "2.0.0",
        "exported_at_utc": _dt.datetime.now(tz=_dt.timezone.utc).isoformat(timespec="seconds"),
    }
    try:
        r = dal.execute("SELECT MAX(last_updated) AS d FROM stats_overall")
        if r.rows and r.rows[0]["d"]:
            prov["db_build_date"] = r.rows[0]["d"]
    except Exception:
        pass
    try:
        r = dal.execute("SELECT value FROM stats_overall WHERE metric='total_samples'")
        if r.rows:
            prov["db_sample_count"] = r.rows[0]["value"]
    except Exception:
        pass
    return prov


@router.post("/downloads/metadata")
async def download_metadata(req: MetadataDownloadRequest):
    """Download unified metadata as CSV or JSON for selected samples."""
    dal = get_dal()
    if dal is None:
        raise HTTPException(status_code=503, detail="Database not available")

    select_cols = ", ".join(METADATA_FIELDS)
    base_sql = (
        f"SELECT {select_cols} FROM unified_samples s "
        "LEFT JOIN unified_series sr ON s.series_pk = sr.pk "
        "LEFT JOIN unified_projects p ON s.project_pk = p.pk"
    )

    if req.sample_pks:
        placeholders = ",".join("?" for _ in req.sample_pks)
        sql = f"{base_sql} WHERE s.pk IN ({placeholders}) LIMIT ?"
        params = list(req.sample_pks) + [req.limit]
    else:
        sql = f"{base_sql} LIMIT ?"
        params = [req.limit]

    result = dal.execute(sql, params)
    provenance = _build_provenance(dal)
    # Record filter scope so the export is self-describing.
    provenance["row_count"] = len(result.rows)
    provenance["row_limit"] = req.limit
    provenance["filtered_by"] = (
        "sample_pks" if req.sample_pks else "limit-only"
    )
    if req.sample_pks:
        provenance["sample_pk_count"] = len(req.sample_pks)

    if req.format == "json":
        import json
        # Phase 31.D — embed provenance as a sibling field so the file
        # is self-describing for citation.
        payload = {
            "provenance": provenance,
            "schema": [
                "sample_id", "tissue", "disease", "cell_type", "organism",
                "sex", "n_cells", "source_database",
                "series_id", "assay",
                "project_id", "project_title", "pmid", "doi",
            ],
            "rows": [dict(r) for r in result.rows],
        }
        content = json.dumps(payload, ensure_ascii=False, indent=2)
        return StreamingResponse(
            iter([content]),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=singligent_metadata.json"},
        )
    else:
        output = io.StringIO()
        # Phase 31.D — CSV header comments (RFC-4180 doesn't bless them
        # but every common CSV reader [pandas, R read.csv, Excel] either
        # skips `#` lines or lets the user opt in via `skip=`).
        output.write("# SGDB Agent metadata export\n")
        for k in ("exported_at_utc", "db_build_date", "db_sample_count",
                  "row_count", "row_limit", "filtered_by", "sample_pk_count"):
            if k in provenance:
                output.write(f"# {k}: {provenance[k]}\n")
        output.write(
            "# To skip these headers: pandas.read_csv(..., comment='#')  |  R: read.csv(..., comment.char='#')\n"
        )
        headers = [
            "sample_id", "tissue", "disease", "cell_type", "organism",
            "sex", "n_cells", "source_database",
            "series_id", "assay",
            "project_id", "project_title", "pmid", "doi",
        ]
        output.write(",".join(headers) + "\n")
        for r in result.rows:
            vals = []
            for h in headers:
                v = r.get(h, "") or ""
                v = str(v).replace('"', '""')
                vals.append(f'"{v}"' if "," in str(v) or '"' in str(v) else str(v))
            output.write(",".join(vals) + "\n")
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=singligent_metadata.csv"},
        )
