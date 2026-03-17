"""Proxy para listar condomínios da API BD FOR ALL."""
import logging
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/condominios", tags=["Condominios"])

# Cache em memória: lista completa + timestamp
_cache: dict = {"data": [], "ts": 0}
CACHE_TTL = 600  # 10 minutos


async def _fetch_condominios(settings: Settings) -> list[dict]:
    """Autentica e busca lista de condomínios da API BD FOR ALL."""
    if not settings.bdforall_email or not settings.bdforall_senha:
        raise HTTPException(502, "Credenciais BD FOR ALL não configuradas no .env")

    base = settings.bdforall_url.rstrip("/")

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        # Login
        login_resp = await client.post(
            f"{base}/api/auth/login",
            params={"email": settings.bdforall_email, "senha": settings.bdforall_senha},
        )
        if login_resp.status_code != 200:
            raise HTTPException(502, "Falha ao autenticar na API BD FOR ALL")

        token = login_resp.json().get("access_token")

        # Busca condomínios (limit alto para pegar todos)
        resp = await client.get(
            f"{base}/api/condominios",
            params={"limit": 500, "status": "ativo"},
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code != 200:
            raise HTTPException(502, "Falha ao buscar condomínios da API BD FOR ALL")

        items = resp.json().get("data", [])
        return [
            {"codigo": int(c["codigo_ahreas"]), "nome": c["nome"]}
            for c in items
            if c.get("codigo_ahreas")
        ]


async def _get_cached(settings: Settings) -> list[dict]:
    """Retorna lista cacheada, revalidando se expirado."""
    now = time.time()
    if _cache["data"] and (now - _cache["ts"]) < CACHE_TTL:
        return _cache["data"]

    data = await _fetch_condominios(settings)
    _cache["data"] = data
    _cache["ts"] = now
    return data


@router.get("")
async def list_condominios(
    busca: str = Query("", description="Filtro por código ou nome"),
    settings: Settings = Depends(get_settings),
):
    """Retorna condomínios filtrados por busca (código ou nome)."""
    try:
        condominios = await _get_cached(settings)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Erro ao buscar condomínios")
        raise HTTPException(502, f"Não foi possível conectar à API BD FOR ALL: {e}")

    if busca:
        q = busca.lower()
        condominios = [
            c for c in condominios
            if q in str(c["codigo"]).lower() or q in c["nome"].lower()
        ]

    condominios.sort(key=lambda c: c["codigo"])
    return condominios
