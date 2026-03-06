"""Schemas de request/response para Sessions."""
from datetime import datetime

from pydantic import BaseModel, Field


class SessionCreate(BaseModel):
    title: str = Field(max_length=200)
    gosati_condominio_codigo: int | None = None
    gosati_condominio_nome: str | None = None
    gosati_mes: int | None = None
    gosati_ano: int | None = None


class GoSatiSelection(BaseModel):
    gosati_query_type: str | None = None
    gosati_condominio_codigo: int | None = None
    gosati_condominio_nome: str | None = None
    gosati_mes: int | None = None
    gosati_ano: int | None = None


class SessionResponse(BaseModel):
    id: int
    title: str
    active_skill_id: int | None
    source_count: int
    created_at: datetime
    gosati_query_type: str | None = None
    gosati_condominio_codigo: int | None = None
    gosati_condominio_nome: str | None = None
    gosati_mes: int | None = None
    gosati_ano: int | None = None

    model_config = {"from_attributes": True}
