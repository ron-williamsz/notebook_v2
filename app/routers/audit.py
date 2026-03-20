"""Rotas de auditoria e gestão de usuários (admin only)."""
import csv
import io
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.dependencies import log_audit, require_admin
from app.models.auth_session import AuthSession
from app.models.base import get_db
from app.models.user_role import UserRole
from app.services.audit_service import AuditService

_BRT = ZoneInfo("America/Sao_Paulo")


def _to_brt(dt: datetime | None) -> str | None:
    """Converte datetime (UTC ou naive) para horário de Brasília ISO string."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_BRT).isoformat()

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
                "created_at": _to_brt(r.created_at),
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


@router.get("/sessions")
async def get_active_sessions(
    db: AsyncSession = Depends(get_db),
    _admin: AuthSession = Depends(require_admin),
):
    """Lista sessões ativas (não expiradas) com role da tabela user_roles."""
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(AuthSession).where(AuthSession.expires_at > now)
        .order_by(AuthSession.created_at.desc())
    )
    sessions = result.scalars().all()

    # Busca roles persistidos na tabela user_roles
    roles_result = await db.execute(select(UserRole))
    roles_map = {r.user_email: r.role for r in roles_result.scalars().all()}

    return [
        {
            "id": s.id[:8],
            "user_id": s.user_id,
            "user_name": s.user_name,
            "user_email": s.user_email,
            "role": roles_map.get(s.user_email.lower(), getattr(s, "role", "user")),
            "created_at": _to_brt(s.created_at),
            "expires_at": _to_brt(s.expires_at),
            "condominio": s.selected_cond_nome or "-",
        }
        for s in sessions
    ]


@router.get("/today")
async def get_today_activity(
    svc: AuditService = Depends(_svc),
    _admin: AuthSession = Depends(require_admin),
):
    """Retorna atividade de hoje agrupada por usuário."""
    return await svc.get_today_activity()


@router.get("/export")
async def export_audit(
    period: str = Query("today", regex="^(today|month)$"),
    svc: AuditService = Depends(_svc),
    _admin: AuthSession = Depends(require_admin),
):
    """Exporta relatório de auditoria em CSV."""
    import json as _json

    action_labels = {
        "login": "Login", "logout": "Logout",
        "create_notebook": "Criar notebook", "delete_notebook": "Excluir notebook",
        "execute_skill": "Executar skill", "execute_pipeline": "Executar pipeline",
        "create_skill": "Criar skill", "update_skill": "Editar skill",
        "delete_skill": "Excluir skill", "import_skill": "Importar skill",
        "change_password": "Alterar senha", "select_condominio": "Selecionar condomínio",
        "change_role": "Alterar role",
    }
    days = 1 if period == "today" else 31
    rows, _ = await svc.query(period_days=days, offset=0, limit=5000)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Data/Hora", "Usuário", "Email", "Ação", "Detalhe", "IP"])
    for r in rows:
        dt = _to_brt(r.created_at) or ""
        label = action_labels.get(r.action, r.action)
        detail = ""
        if r.details:
            try:
                d = _json.loads(r.details)
                parts = []
                if d.get("skill_name"):
                    parts.append(f"Skill: {d['skill_name']}")
                if d.get("condominio"):
                    parts.append(f"Cond: {d['condominio']}")
                if d.get("title"):
                    parts.append(d["title"])
                if d.get("name"):
                    parts.append(d["name"])
                if d.get("session_id") and not parts:
                    parts.append(f"Sessão {d['session_id']}")
                detail = " | ".join(parts)
            except Exception:
                detail = r.details
        if not detail and r.resource_id:
            detail = f"{r.resource_type} #{r.resource_id}"
        writer.writerow([dt, r.user_name, r.user_email, label, detail, r.ip_address or ""])

    buf.seek(0)
    filename = f"auditoria_{period}_{datetime.now(_BRT).strftime('%Y%m%d_%H%M')}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --- User Roles Management ---

@router.get("/roles")
async def list_roles(
    db: AsyncSession = Depends(get_db),
    _admin: AuthSession = Depends(require_admin),
):
    """Lista todos os roles persistidos."""
    result = await db.execute(select(UserRole).order_by(UserRole.user_email))
    return [
        {
            "user_email": r.user_email,
            "role": r.role,
            "updated_at": _to_brt(r.updated_at),
        }
        for r in result.scalars().all()
    ]


class RoleUpdate(BaseModel):
    user_email: str
    role: str  # "admin" ou "user"


@router.put("/roles")
async def set_role(
    data: RoleUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: AuthSession = Depends(require_admin),
):
    """Define ou altera o role de um usuário."""
    if data.role not in ("admin", "user"):
        raise HTTPException(status_code=400, detail="Role inválido. Use 'admin' ou 'user'.")

    email = data.user_email.strip().lower()

    # Não permite remover admin de si mesmo
    if email == admin.user_email.lower() and data.role != "admin":
        raise HTTPException(status_code=400, detail="Você não pode remover seu próprio acesso admin.")

    result = await db.execute(select(UserRole).where(UserRole.user_email == email))
    user_role = result.scalar_one_or_none()

    if user_role:
        user_role.role = data.role
        user_role.updated_at = datetime.now(timezone.utc)
    else:
        user_role = UserRole(user_email=email, role=data.role)
        db.add(user_role)

    await db.commit()

    await log_audit(
        db, admin, "change_role", request,
        resource_type="user", resource_id=email,
        details={"role": data.role},
    )

    return {"user_email": email, "role": data.role}
