"""
Download routes — download options and bulk manifest generation.
"""

from __future__ import annotations

import io
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.deps import get_dal
from api.services.download_resolver import DownloadResolver

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/scdbAPI", tags=["downloads"])

_resolver = DownloadResolver()


class ManifestRequest(BaseModel):
    entity_ids: list[str] = []
    file_types: list[str] = ["fastq"]
    format: str = "tsv"  # tsv | bash | aria2


@router.get("/downloads/{id_value}")
async def get_downloads(id_value: str):
    """Get download options for an entity."""
    dal = get_dal()
    if dal is None:
        raise HTTPException(status_code=503, detail="Database not available")

    entity = dal.get_entity_by_id(id_value)
    if entity is None:
        raise HTTPException(status_code=404, detail=f"Entity {id_value} not found")

    entity_data = {k: v for k, v in entity.items() if not k.startswith("_")}

    # Load project + series context
    project_pk = entity_data.get("pk") if entity.get("_type") == "project" else entity_data.get("project_pk")
    project_data = None
    series_list = []

    if project_pk:
        result = dal.execute("SELECT * FROM unified_projects WHERE pk = ?", [project_pk])
        if result.rows:
            project_data = result.rows[0]
        result = dal.execute("SELECT * FROM unified_series WHERE project_pk = ? LIMIT 50", [project_pk])
        series_list = [dict(r) for r in result.rows]

    options = _resolver.resolve(entity_data, series_list, project_data)

    return {
        "entity_id": id_value,
        "source_database": entity_data.get("source_database", ""),
        "downloads": [
            {"file_type": o.file_type, "label": o.label, "url": o.url,
             "instructions": o.instructions, "source": o.source}
            for o in options
        ],
    }


@router.post("/downloads/manifest")
async def generate_manifest(req: ManifestRequest):
    """Generate a bulk download manifest file (TSV, bash script, or aria2)."""
    dal = get_dal()
    if dal is None:
        raise HTTPException(status_code=503, detail="Database not available")

    if not req.entity_ids:
        raise HTTPException(status_code=400, detail="No entity IDs provided")

    all_downloads: list[dict] = []

    for eid in req.entity_ids[:100]:  # Cap at 100
        entity = dal.get_entity_by_id(eid)
        if not entity:
            continue

        entity_data = {k: v for k, v in entity.items() if not k.startswith("_")}
        project_pk = entity_data.get("pk") if entity.get("_type") == "project" else entity_data.get("project_pk")
        project_data = None
        series_list = []

        if project_pk:
            result = dal.execute("SELECT * FROM unified_projects WHERE pk = ?", [project_pk])
            if result.rows:
                project_data = result.rows[0]
            result = dal.execute("SELECT * FROM unified_series WHERE project_pk = ? LIMIT 50", [project_pk])
            series_list = [dict(r) for r in result.rows]

        options = _resolver.resolve(entity_data, series_list, project_data)
        for o in options:
            if o.url and o.file_type in req.file_types:
                all_downloads.append({
                    "entity_id": eid,
                    "file_type": o.file_type,
                    "url": o.url,
                    "label": o.label,
                    "instructions": o.instructions,
                })

    if not all_downloads:
        raise HTTPException(status_code=404, detail="No downloadable files found for the given IDs and file types")

    if req.format == "bash":
        return _generate_bash(all_downloads)
    elif req.format == "aria2":
        return _generate_aria2(all_downloads)
    else:
        return _generate_tsv(all_downloads)


def _generate_tsv(downloads: list[dict]) -> StreamingResponse:
    output = io.StringIO()
    output.write("entity_id\tfile_type\turl\tlabel\n")
    for d in downloads:
        output.write(f"{d['entity_id']}\t{d['file_type']}\t{d['url']}\t{d['label']}\n")
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/tab-separated-values",
        headers={"Content-Disposition": "attachment; filename=sceqtl_downloads.tsv"},
    )


def _generate_bash(downloads: list[dict]) -> StreamingResponse:
    lines = [
        "#!/bin/bash",
        "# SCeQTL-Agent Bulk Download Script",
        f"# Total files: {len(downloads)}",
        "",
        "set -e",
        'mkdir -p sceqtl_downloads && cd sceqtl_downloads',
        "",
    ]

    for d in downloads:
        lines.append(f"# {d['label']}")
        if d["file_type"] == "fastq" and d.get("instructions"):
            # Use SRA toolkit command from instructions
            for line in d["instructions"].split("\n"):
                if line.strip().startswith("prefetch") or line.strip().startswith("fastq-dump"):
                    lines.append(line.strip())
        elif d["url"]:
            lines.append(f'wget -c "{d["url"]}"')
        lines.append("")

    content = "\n".join(lines)
    return StreamingResponse(
        iter([content]),
        media_type="text/x-shellscript",
        headers={"Content-Disposition": "attachment; filename=sceqtl_download.sh"},
    )


def _generate_aria2(downloads: list[dict]) -> StreamingResponse:
    lines = []
    for d in downloads:
        if d["url"]:
            lines.append(d["url"])
            filename = d["url"].rstrip("/").split("/")[-1] or f"{d['entity_id']}.{d['file_type']}"
            lines.append(f"  out={filename}")
    content = "\n".join(lines)
    return StreamingResponse(
        iter([content]),
        media_type="text/plain",
        headers={"Content-Disposition": "attachment; filename=sceqtl_downloads.aria2"},
    )


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

    if req.format == "json":
        import json
        rows = [dict(r) for r in result.rows]
        content = json.dumps(rows, ensure_ascii=False, indent=2)
        return StreamingResponse(
            iter([content]),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=sceqtl_metadata.json"},
        )
    else:
        output = io.StringIO()
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
            headers={"Content-Disposition": "attachment; filename=sceqtl_metadata.csv"},
        )
