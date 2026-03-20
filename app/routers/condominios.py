"""Condomínios — lista local + sincronização com BD FOR ALL."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.dependencies import require_admin
from app.models.auth_session import AuthSession
from app.models.base import get_db
from app.services.condominio_service import CondominioService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/condominios", tags=["Condominios"])


def _svc(db: AsyncSession = Depends(get_db)) -> CondominioService:
    return CondominioService(db)


@router.get("")
async def list_condominios(
    busca: str = Query("", description="Filtro por código ou nome"),
    svc: CondominioService = Depends(_svc),
):
    """Retorna condomínios da tabela local com contagem de notebooks."""
    return await svc.list_all(busca=busca)


@router.post("/sync")
async def sync_condominios(
    svc: CondominioService = Depends(_svc),
    settings: Settings = Depends(get_settings),
    _admin: AuthSession = Depends(require_admin),
):
    """Sincroniza condomínios da API BD FOR ALL (admin only)."""
    try:
        result = await svc.sync_from_bdforall(settings)
        return result
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        logger.exception("Erro ao sincronizar condomínios")
        raise HTTPException(status_code=502, detail=f"Erro na sincronização: {e}")
