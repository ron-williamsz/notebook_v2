"""Serviço de auditoria — registro e consulta de ações de usuários."""
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.audit_log import AuditLog

logger = logging.getLogger(__name__)


class AuditService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def log(
        self,
        user_id: int,
        user_name: str,
        user_email: str,
        action: str,
        resource_type: str = "",
        resource_id: str | None = None,
        details: dict | None = None,
        ip_address: str | None = None,
    ) -> None:
        """Registra ação no audit log."""
        entry = AuditLog(
            user_id=user_id,
            user_name=user_name,
            user_email=user_email,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=json.dumps(details, ensure_ascii=False) if details else None,
            ip_address=ip_address,
        )
        self.db.add(entry)
        await self.db.commit()

    async def query(
        self,
        user_email: str | None = None,
        action: str | None = None,
        period_days: int = 30,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[AuditLog], int]:
        """Consulta audit logs com filtros."""
        since = datetime.now(timezone.utc) - timedelta(days=period_days)

        stmt = select(AuditLog).where(AuditLog.created_at >= since)
        count_stmt = select(func.count(AuditLog.id)).where(AuditLog.created_at >= since)

        if user_email:
            stmt = stmt.where(AuditLog.user_email == user_email)
            count_stmt = count_stmt.where(AuditLog.user_email == user_email)
        if action:
            stmt = stmt.where(AuditLog.action == action)
            count_stmt = count_stmt.where(AuditLog.action == action)

        total = (await self.db.execute(count_stmt)).scalar() or 0
        rows = (
            await self.db.execute(
                stmt.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)
            )
        ).scalars().all()

        return rows, total

    async def get_counters(self, period_days: int = 30) -> dict:
        """Contadores de ações no período."""
        since = datetime.now(timezone.utc) - timedelta(days=period_days)
        stmt = (
            select(AuditLog.action, func.count(AuditLog.id))
            .where(AuditLog.created_at >= since)
            .group_by(AuditLog.action)
        )
        result = await self.db.execute(stmt)
        return dict(result.all())

    async def get_active_users(self, period_days: int = 30) -> list[dict]:
        """Usuários com atividade no período."""
        since = datetime.now(timezone.utc) - timedelta(days=period_days)
        stmt = (
            select(
                AuditLog.user_email,
                AuditLog.user_name,
                func.count(AuditLog.id).label("total_actions"),
                func.max(AuditLog.created_at).label("last_action"),
            )
            .where(AuditLog.created_at >= since)
            .group_by(AuditLog.user_email, AuditLog.user_name)
            .order_by(func.max(AuditLog.created_at).desc())
        )
        result = await self.db.execute(stmt)
        return [
            {
                "user_email": r[0],
                "user_name": r[1],
                "total_actions": r[2],
                "last_action": r[3].isoformat() if r[3] else None,
            }
            for r in result.all()
        ]
