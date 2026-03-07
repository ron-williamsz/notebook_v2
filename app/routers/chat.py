"""Chat com LLM (streaming via SSE)."""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models.base import get_db
from app.models.skill import Skill
from app.schemas.chat import ChatMessage, ChatSkillRequest
from app.schemas.conferencia import ConferenciaBatchResult, ConferenciaStatus
from app.services.chat_service import ChatService, clear_session_cache
from app.services.conferencia_service import ConferenciaService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions/{session_id}/chat", tags=["Chat"])


@router.post("")
async def send_message(
    session_id: int,
    data: ChatMessage,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    svc = ChatService(db, settings)
    return StreamingResponse(
        svc.chat_stream(session_id, data.message),
        media_type="text/event-stream",
    )


@router.post("/skill/{skill_id}")
async def execute_skill(
    session_id: int,
    skill_id: int,
    data: ChatSkillRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    skill = await db.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill não encontrada")

    if skill.execution_mode == "conferencia":
        return StreamingResponse(
            _run_conferencia_as_chat(session_id, db, settings),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    svc = ChatService(db, settings)
    return StreamingResponse(
        svc.chat_with_skill(session_id, skill_id, data.message),
        media_type="text/event-stream",
    )


async def _run_conferencia_as_chat(
    session_id: int,
    db: AsyncSession,
    settings: Settings,
):
    """Bridge: executa ConferenciaService e traduz eventos para formato SSE do chat."""
    from app.models.session import Session

    session = await db.get(Session, session_id)
    if not session or not session.gosati_condominio_codigo:
        yield f"data: {json.dumps({'error': 'Selecione um condomínio e consulte a prestação de contas antes de executar a conferência.'})}\n\n"
        yield "data: [DONE]\n\n"
        return

    condominio = session.gosati_condominio_codigo
    mes = session.gosati_mes or 1
    ano = session.gosati_ano or 2026

    svc = ConferenciaService(settings)
    collected_batches: list[ConferenciaBatchResult] = []

    try:
        async for event in svc.run_conferencia(
            condominio=condominio,
            mes=mes,
            ano=ano,
            batch_size=5,
        ):
            if event.batch_result:
                collected_batches.append(event.batch_result)

            if event.status == ConferenciaStatus.ERROR:
                yield f"data: {json.dumps({'error': event.error or event.message})}\n\n"

            elif event.status == ConferenciaStatus.COMPLETED and event.final_report:
                # Salva relatório COMPLETO em disco
                ConferenciaService.save_result(
                    session_id=session_id,
                    report=event.final_report,
                    pendencias=event.pendencias,
                    batch_results=collected_batches,
                    condominio_nome=event.condominio_nome or "",
                    condominio_codigo=event.condominio_codigo or condominio,
                    mes=mes,
                    ano=ano,
                )
                # Envia relatório completo para o chat
                yield f"data: {json.dumps({'text': event.final_report})}\n\n"

            else:
                # Progress events (PENDING, DOWNLOADING, ANALYZING, CONSOLIDATING)
                msg = event.message
                if event.batch_current and event.batch_total:
                    msg = f"[{event.batch_current}/{event.batch_total}] {msg}"
                yield f"data: {json.dumps({'progress': msg})}\n\n"

    except Exception as e:
        logger.exception("Erro na conferência para sessão %d", session_id)
        yield f"data: {json.dumps({'error': f'Erro interno na conferência: {e}'})}\n\n"

    yield "data: [DONE]\n\n"


@router.get("/history")
async def get_history(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    svc = ChatService(db, settings)
    return await svc.get_history(session_id)


@router.delete("/cache", status_code=204)
async def reset_chat_cache(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Limpa histórico do chat no banco e cache em memória."""
    svc = ChatService(db, settings)
    await svc.clear_history(session_id)
