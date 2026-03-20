"""Modelo de Session (notebook do usuário)."""
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, Relationship, SQLModel


class Session(SQLModel, table=True):
    __tablename__ = "sessions"

    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = Field(max_length=200)
    active_skill_id: Optional[int] = Field(default=None, foreign_key="skills.id")
    source_count: int = Field(default=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # FK para tabela agrupadora de condomínio
    condominio_id: Optional[int] = Field(default=None, foreign_key="condominios.id", index=True)

    # GoSATI selection persistence (mantidos como denormalizados)
    gosati_query_type: Optional[str] = Field(default=None)
    gosati_condominio_codigo: Optional[int] = Field(default=None)
    gosati_condominio_nome: Optional[str] = Field(default=None)
    gosati_mes: Optional[int] = Field(default=None)
    gosati_ano: Optional[int] = Field(default=None)
    gosati_total_despesas: Optional[int] = Field(default=None)

    condominio: Optional["Condominio"] = Relationship(back_populates="sessions")
    sources: list["Source"] = Relationship(
        back_populates="session",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    etapas: list["Etapa"] = Relationship(
        back_populates="session",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
