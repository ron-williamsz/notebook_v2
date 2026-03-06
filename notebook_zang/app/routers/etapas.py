"""Etapas — CRUD e execução de Etapas dentro de uma sessão."""
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models.base import get_db
from app.schemas.etapa import EtapaCreate
from app.services.etapa_service import EtapaService

router = APIRouter(prefix="/sessions/{session_id}/etapas", tags=["Etapas"])


@router.get("")
async def list_etapas(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    svc = EtapaService(db, settings)
    return await svc.list_by_session(session_id)


@router.post("", status_code=201)
async def create_etapa(
    session_id: int,
    data: EtapaCreate,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    svc = EtapaService(db, settings)
    return await svc.create(session_id, data.skill_id)


@router.post("/{etapa_id}/execute")
async def execute_etapa(
    session_id: int,
    etapa_id: int,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    svc = EtapaService(db, settings)
    # Condomínio é fixo por notebook (definido na criação), usa session.gosati_condominio_codigo
    return StreamingResponse(
        svc.execute(session_id, etapa_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.delete("/{etapa_id}", status_code=204)
async def delete_etapa(
    session_id: int,
    etapa_id: int,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    svc = EtapaService(db, settings)
    await svc.delete(session_id, etapa_id)
