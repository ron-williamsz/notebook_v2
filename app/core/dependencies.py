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


async def require_admin(
    auth_session: AuthSession = Depends(require_auth),
) -> AuthSession:
    """Exige role admin — raise 403 se não for admin."""
    if getattr(auth_session, "role", "user") != "admin":
        from app.core.exceptions import AppError
        raise AppError(403, "Acesso restrito a administradores")
    return auth_session


async def log_audit(
    db: AsyncSession,
    auth: AuthSession,
    action: str,
    request: Request | None = None,
    resource_type: str = "",
    resource_id: str | None = None,
    details: dict | None = None,
) -> None:
    """Helper para registrar ação no audit log."""
    from app.services.audit_service import AuditService
    svc = AuditService(db)
    ip = request.client.host if request and request.client else None
    await svc.log(
        user_id=auth.user_id,
        user_name=auth.user_name,
        user_email=auth.user_email,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        ip_address=ip,
    )
