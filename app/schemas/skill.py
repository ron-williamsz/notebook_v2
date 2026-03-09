"""Schemas de request/response para Skills."""
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.criterio import CriterionResponse


# === Steps ===
class StepCreate(BaseModel):
    title: str = Field(max_length=200)
    instruction: str = ""
    expected_output: str | None = None


class StepUpdate(BaseModel):
    title: str | None = None
    instruction: str | None = None
    expected_output: str | None = None
    order: int | None = None


class StepResponse(BaseModel):
    id: int
    order: int
    title: str
    instruction: str
    expected_output: str | None

    model_config = {"from_attributes": True}


# === Examples ===
class ExampleResponse(BaseModel):
    id: int
    filename: str
    description: str
    mime_type: str

    model_config = {"from_attributes": True}


class StepSyncItem(BaseModel):
    title: str = Field(max_length=200)
    instruction: str = ""
    expected_output: str | None = None


class StepSyncRequest(BaseModel):
    steps: list[StepSyncItem] = []


# === Skill ===
class SkillCreate(BaseModel):
    name: str = Field(max_length=100)
    description: str = Field(max_length=500, default="")
    icon: str = Field(default="📋", max_length=10)
    color: str = Field(default="#6366f1", max_length=9)
    macro_instruction: str = ""
    execution_mode: str = "chat"
    gosati_sections: str | None = None
    gosati_filters: str | None = None


class SkillUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    icon: str | None = None
    color: str | None = None
    macro_instruction: str | None = None
    execution_mode: str | None = None
    is_active: bool | None = None
    gosati_sections: str | None = None
    gosati_filters: str | None = None


class SkillResponse(BaseModel):
    id: int
    name: str
    description: str
    icon: str
    color: str
    macro_instruction: str
    execution_mode: str = "chat"
    is_active: bool
    gosati_sections: str | None = None
    gosati_filters: str | None = None
    created_at: datetime
    updated_at: datetime
    steps: list[StepResponse] = []
    examples: list[ExampleResponse] = []
    criteria: list[CriterionResponse] = []

    model_config = {"from_attributes": True}


class SkillCardResponse(BaseModel):
    """Versão resumida para os cards no notebook."""
    id: int
    name: str
    description: str
    icon: str
    color: str
    is_active: bool

    model_config = {"from_attributes": True}
