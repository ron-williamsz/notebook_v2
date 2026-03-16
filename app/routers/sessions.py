"""CRUD de Sessions (notebooks do usuário)."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import log_audit, require_auth
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
    request: Request,
    svc: SessionService = Depends(_svc),
    auth: AuthSession = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    session = await svc.create(data, auth)
    await log_audit(
        db, auth, "create_notebook", request,
        resource_type="session", resource_id=str(session.id),
        details={"title": session.title},
    )
    return session


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(session_id: int, svc: SessionService = Depends(_svc)):
    return await svc.get_by_id(session_id)


@router.patch("/{session_id}/gosati-selection", response_model=SessionResponse)
async def update_gosati_selection(
    session_id: int, data: GoSatiSelection, svc: SessionService = Depends(_svc)
):
    return await svc.update_gosati_selection(session_id, data)


@router.get("/{session_id}/coverage")
async def get_coverage(session_id: int, svc: SessionService = Depends(_svc)):
    return await svc.get_coverage(session_id)


@router.delete("/{session_id}", status_code=204)
async def delete_session(
    session_id: int,
    request: Request,
    svc: SessionService = Depends(_svc),
    auth: AuthSession = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    await log_audit(
        db, auth, "delete_notebook", request,
        resource_type="session", resource_id=str(session_id),
    )
    await svc.delete(session_id)
