"""Rotas de auditoria (admin only)."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_admin
from app.models.auth_session import AuthSession
from app.models.base import get_db
from app.services.audit_service import AuditService

router = APIRouter(prefix="/audit", tags=["Audit"])


def _svc(db: AsyncSession = Depends(get_db)) -> AuditService:
    return AuditService(db)


@router.get("")
async def list_audit_logs(
    user_email: str | None = Query(None),
    action: str | None = Query(None),
    period: int = Query(30, ge=1, le=365),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    svc: AuditService = Depends(_svc),
    _admin: AuthSession = Depends(require_admin),
):
    rows, total = await svc.query(
        user_email=user_email, action=action,
        period_days=period, offset=offset, limit=limit,
    )
    return {
        "items": [
            {
                "id": r.id,
                "user_name": r.user_name,
                "user_email": r.user_email,
                "action": r.action,
                "resource_type": r.resource_type,
                "resource_id": r.resource_id,
                "details": r.details,
                "ip_address": r.ip_address,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
        "total": total,
    }


@router.get("/counters")
async def get_counters(
    period: int = Query(30, ge=1, le=365),
    svc: AuditService = Depends(_svc),
    _admin: AuthSession = Depends(require_admin),
):
    return await svc.get_counters(period_days=period)


@router.get("/users")
async def get_active_users(
    period: int = Query(30, ge=1, le=365),
    svc: AuditService = Depends(_svc),
    _admin: AuthSession = Depends(require_admin),
):
    return await svc.get_active_users(period_days=period)
