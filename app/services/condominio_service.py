"""Serviço de gerenciamento de Condomínios locais."""
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.config import Settings
from app.models.condominio import Condominio
from app.models.session import Session

logger = logging.getLogger(__name__)


class CondominioService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_or_create(self, codigo: int, nome: str) -> Condominio:
        """Busca condomínio pelo código ou cria se não existir."""
        result = await self.db.execute(
            select(Condominio).where(Condominio.gosati_condominio_codigo == codigo)
        )
        cond = result.scalar_one_or_none()
        if cond:
            # Atualiza nome se mudou
            if nome and cond.gosati_condominio_nome != nome:
                cond.gosati_condominio_nome = nome
                cond.updated_at = datetime.now(timezone.utc)
                self.db.add(cond)
                await self.db.flush()
            return cond

        cond = Condominio(
            gosati_condominio_codigo=codigo,
            gosati_condominio_nome=nome,
        )
        self.db.add(cond)
        try:
            await self.db.flush()
        except Exception:
            # Race condition: outro request criou primeiro, busca de novo
            await self.db.rollback()
            result = await self.db.execute(
                select(Condominio).where(Condominio.gosati_condominio_codigo == codigo)
            )
            cond = result.scalar_one_or_none()
            if cond:
                return cond
            raise
        await self.db.refresh(cond)
        return cond

    async def list_all(self, busca: str = "") -> list[dict]:
        """Lista condomínios locais com contagem de notebooks."""
        stmt = (
            select(
                Condominio.id,
                Condominio.gosati_condominio_codigo,
                Condominio.gosati_condominio_nome,
                Condominio.status,
                func.count(Session.id).label("session_count"),
            )
            .outerjoin(Session, Session.condominio_id == Condominio.id)
            .group_by(Condominio.id)
        )

        if busca:
            q = busca.lower()
            from sqlalchemy import String, cast
            stmt = stmt.where(
                (func.lower(Condominio.gosati_condominio_nome).contains(q))
                | (cast(Condominio.gosati_condominio_codigo, String).contains(q))
            )

        stmt = stmt.order_by(Condominio.gosati_condominio_codigo)
        result = await self.db.execute(stmt)

        return [
            {
                "id": r[0],
                "codigo": r[1],
                "nome": r[2],
                "status": r[3],
                "session_count": r[4],
            }
            for r in result.all()
        ]

    async def sync_from_bdforall(self, settings: Settings) -> dict:
        """Sincroniza condomínios da API BD FOR ALL para a tabela local."""
        if not settings.bdforall_email or not settings.bdforall_senha:
            raise ValueError("Credenciais BD FOR ALL não configuradas no .env")

        base = settings.bdforall_url.rstrip("/")
        criados = 0
        atualizados = 0

        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            # Login
            login_resp = await client.post(
                f"{base}/api/auth/login",
                params={"email": settings.bdforall_email, "senha": settings.bdforall_senha},
            )
            if login_resp.status_code != 200:
                raise ValueError("Falha ao autenticar na API BD FOR ALL")

            token = login_resp.json().get("access_token")

            # Busca condomínios
            resp = await client.get(
                f"{base}/api/condominios",
                params={"limit": 500, "status": "ativo"},
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code != 200:
                raise ValueError("Falha ao buscar condomínios da API BD FOR ALL")

            items = resp.json().get("data", [])

        now = datetime.now(timezone.utc)
        codigos_ativos = set()

        for c in items:
            codigo_raw = c.get("codigo_ahreas")
            if not codigo_raw:
                continue
            codigo = int(codigo_raw)
            nome = c.get("nome", "")
            codigos_ativos.add(codigo)

            result = await self.db.execute(
                select(Condominio).where(Condominio.gosati_condominio_codigo == codigo)
            )
            existing = result.scalar_one_or_none()

            if existing:
                if existing.gosati_condominio_nome != nome or existing.status != "ativo":
                    existing.gosati_condominio_nome = nome
                    existing.status = "ativo"
                    existing.updated_at = now
                    self.db.add(existing)
                    atualizados += 1
            else:
                self.db.add(Condominio(
                    gosati_condominio_codigo=codigo,
                    gosati_condominio_nome=nome,
                    status="ativo",
                    created_at=now,
                    updated_at=now,
                ))
                criados += 1

        await self.db.commit()

        total = len(codigos_ativos)
        logger.info("Sync condomínios: %d criados, %d atualizados, %d total", criados, atualizados, total)
        return {"criados": criados, "atualizados": atualizados, "total": total}
