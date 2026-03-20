"""Serviço de gerenciamento de Sessions."""
import json
import logging
import shutil

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.config import BASE_DIR
from app.core.exceptions import NotFoundError
from app.models.etapa import Etapa
from app.models.skill import Skill
from app.models.session import Session
from app.models.chat_message import ChatMessage as ChatMessageRecord
from app.schemas.session import GoSatiSelection, SessionCreate
from app.services.chat_service import clear_session_cache
from app.services.gosati_service import clear_prestacao_cache

logger = logging.getLogger(__name__)


class SessionService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_all(self) -> list[Session]:
        result = await self.db.execute(select(Session).order_by(Session.created_at.desc()))
        return result.scalars().all()

    async def get_by_id(self, session_id: int) -> Session:
        session = await self.db.get(Session, session_id)
        if not session:
            raise NotFoundError(404, f"Session {session_id} não encontrada")
        return session

    async def create(self, data: SessionCreate, auth=None) -> Session:
        session = Session(**data.model_dump())
        if session.gosati_condominio_codigo:
            session.gosati_query_type = "prestacao_contas"
            # Vincula ao condomínio agrupador (cria se não existir)
            from app.services.condominio_service import CondominioService
            cond_svc = CondominioService(self.db)
            condominio = await cond_svc.get_or_create(
                session.gosati_condominio_codigo,
                session.gosati_condominio_nome or "",
            )
            session.condominio_id = condominio.id
        self.db.add(session)
        await self.db.commit()
        await self.db.refresh(session)
        return session

    async def update_gosati_selection(self, session_id: int, data: GoSatiSelection) -> Session:
        session = await self.get_by_id(session_id)
        for key, value in data.model_dump().items():
            setattr(session, key, value)
        # Atualiza FK condominio_id se o código mudou
        if data.gosati_condominio_codigo:
            from app.services.condominio_service import CondominioService
            cond_svc = CondominioService(self.db)
            condominio = await cond_svc.get_or_create(
                data.gosati_condominio_codigo,
                data.gosati_condominio_nome or "",
            )
            session.condominio_id = condominio.id
        self.db.add(session)
        await self.db.commit()
        await self.db.refresh(session)
        return session

    async def get_coverage(self, session_id: int) -> dict:
        """Retorna cobertura de análise com pendências reais por skill."""
        session = await self.get_by_id(session_id)
        total = session.gosati_total_despesas or 0

        from sqlalchemy.orm import selectinload
        result = await self.db.execute(
            select(Etapa)
            .options(selectinload(Etapa.skill))
            .where(
                Etapa.session_id == session_id,
                Etapa.status == "done",
            )
        )
        etapas = result.scalars().all()

        analisados: set[str] = set()
        total_criterios = 0
        total_pendentes = 0
        skills_summary: list[dict] = []

        for etapa in etapas:
            if not etapa.result_text:
                continue
            try:
                data = json.loads(etapa.result_text)
                # Conta lançamentos analisados
                for lanc in data.get("lancamentos", []):
                    num = str(lanc.get("numero_lancamento", ""))
                    if num:
                        analisados.add(num)

                # Conta pendências dos critérios
                criterios = data.get("criterios")
                if criterios and isinstance(criterios, dict):
                    resumo = criterios.get("resumo", {})
                    skill_total = resumo.get("total_verificacoes", 0)
                    skill_pend = resumo.get("divergencias", 0) + resumo.get("itens_ausentes", 0)
                    total_criterios += skill_total
                    total_pendentes += skill_pend
                    skill_name = etapa.skill.name if etapa.skill else f"Etapa {etapa.id}"
                    skills_summary.append({
                        "skill_name": skill_name,
                        "total": skill_total,
                        "pendentes": skill_pend,
                        "aprovados": resumo.get("aprovados", 0),
                    })
            except (json.JSONDecodeError, KeyError):
                pass

        n_analisados = len(analisados)
        return {
            "total_despesas": total,
            "analisados": n_analisados,
            "pendentes": total_pendentes,
            "total_criterios": total_criterios,
            "percentual": round(n_analisados / total * 100) if total > 0 else 0,
            "skills": skills_summary,
            "lancamentos_analisados": sorted(analisados),
        }

    async def delete(self, session_id: int) -> None:
        session = await self.get_by_id(session_id)
        # Limpa cache de prestação GoSATI associado a esta sessão
        if session.gosati_condominio_codigo and session.gosati_mes and session.gosati_ano:
            cache_key = f"{session.gosati_condominio_codigo}_{session.gosati_mes}_{session.gosati_ano}"
            clear_prestacao_cache(cache_key)
        # Remove mensagens de chat associadas
        stmt = select(ChatMessageRecord).where(ChatMessageRecord.session_id == session_id)
        result = await self.db.execute(stmt)
        for msg in result.scalars().all():
            await self.db.delete(msg)
        await self.db.delete(session)
        await self.db.commit()
        # Limpa cache em memória
        clear_session_cache(session_id)
        # Limpa arquivos do disco
        for subdir in ("gosati", "uploads"):
            dir_path = BASE_DIR / "data" / subdir / str(session_id)
            if dir_path.exists():
                shutil.rmtree(dir_path, ignore_errors=True)
                logger.info("Removido diretório: %s", dir_path)
        # Limpa resultado de conferência
        conf_file = BASE_DIR / "data" / "conferencias" / f"{session_id}.json"
        if conf_file.exists():
            conf_file.unlink(missing_ok=True)
            logger.info("Removido conferência: %s", conf_file)
