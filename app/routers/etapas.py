"""Etapas — CRUD e execução de Etapas dentro de uma sessão."""
import asyncio
import json

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from urllib.parse import urlparse

from app.core.config import Settings, get_settings
from app.core.dependencies import log_audit, require_auth
from app.core.redis import get_redis
from app.models.auth_session import AuthSession
from app.models.base import get_db
from app.schemas.etapa import EtapaCreate
from app.services.etapa_service import EtapaService
from app.services.pipeline_service import ETAPA_CHANNEL

router = APIRouter(prefix="/sessions/{session_id}/etapas", tags=["Etapas"])


def _arq_redis_settings(url: str) -> RedisSettings:
    parsed = urlparse(url)
    return RedisSettings(
        host=parsed.hostname or "redis",
        port=parsed.port or 6379,
        database=int(parsed.path.lstrip("/") or 0),
        password=parsed.password,
    )


@router.get("")
async def list_etapas(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    svc = EtapaService(db, settings)
    return await svc.list_by_session(session_id)


@router.post("", status_code=201)
async def create_etapa(
    session_id: int,
    data: EtapaCreate,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    svc = EtapaService(db, settings)
    return await svc.create(session_id, data.skill_id)


@router.post("/{etapa_id}/execute")
async def execute_etapa(
    session_id: int,
    etapa_id: int,
    request: Request,
    settings: Settings = Depends(get_settings),
    redis: Redis = Depends(get_redis),
    auth: AuthSession = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Enfileira execução da etapa no worker ARQ (independente do browser)."""
    await log_audit(
        db, auth, "execute_skill", request,
        resource_type="etapa", resource_id=str(etapa_id),
        details={"session_id": session_id},
    )
    # Limpa resultado de job anterior (ARQ dedup por job_id)
    old_result_key = f"arq:result:etapa-{etapa_id}"
    await redis.delete(old_result_key)

    arq_pool = await create_pool(_arq_redis_settings(settings.redis_url))
    try:
        await arq_pool.enqueue_job(
            "run_single_etapa",
            session_id,
            etapa_id,
            _job_id=f"etapa-{etapa_id}",
        )
    finally:
        await arq_pool.aclose()

    return {"status": "queued", "etapa_id": etapa_id}


@router.get("/{etapa_id}/stream")
async def stream_etapa(
    session_id: int,
    etapa_id: int,
    redis: Redis = Depends(get_redis),
):
    """SSE stream do progresso da etapa via Redis PubSub."""
    channel = ETAPA_CHANNEL.format(etapa_id=etapa_id)

    async def event_generator():
        pubsub = redis.pubsub()
        await pubsub.subscribe(channel)
        try:
            while True:
                msg = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if msg and msg["type"] == "message":
                    data = msg["data"]
                    yield f"data: {data}\n\n"
                    # Verifica se é mensagem terminal
                    try:
                        parsed = json.loads(data)
                        if parsed.get("type") in ("done", "error"):
                            yield "data: [DONE]\n\n"
                            return
                    except (json.JSONDecodeError, ValueError):
                        pass
                else:
                    yield ": heartbeat\n\n"
                    await asyncio.sleep(0.5)
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.delete("/{etapa_id}", status_code=204)
async def delete_etapa(
    session_id: int,
    etapa_id: int,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    svc = EtapaService(db, settings)
    await svc.delete(session_id, etapa_id)
