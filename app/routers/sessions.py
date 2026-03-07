"""CRUD de Sessions (notebooks do usuário)."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_auth
from app.models.auth_session import AuthSession
from app.models.base import get_db
from app.schemas.session import GoSatiSelection, SessionCreate, SessionResponse
from app.services.session_service import SessionService

router = APIRouter(prefix="/sessions", tags=["Sessions"])


def _svc(db: AsyncSession = Depends(get_db)) -> SessionService:
    return SessionService(db)


@router.get("", response_model=list[SessionResponse])
async def list_sessions(svc: SessionService = Depends(_svc)):
    return await svc.list_all()


@router.post("", response_model=SessionResponse, status_code=201)
async def create_session(
    data: SessionCreate,
    svc: SessionService = Depends(_svc),
    auth: AuthSession = Depends(require_auth),
):
    return await svc.create(data, auth)


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(session_id: int, svc: SessionService = Depends(_svc)):
    return await svc.get_by_id(session_id)


@router.patch("/{session_id}/gosati-selection", response_model=SessionResponse)
async def update_gosati_selection(
    session_id: int, data: GoSatiSelection, svc: SessionService = Depends(_svc)
):
    return await svc.update_gosati_selection(session_id, data)


@router.delete("/{session_id}", status_code=204)
async def delete_session(session_id: int, svc: SessionService = Depends(_svc)):
    await svc.delete(session_id)
