"""Upload e listagem de fontes (sources)."""
import re
from pathlib import Path

from fastapi import APIRouter, Depends, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import BASE_DIR
from app.core.exceptions import NotFoundError
from app.models.base import get_db
from app.models.source import Source
from app.schemas.source import SourceResponse
from app.services.source_service import SourceService

router = APIRouter(prefix="/sessions/{session_id}/sources", tags=["Sources"])


def _svc(db: AsyncSession = Depends(get_db)) -> SourceService:
    return SourceService(db)


@router.get("", response_model=list[SourceResponse])
async def list_sources(session_id: int, svc: SourceService = Depends(_svc)):
    return await svc.list_by_session(session_id)


@router.post("/upload", response_model=SourceResponse, status_code=201)
async def upload_source(
    session_id: int,
    file: UploadFile = File(...),
    svc: SourceService = Depends(_svc),
):
    return await svc.upload(session_id, file)


@router.delete("/{source_id}", status_code=204)
async def delete_source(
    session_id: int, source_id: int, svc: SourceService = Depends(_svc)
):
    await svc.delete(session_id, source_id)


def _resolve_file_path(stored_path: str) -> Path:
    """Resolve file_path stored in DB, handling environment changes (e.g. Mac → Docker).

    Paths stored as absolute may not match the current BASE_DIR.
    Extracts the relative 'data/...' portion and resolves against current BASE_DIR.
    """
    fp = Path(stored_path)
    if fp.exists():
        return fp

    # Extract relative portion after 'data/' (works for paths from any environment)
    match = re.search(r"[/\\](data[/\\].+)$", stored_path)
    if match:
        relative = match.group(1).replace("\\", "/")
        resolved = BASE_DIR / relative
        if resolved.exists():
            return resolved

    return fp  # Return original (will trigger 404)


@router.get("/{source_id}/file")
async def serve_source_file(
    session_id: int, source_id: int, inline: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """Serve o arquivo original de uma Source."""
    source = await db.get(Source, source_id)
    if not source or source.session_id != session_id:
        raise NotFoundError(404, f"Source {source_id} não encontrada")

    file_path = _resolve_file_path(source.file_path)
    if not file_path.exists():
        raise NotFoundError(404, "Arquivo não encontrado no disco")

    return FileResponse(
        path=str(file_path),
        media_type=source.mime_type,
        filename=source.filename,
        content_disposition_type="inline" if inline else "attachment",
    )
