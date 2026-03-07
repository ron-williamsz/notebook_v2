"""CRUD de Skills (admin)."""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.base import get_db
from app.schemas.skill import (
    SkillCardResponse,
    SkillCreate,
    SkillResponse,
    SkillUpdate,
    StepCreate,
    StepResponse,
    StepSyncRequest,
    StepUpdate,
)
from app.services.skill_service import SkillService

router = APIRouter(prefix="/skills", tags=["Skills"])


def _svc(db: AsyncSession = Depends(get_db)) -> SkillService:
    return SkillService(db)


# --- Skill CRUD ---

@router.get("", response_model=list[SkillCardResponse])
async def list_skills(svc: SkillService = Depends(_svc)):
    return await svc.list_all()


@router.post("", response_model=SkillResponse, status_code=201)
async def create_skill(data: SkillCreate, svc: SkillService = Depends(_svc)):
    return await svc.create(data)


@router.get("/{skill_id}", response_model=SkillResponse)
async def get_skill(skill_id: int, svc: SkillService = Depends(_svc)):
    return await svc.get_by_id(skill_id)


@router.put("/{skill_id}", response_model=SkillResponse)
async def update_skill(skill_id: int, data: SkillUpdate, svc: SkillService = Depends(_svc)):
    return await svc.update(skill_id, data)


@router.delete("/{skill_id}", status_code=204)
async def delete_skill(skill_id: int, svc: SkillService = Depends(_svc)):
    await svc.delete(skill_id)


# --- Steps ---

@router.post("/{skill_id}/steps", response_model=StepResponse, status_code=201)
async def add_step(skill_id: int, data: StepCreate, svc: SkillService = Depends(_svc)):
    return await svc.add_step(skill_id, data)


@router.put("/{skill_id}/steps/{step_id}", response_model=StepResponse)
async def update_step(
    skill_id: int, step_id: int, data: StepUpdate, svc: SkillService = Depends(_svc)
):
    return await svc.update_step(skill_id, step_id, data)


@router.delete("/{skill_id}/steps/{step_id}", status_code=204)
async def delete_step(skill_id: int, step_id: int, svc: SkillService = Depends(_svc)):
    await svc.delete_step(skill_id, step_id)


@router.put("/{skill_id}/steps", response_model=list[StepResponse])
async def sync_steps(skill_id: int, data: StepSyncRequest, svc: SkillService = Depends(_svc)):
    """Substitui todas as etapas atomicamente (delete + recreate em 1 transação)."""
    return await svc.sync_steps(skill_id, data.steps)


# --- Examples ---

@router.post("/{skill_id}/examples", status_code=201)
async def upload_example(
    skill_id: int,
    file: UploadFile = File(...),
    description: str = Form(""),
    svc: SkillService = Depends(_svc),
):
    return await svc.add_example(skill_id, file, description)


@router.delete("/{skill_id}/examples/{example_id}", status_code=204)
async def delete_example(
    skill_id: int, example_id: int, svc: SkillService = Depends(_svc)
):
    await svc.delete_example(skill_id, example_id)


# --- Export / Import ---

@router.get("/{skill_id}/export")
async def export_skill(skill_id: int, svc: SkillService = Depends(_svc)):
    """Exporta skill como arquivo ZIP (skill.json + examples/)."""
    zip_buffer, filename = await svc.export_skill(skill_id)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import", response_model=SkillResponse, status_code=201)
async def import_skill(file: UploadFile = File(...), svc: SkillService = Depends(_svc)):
    """Importa skill de um arquivo ZIP."""
    content = await file.read()
    try:
        return await svc.import_skill(content)
    except NotFoundError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
