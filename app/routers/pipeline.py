"""Pipeline — execução sequencial de todas as skills."""
import asyncio
import json
import logging
import time

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from urllib.parse import urlparse

from app.core.config import Settings, get_settings
from app.core.dependencies import log_audit, require_auth
from app.core.redis import get_redis
from app.models.auth_session import AuthSession
from app.models.base import get_db
from app.services.pipeline_service import PipelineService, PIPELINE_CHANNEL

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions/{session_id}/pipeline", tags=["Pipeline"])


def _arq_redis_settings(url: str) -> RedisSettings:
    parsed = urlparse(url)
    return RedisSettings(
        host=parsed.hostname or "redis",
        port=parsed.port or 6379,
        database=int(parsed.path.lstrip("/") or 0),
        password=parsed.password,
    )


@router.post("/start")
async def start_pipeline(
    session_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    redis: Redis = Depends(get_redis),
    auth: AuthSession = Depends(require_auth),
):
    """Inicia pipeline: cria etapas para todas as skills e enfileira execução."""
    # Busca condomínio para enriquecer o audit log
    from app.models.session import Session
    from sqlmodel import select as sel
    audit_details: dict = {"session_id": session_id}
    try:
        sess_row = (await db.execute(sel(Session).where(Session.id == session_id))).scalar_one_or_none()
        if sess_row:
            cond_nome = sess_row.gosati_condominio_nome or ""
            cond_cod = sess_row.gosati_condominio_codigo or ""
            audit_details["condominio"] = f"{cond_cod} - {cond_nome}".strip(" -")
    except Exception:
        pass
    await log_audit(
        db, auth, "execute_pipeline", request,
        resource_type="session", resource_id=str(session_id),
        details=audit_details,
    )
    svc = PipelineService(db, settings, redis)
    try:
        result = await svc.start_pipeline(session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Enfileira job no ARQ worker
    arq_pool = await create_pool(_arq_redis_settings(settings.redis_url))
    try:
        await arq_pool.enqueue_job(
            "run_pipeline",
            session_id,
            result["etapa_ids"],
            _job_id=f"pipeline-{session_id}",
        )
    finally:
        await arq_pool.aclose()

    return result


@router.get("/status")
async def get_pipeline_status(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    redis: Redis = Depends(get_redis),
):
    """Retorna estado atual do pipeline."""
    svc = PipelineService(db, settings, redis)
    status = await svc.get_status(session_id)
    if not status:
        raise HTTPException(status_code=404, detail="Nenhum pipeline encontrado")
    return status


@router.post("/cancel")
async def cancel_pipeline(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    redis: Redis = Depends(get_redis),
):
    """Cancela pipeline em execução."""
    svc = PipelineService(db, settings, redis)
    await svc.cancel_pipeline(session_id)
    return {"status": "cancelled"}


@router.get("/stream")
async def stream_pipeline(
    session_id: int,
    redis: Redis = Depends(get_redis),
):
    """SSE stream do progresso do pipeline via Redis PubSub."""
    channel = PIPELINE_CHANNEL.format(session_id=session_id)

    max_duration = 1800  # 30 min — mesmo timeout do worker ARQ

    async def event_generator():
        pubsub = redis.pubsub()
        await pubsub.subscribe(channel)
        started_at = time.monotonic()
        try:
            while True:
                # Timeout: encerra stream se exceder duração máxima
                if time.monotonic() - started_at > max_duration:
                    yield f'data: {json.dumps({"type": "error", "message": "Stream timeout"})}\n\n'
                    yield "data: [DONE]\n\n"
                    return

                msg = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if msg and msg["type"] == "message":
                    data = msg["data"]
                    yield f"data: {data}\n\n"
                    # Verifica se é mensagem terminal
                    try:
                        parsed = json.loads(data)
                        if parsed.get("type") in ("done", "error", "cancelled"):
                            yield "data: [DONE]\n\n"
                            return
                    except (json.JSONDecodeError, ValueError):
                        pass
                else:
                    # Heartbeat para manter conexão SSE viva
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


@router.get("/summary")
async def get_pipeline_summary(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    redis: Redis = Depends(get_redis),
):
    """Retorna resumo agregado de pendências de todas as etapas."""
    svc = PipelineService(db, settings, redis)
    return await svc.build_summary(session_id)
