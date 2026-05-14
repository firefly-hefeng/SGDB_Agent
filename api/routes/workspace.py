"""
Workspace routes — Phase 15D.

Anonymous, IP+UUID-scoped collections so users can build a "cart" of
samples / series / projects without logging in. Stored in an
independent SQLite DB at data/workspace.db.

Endpoints:
    POST   /scdbAPI/workspace/create
    GET    /scdbAPI/workspace/list
    GET    /scdbAPI/workspace/{id}
    PATCH  /scdbAPI/workspace/{id}
    POST   /scdbAPI/workspace/{id}/items
    DELETE /scdbAPI/workspace/{id}/items/{item_pk}
    DELETE /scdbAPI/workspace/{id}
    POST   /scdbAPI/workspace/{id}/recover
    GET    /scdbAPI/workspace/{id}/export?format=csv|json

Identity: header `X-Client-UUID` + request IP. Browser persists the
UUID in localStorage; reset reset = different identity. The two
fields are concatenated into a single user_token.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from src.workspace.store import WorkspaceStore

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/scdbAPI/workspace", tags=["workspace"])

# Module-level singleton — created lazily so unit tests can swap it.
_store: WorkspaceStore | None = None


def get_store() -> WorkspaceStore:
    global _store
    if _store is None:
        project_root = Path(__file__).resolve().parents[2]
        db_path = project_root / "data" / "workspace.db"
        _store = WorkspaceStore(str(db_path))
    return _store


def set_store(store: WorkspaceStore | None):
    """Test hook to replace the store with a temp DB."""
    global _store
    _store = store


def _user_token(request: Request, x_client_uuid: str | None) -> str:
    if not x_client_uuid:
        raise HTTPException(status_code=400, detail="X-Client-UUID header required")
    ip = request.client.host if request.client else "unknown"
    # Deliberately put IP first so per-IP listings group naturally;
    # the UUID makes it unique even on shared NATs.
    return f"{ip}:{x_client_uuid}"


# ── Request / response models ──

class CreateWorkspaceRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


class UpdateWorkspaceRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class WorkspaceItemIn(BaseModel):
    item_type: str = Field(default="sample", pattern=r"^(sample|series|project)$")
    item_id: str
    item_pk: int | None = None
    source_database: str | None = None
    title: str | None = None
    note: str | None = Field(default=None, max_length=2000)
    metadata: dict | None = None


class AddItemsRequest(BaseModel):
    items: list[WorkspaceItemIn] = Field(..., min_length=1, max_length=500)


# ── Endpoints ──

@router.post("/create")
async def create_workspace(
    body: CreateWorkspaceRequest,
    request: Request,
    x_client_uuid: str | None = Header(default=None, alias="X-Client-UUID"),
):
    user_token = _user_token(request, x_client_uuid)
    ws = get_store().create(user_token, body.name, body.description)
    return ws


@router.get("/list")
async def list_workspaces(
    request: Request,
    include_deleted: bool = False,
    x_client_uuid: str | None = Header(default=None, alias="X-Client-UUID"),
):
    user_token = _user_token(request, x_client_uuid)
    return {"workspaces": get_store().list_for_user(user_token, include_deleted=include_deleted)}


@router.get("/{workspace_id}")
async def get_workspace(
    workspace_id: int,
    request: Request,
    x_client_uuid: str | None = Header(default=None, alias="X-Client-UUID"),
):
    user_token = _user_token(request, x_client_uuid)
    store = get_store()
    ws = store.get(workspace_id, user_token)
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    items = store.list_items(workspace_id, user_token)
    return {"workspace": ws, "items": items}


@router.patch("/{workspace_id}")
async def update_workspace(
    workspace_id: int,
    body: UpdateWorkspaceRequest,
    request: Request,
    x_client_uuid: str | None = Header(default=None, alias="X-Client-UUID"),
):
    user_token = _user_token(request, x_client_uuid)
    ws = get_store().update(workspace_id, user_token, name=body.name, description=body.description)
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws


@router.post("/{workspace_id}/items")
async def add_items(
    workspace_id: int,
    body: AddItemsRequest,
    request: Request,
    x_client_uuid: str | None = Header(default=None, alias="X-Client-UUID"),
):
    user_token = _user_token(request, x_client_uuid)
    items = [it.model_dump() for it in body.items]
    result = get_store().add_items(workspace_id, user_token, items)
    if result.get("error") == "not_found":
        raise HTTPException(status_code=404, detail="Workspace not found")
    return result


@router.delete("/{workspace_id}/items/{item_pk}")
async def remove_item(
    workspace_id: int,
    item_pk: int,
    request: Request,
    x_client_uuid: str | None = Header(default=None, alias="X-Client-UUID"),
):
    user_token = _user_token(request, x_client_uuid)
    ok = get_store().remove_item(workspace_id, user_token, item_pk)
    if not ok:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"removed": True}


@router.delete("/{workspace_id}")
async def delete_workspace(
    workspace_id: int,
    request: Request,
    x_client_uuid: str | None = Header(default=None, alias="X-Client-UUID"),
):
    user_token = _user_token(request, x_client_uuid)
    ok = get_store().soft_delete(workspace_id, user_token)
    if not ok:
        raise HTTPException(status_code=404, detail="Workspace not found or already deleted")
    return {"deleted": True}


@router.post("/{workspace_id}/recover")
async def recover_workspace(
    workspace_id: int,
    request: Request,
    x_client_uuid: str | None = Header(default=None, alias="X-Client-UUID"),
):
    user_token = _user_token(request, x_client_uuid)
    ok = get_store().recover(workspace_id, user_token)
    if not ok:
        raise HTTPException(status_code=404, detail="Workspace not found or not deleted")
    return {"recovered": True}


@router.get("/{workspace_id}/export")
async def export_workspace(
    workspace_id: int,
    request: Request,
    format: str = "json",
    x_client_uuid: str | None = Header(default=None, alias="X-Client-UUID"),
):
    user_token = _user_token(request, x_client_uuid)
    store = get_store()
    ws = store.get(workspace_id, user_token)
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    items = store.list_items(workspace_id, user_token)

    if format == "json":
        body = json.dumps({"workspace": ws, "items": items}, ensure_ascii=False, indent=2)
        return Response(
            content=body, media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="workspace_{workspace_id}.json"'},
        )

    if format == "csv":
        buf = io.StringIO()
        cols = ["item_type", "item_id", "source_database", "title", "note", "added_at"]
        writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        for it in items:
            writer.writerow({k: it.get(k, "") for k in cols})
        return Response(
            content=buf.getvalue(), media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="workspace_{workspace_id}.csv"'},
        )

    raise HTTPException(status_code=400, detail=f"Unsupported format: {format}")
