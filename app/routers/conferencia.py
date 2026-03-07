"""Conferencia (audit) de comprovantes de despesas condominiais."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.core.config import Settings, get_settings
from app.schemas.conferencia import (
    ConferenciaBatchResult,
    ConferenciaStartRequest,
    ConferenciaStatus,
)
from app.services.conferencia_service import ConferenciaService

router = APIRouter(
    prefix="/sessions/{session_id}/conferencia",
    tags=["Conferencia"],
)


@router.post("/start")
async def start_conferencia(
    session_id: str,
    body: ConferenciaStartRequest,
    settings: Settings = Depends(get_settings),
):
    """Start conferencia and stream progress via SSE."""
    svc = ConferenciaService(settings)

    async def event_generator():
        collected_batches: list[ConferenciaBatchResult] = []

        async for event in svc.run_conferencia(
            condominio=body.condominio,
            mes=body.mes,
            ano=body.ano,
            batch_size=body.batch_size,
            tipo_conta=body.tipo_conta,
        ):
            if event.batch_result:
                collected_batches.append(event.batch_result)

            if event.status == ConferenciaStatus.COMPLETED and event.final_report:
                ConferenciaService.save_result(
                    session_id=session_id,
                    report=event.final_report,
                    pendencias=event.pendencias,
                    batch_results=collected_batches,
                    condominio_nome=event.condominio_nome or "",
                    condominio_codigo=event.condominio_codigo or body.condominio,
                    mes=body.mes,
                    ano=body.ano,
                )

            payload = event.model_dump_json(exclude_none=True)
            yield f"data: {payload}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/result")
async def get_conferencia_result(session_id: str):
    """Retrieve last conferencia result from disk."""
    data = ConferenciaService.get_result(session_id)
    if not data:
        raise HTTPException(
            status_code=404,
            detail="Nenhum resultado de conferencia encontrado",
        )
    return data
