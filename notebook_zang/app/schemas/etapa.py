"""Schemas de request/response para Etapas."""
from datetime import datetime

from pydantic import BaseModel


class EtapaCreate(BaseModel):
    skill_id: int


class EtapaResponse(BaseModel):
    id: int
    session_id: int
    skill_id: int
    skill_name: str = ""
    skill_icon: str = ""
    skill_color: str = ""
    order: int
    status: str
    result_text: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
