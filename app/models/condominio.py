"""Modelo Condominio — agrupador de notebooks (sessions) por condomínio."""
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, Relationship, SQLModel


class Condominio(SQLModel, table=True):
    __tablename__ = "condominios"

    id: Optional[int] = Field(default=None, primary_key=True)
    gosati_condominio_codigo: int = Field(unique=True, index=True)
    gosati_condominio_nome: str = Field(max_length=300, default="")
    status: str = Field(default="ativo", max_length=20)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    sessions: list["Session"] = Relationship(
        back_populates="condominio",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
