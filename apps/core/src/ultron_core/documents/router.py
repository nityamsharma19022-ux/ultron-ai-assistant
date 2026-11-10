"""Document endpoints (/api/v1/documents)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from ultron_core import activity
from ultron_core.db.models import Document
from ultron_core.deps import PrincipalDep, SessionDep, SettingsDep
from ultron_core.documents import service
from ultron_core.documents.extract import ExtractionError

router = APIRouter(prefix="/documents", tags=["documents"])
PRIVATE_NOT_ALLOWED = "Private documents need a local ULTRON backend with a local database."


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    kind: str
    size: int
    pages: int | None
    chars: int
    chunk_count: int
    is_private: bool
    source: str
    created_at: datetime


class UploadOut(DocumentOut):
    reused: bool = False


class SearchHit(BaseModel):
    document_id: uuid.UUID
    document_name: str
    part: int
    text: str


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, detail="Document not found")


@router.post("", response_model=UploadOut, status_code=status.HTTP_201_CREATED)
async def upload(
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    file: Annotated[UploadFile, File()],
    is_private: Annotated[bool, Form()] = False,
) -> UploadOut:
    if is_private and not settings.private_conversations_allowed:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=PRIVATE_NOT_ALLOWED)
    limit = settings.document_max_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Files can be up to {settings.document_max_mb} MB",
        )
    if not data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="The file is empty")
    name = (file.filename or "document").replace("\\", "/").rsplit("/", 1)[-1][:255] or "document"
    try:
        doc, reused = await service.ingest(
            session, principal.user.id, name, data, private=is_private
        )
    except ExtractionError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.message) from None
    out = UploadOut.model_validate(doc)
    out.reused = reused
    return out


@router.get("", response_model=list[DocumentOut])
async def list_documents(
    principal: PrincipalDep,
    session: SessionDep,
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[DocumentOut]:
    query = select(Document).where(Document.user_id == principal.user.id)
    if q:
        query = query.where(Document.name.ilike(f"%{q.strip()}%"))
    rows = await session.scalars(query.order_by(Document.created_at.desc()).limit(limit))
    return [DocumentOut.model_validate(d) for d in rows]


@router.get("/search", response_model=list[SearchHit])
async def search_documents(
    principal: PrincipalDep,
    session: SessionDep,
    q: str = Query(min_length=1, max_length=300),
    document_id: uuid.UUID | None = None,
    limit: int = Query(default=8, ge=1, le=50),
) -> list[SearchHit]:
    hits = await service.search(
        session,
        principal.user.id,
        q,
        document_ids=[document_id] if document_id else None,
        include_private=True,
        limit=limit,
    )
    return [
        SearchHit(document_id=d.id, document_name=d.name, part=c.idx + 1, text=c.text)
        for d, c in hits
    ]


@router.get("/{document_id}")
async def get_document(
    document_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> dict[str, Any]:
    try:
        doc = await service.get(session, principal.user.id, document_id)
    except service.DocumentNotFoundError:
        raise _not_found() from None
    text = await service.full_text(session, doc, max_chars=5000)
    return {**DocumentOut.model_validate(doc).model_dump(mode="json"), "preview": text}


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> Response:
    try:
        doc = await service.get(session, principal.user.id, document_id)
    except service.DocumentNotFoundError:
        raise _not_found() from None
    await session.delete(doc)
    activity.record(session, principal.user.id, "document.deleted", "Deleted a document")
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
