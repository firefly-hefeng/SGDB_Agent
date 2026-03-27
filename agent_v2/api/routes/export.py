"""
Data export route
"""

from __future__ import annotations

import csv
import io
import json
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from api.schemas import ExportRequest
from api.deps import get_coordinator

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/scdbAPI", tags=["export"])


@router.post("/export")
async def export_data(req: ExportRequest):
    """
    Export query results in CSV, JSON, or BibTeX format.
    """
    coordinator = get_coordinator()
    if coordinator is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    # Execute the query
    try:
        resp = await coordinator.query(
            user_input=req.query,
            session_id=req.session_id,
        )
    except Exception as e:
        logger.error("Export query failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Query failed: {e}")

    if not resp.results:
        raise HTTPException(status_code=404, detail="No results to export")

    records = resp.results[:req.limit]

    if req.format == "csv":
        return _export_csv(records, req.fields)
    elif req.format == "json":
        return _export_json(records, req.fields, resp.summary)
    elif req.format == "bibtex":
        return _export_bibtex(records)
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {req.format}")


def _export_csv(records, fields: list[str] | None) -> StreamingResponse:
    """Export as CSV."""
    output = io.StringIO()
    writer = None

    for r in records:
        data = _filter_fields(r.data, fields)
        data["sources"] = "; ".join(r.sources)
        data["quality_score"] = r.quality_score

        if writer is None:
            writer = csv.DictWriter(output, fieldnames=list(data.keys()))
            writer.writeheader()
        writer.writerow(data)

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=sceqtl_export.csv"},
    )


def _export_json(records, fields: list[str] | None, summary: str) -> StreamingResponse:
    """Export as JSON."""
    data = {
        "summary": summary,
        "total_count": len(records),
        "results": [
            {
                "data": _filter_fields(r.data, fields),
                "sources": r.sources,
                "quality_score": r.quality_score,
            }
            for r in records
        ],
    }
    content = json.dumps(data, ensure_ascii=False, indent=2)
    return StreamingResponse(
        iter([content]),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=sceqtl_export.json"},
    )


def _export_bibtex(records) -> StreamingResponse:
    """Export as BibTeX (for records with PMID/DOI)."""
    entries = []
    for i, r in enumerate(records):
        pmid = r.data.get("pmid") or r.data.get("project_pmid")
        doi = r.data.get("doi") or r.data.get("project_doi")
        title = r.data.get("title") or r.data.get("project_title") or ""
        pid = r.data.get("project_id") or r.data.get("sample_id") or f"entry_{i}"

        if not pmid and not doi:
            continue

        entry = f"@article{{{pid},\n"
        entry += f"  title = {{{title}}},\n"
        if pmid:
            entry += f"  pmid = {{{pmid}}},\n"
        if doi:
            entry += f"  doi = {{{doi}}},\n"
        sources = "; ".join(r.sources)
        entry += f"  note = {{Source databases: {sources}}},\n"
        entry += "}\n"
        entries.append(entry)

    if not entries:
        entries = ["% No records with PMID or DOI found\n"]

    content = "\n".join(entries)
    return StreamingResponse(
        iter([content]),
        media_type="application/x-bibtex",
        headers={"Content-Disposition": "attachment; filename=sceqtl_export.bib"},
    )


def _filter_fields(data: dict, fields: list[str] | None) -> dict:
    """Filter data dict to only include specified fields."""
    if not fields:
        # Exclude internal/large fields
        exclude = {"raw_metadata", "description", "etl_source_file", "raw_xml"}
        return {k: v for k, v in data.items() if k not in exclude}
    return {k: v for k, v in data.items() if k in fields}
