"""PipelineService — orquestra execução sequencial de todas as skills."""
import json
import logging
from datetime import datetime, timezone

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.config import Settings
from app.models.etapa import Etapa
from app.models.session import Session
from app.models.skill import Skill
from app.services.etapa_service import EtapaService

logger = logging.getLogger(__name__)

# Redis keys
PIPELINE_KEY = "pipeline:{session_id}"          # hash: status, current_skill, progress...
PIPELINE_CHANNEL = "pipeline:{session_id}:events"  # pubsub channel
ETAPA_CHANNEL = "etapa:{etapa_id}:events"       # pubsub channel per etapa


class PipelineService:
    """Cria e monitora pipelines de execução sequencial."""

    def __init__(self, db: AsyncSession, settings: Settings, redis: Redis):
        self.db = db
        self.settings = settings
        self.redis = redis

    async def start_pipeline(self, session_id: int) -> dict:
        """Cria etapas para todas as skills ativas e enfileira no ARQ."""
        session = await self.db.get(Session, session_id)
        if not session:
            raise ValueError(f"Session {session_id} não encontrada")

        # Busca todas as skills ativas
        result = await self.db.execute(
            select(Skill).where(Skill.is_active == True).order_by(Skill.id)  # noqa: E712
        )
        skills = result.scalars().all()
        if not skills:
            raise ValueError("Nenhuma skill ativa encontrada")

        # Verifica se já existe pipeline em execução
        pipe_key = PIPELINE_KEY.format(session_id=session_id)
        existing = await self.redis.hget(pipe_key, "status")
        if existing == "running":
            raise ValueError("Pipeline já em execução para esta sessão")

        # Limpa estado anterior do pipeline no Redis
        await self.redis.delete(pipe_key)

        # Remove TODAS as etapas anteriores desta sessão (evita duplicatas)
        # e limpa keys ARQ órfãs (result/retry) das etapas antigas
        old_etapas = await self.db.execute(
            select(Etapa).where(Etapa.session_id == session_id)
        )
        old_etapa_ids = []
        for e in old_etapas.scalars().all():
            old_etapa_ids.append(e.id)
            await self.db.delete(e)
        await self.db.commit()

        # Limpa keys ARQ órfãs das etapas e pipeline anteriores
        cleanup_keys = [
            f"arq:result:pipeline-{session_id}",
            f"arq:retry:pipeline-{session_id}",
        ]
        for eid in old_etapa_ids:
            cleanup_keys.append(f"arq:result:etapa-{eid}")
            cleanup_keys.append(f"arq:retry:etapa-{eid}")
        if cleanup_keys:
            await self.redis.delete(*cleanup_keys)

        # Cria etapas para cada skill
        etapa_svc = EtapaService(self.db, self.settings)
        etapa_ids = []
        skill_names = []
        for skill in skills:
            etapa_data = await etapa_svc.create(session_id, skill.id)
            etapa_ids.append(etapa_data["id"])
            skill_names.append(skill.name)

        # Salva estado do pipeline no Redis
        pipeline_state = {
            "status": "pending",
            "session_id": str(session_id),
            "etapa_ids": json.dumps(etapa_ids),
            "skill_names": json.dumps(skill_names),
            "total": str(len(etapa_ids)),
            "current_index": "0",
            "current_skill": "",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await self.redis.hset(pipe_key, mapping=pipeline_state)
        await self.redis.expire(pipe_key, 7200)  # expira em 2h

        return {
            "session_id": session_id,
            "etapa_ids": etapa_ids,
            "skill_names": skill_names,
            "total": len(etapa_ids),
        }

    async def get_status(self, session_id: int) -> dict | None:
        """Retorna estado atual do pipeline."""
        pipe_key = PIPELINE_KEY.format(session_id=session_id)
        data = await self.redis.hgetall(pipe_key)
        if not data:
            return None
        return {
            "status": data.get("status", "unknown"),
            "session_id": int(data.get("session_id", session_id)),
            "total": int(data.get("total", 0)),
            "current_index": int(data.get("current_index", 0)),
            "current_skill": data.get("current_skill", ""),
            "etapa_ids": json.loads(data.get("etapa_ids", "[]")),
            "skill_names": json.loads(data.get("skill_names", "[]")),
            "error": data.get("error"),
        }

    async def cancel_pipeline(self, session_id: int) -> None:
        """Cancela pipeline em execução."""
        pipe_key = PIPELINE_KEY.format(session_id=session_id)
        await self.redis.hset(pipe_key, "status", "cancelled")
        channel = PIPELINE_CHANNEL.format(session_id=session_id)
        await self.redis.publish(channel, json.dumps({
            "type": "cancelled",
            "message": "Pipeline cancelado pelo usuário",
        }))

    async def build_summary(self, session_id: int) -> dict:
        """Agrega pendências de todas as etapas 'done' da sessão."""
        result = await self.db.execute(
            select(Etapa).where(
                Etapa.session_id == session_id,
                Etapa.status == "done",
            ).order_by(Etapa.order)
        )
        etapas = result.scalars().all()

        skills_summary = []
        total_lancamentos = 0
        total_pendencias = 0

        for etapa in etapas:
            skill = await self.db.get(Skill, etapa.skill_id)
            if not etapa.result_text:
                continue

            try:
                data = json.loads(etapa.result_text)
            except (json.JSONDecodeError, ValueError):
                continue

            lancamentos = data.get("lancamentos", [])
            n_lancto = len(lancamentos)
            total_lancamentos += n_lancto

            # Extrai pendências baseado no tipo de resultado
            pendencias = []
            criterios = data.get("criterios")
            if criterios:
                # Modo critérios: divergências + ausentes
                for grupo in criterios.get("grupos", []):
                    for item in grupo.get("itens", []):
                        if item.get("resultado") in ("DIVERGENCIA", "ITEM_AUSENTE"):
                            pendencias.append({
                                "lancamento": item.get("lancamento", ""),
                                "criterio": grupo.get("criterio_nome", ""),
                                "resultado": item.get("resultado", ""),
                                "detalhes": item.get("detalhes", ""),
                                "lancamento_info": item.get("lancamento_info", {}),
                            })

                resumo = criterios.get("resumo", {})
                skill_info = {
                    "etapa_id": etapa.id,
                    "skill_name": skill.name if skill else "Skill removida",
                    "skill_icon": skill.icon if skill else "",
                    "skill_color": skill.color if skill else "#6366f1",
                    "n_lancto": n_lancto,
                    "aprovados": resumo.get("aprovados", 0),
                    "divergencias": resumo.get("divergencias", 0),
                    "ausentes": resumo.get("itens_ausentes", 0),
                    "pendencias": pendencias,
                }
            else:
                # Modo chat: sem critérios estruturados, apenas conta lancamentos
                skill_info = {
                    "etapa_id": etapa.id,
                    "skill_name": skill.name if skill else "Skill removida",
                    "skill_icon": skill.icon if skill else "",
                    "skill_color": skill.color if skill else "#6366f1",
                    "n_lancto": n_lancto,
                    "aprovados": 0,
                    "divergencias": 0,
                    "ausentes": 0,
                    "pendencias": [],
                }

            total_pendencias += len(pendencias)
            skills_summary.append(skill_info)

        return {
            "session_id": session_id,
            "total_skills": len(skills_summary),
            "total_lancamentos": total_lancamentos,
            "total_pendencias": total_pendencias,
            "skills": skills_summary,
        }


async def execute_pipeline_job(session_id: int, etapa_ids: list[int]) -> None:
    """Job ARQ: executa etapas sequencialmente.

    Roda no worker — cria sua própria sessão de DB e conexão Redis.
    """
    from app.core.config import get_settings
    from app.core.redis import get_redis
    from app.models.base import async_session_maker

    settings = get_settings()
    redis = await get_redis()
    pipe_key = PIPELINE_KEY.format(session_id=session_id)
    channel = PIPELINE_CHANNEL.format(session_id=session_id)

    await redis.hset(pipe_key, "status", "running")
    await redis.publish(channel, json.dumps({
        "type": "started",
        "total": len(etapa_ids),
    }))

    for idx, etapa_id in enumerate(etapa_ids):
        # Verifica se foi cancelado
        status = await redis.hget(pipe_key, "status")
        if status == "cancelled":
            logger.info("Pipeline sessão %d cancelado no índice %d", session_id, idx)
            await redis.publish(channel, json.dumps({
                "type": "cancelled",
                "message": "Pipeline cancelado",
            }))
            return

        # Atualiza progresso no Redis
        async with async_session_maker() as db:
            etapa = await db.get(Etapa, etapa_id)
            skill = await db.get(Skill, etapa.skill_id) if etapa else None
            skill_name = skill.name if skill else f"Etapa {idx + 1}"

        await redis.hset(pipe_key, mapping={
            "current_index": str(idx),
            "current_skill": skill_name,
        })
        await redis.publish(channel, json.dumps({
            "type": "skill_start",
            "index": idx,
            "etapa_id": etapa_id,
            "skill_name": skill_name,
            "total": len(etapa_ids),
        }))

        # Executa a etapa (usa o EtapaService existente)
        try:
            async with async_session_maker() as db:
                svc = EtapaService(db, settings)
                # Consome o generator completamente (executa a skill)
                async for sse_msg in svc.execute(session_id, etapa_id):
                    # Repassa mensagens de progresso via Redis PubSub
                    if sse_msg.startswith("data: "):
                        raw = sse_msg[6:].strip()
                        if raw and raw != "[DONE]":
                            try:
                                parsed = json.loads(raw)
                                if "progress" in parsed:
                                    await redis.publish(channel, json.dumps({
                                        "type": "progress",
                                        "index": idx,
                                        "message": parsed["progress"],
                                    }))
                            except (json.JSONDecodeError, ValueError):
                                pass

            await redis.publish(channel, json.dumps({
                "type": "skill_done",
                "index": idx,
                "etapa_id": etapa_id,
                "skill_name": skill_name,
            }))

        except Exception as e:
            logger.error("Pipeline sessão %d erro na etapa %d: %s", session_id, etapa_id, e)
            await redis.publish(channel, json.dumps({
                "type": "skill_error",
                "index": idx,
                "etapa_id": etapa_id,
                "skill_name": skill_name,
                "message": str(e),
            }))
            # Continua para a próxima etapa ao invés de parar o pipeline
            continue

    # Pipeline completo
    await redis.hset(pipe_key, "status", "done")
    await redis.publish(channel, json.dumps({
        "type": "done",
        "total": len(etapa_ids),
    }))
    # Expira o estado após 1h
    await redis.expire(pipe_key, 3600)
    logger.info("Pipeline sessão %d concluído com sucesso (%d etapas)", session_id, len(etapa_ids))


async def execute_single_etapa_job(session_id: int, etapa_id: int) -> None:
    """Job ARQ: executa uma única etapa em background.

    Roda no worker — independente da conexão do browser.
    Publica progresso via Redis PubSub para SSE no frontend.
    """
    from app.core.config import get_settings
    from app.core.redis import get_redis
    from app.models.base import async_session_maker

    settings = get_settings()
    redis = await get_redis()
    channel = ETAPA_CHANNEL.format(etapa_id=etapa_id)

    try:
        async with async_session_maker() as db:
            svc = EtapaService(db, settings)
            async for sse_msg in svc.execute(session_id, etapa_id):
                if sse_msg.startswith("data: "):
                    raw = sse_msg[6:].strip()
                    if raw == "[DONE]":
                        await redis.publish(channel, json.dumps({"type": "done"}))
                    elif raw:
                        # Repassa o evento SSE original via Redis PubSub
                        await redis.publish(channel, raw)

    except Exception as e:
        logger.error("Etapa %d sessão %d erro: %s", etapa_id, session_id, e)
        await redis.publish(channel, json.dumps({
            "type": "error",
            "error": str(e),
        }))
