"""Dependências de autenticação para FastAPI."""
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth_session import AuthSession
from app.models.base import get_db
from app.services.auth_service import AuthService

COOKIE_NAME = "nz_session"


async def get_auth_session(
    request: Request, db: AsyncSession = Depends(get_db)
) -> AuthSession | None:
    """Lê cookie e retorna AuthSession (ou None se não autenticado)."""
    session_id = request.cookies.get(COOKIE_NAME)
    if not session_id:
        return None
    svc = AuthService(db)
    return await svc.get_session(session_id)


async def require_auth(
    auth_session: AuthSession | None = Depends(get_auth_session),
) -> AuthSession:
    """Exige autenticação — raise 401 se não autenticado."""
    if not auth_session:
        from app.core.exceptions import AuthenticationError
        raise AuthenticationError(401, "Não autenticado")
    return auth_session
