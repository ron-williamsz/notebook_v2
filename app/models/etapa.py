"""Modelo de Etapa — execução de uma Skill dentro de uma sessão."""
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, Relationship, SQLModel


class Etapa(SQLModel, table=True):
    __tablename__ = "etapas"

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="sessions.id", index=True)
    skill_id: int = Field(foreign_key="skills.id")
    order: int = Field(default=1)
    status: str = Field(default="pending", max_length=20)  # pending | running | done | error
    result_text: Optional[str] = Field(default=None)
    error_message: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    session: Optional["Session"] = Relationship(
        back_populates="etapas",
        sa_relationship_kwargs={"lazy": "noload"},
    )  # noqa: F821
    skill: Optional["Skill"] = Relationship()  # noqa: F821
