"""Modelo de SkillCriterion — critérios estruturados de análise."""
from typing import Optional

from sqlmodel import Field, Relationship, SQLModel


class SkillCriterion(SQLModel, table=True):
    __tablename__ = "skill_criteria"

    id: Optional[int] = Field(default=None, primary_key=True)
    skill_id: int = Field(foreign_key="skills.id", index=True)
    order: int = Field(default=1)
    nome: str = Field(max_length=200)
    tipo: str = Field(max_length=50)  # presenca_documento | classificacao_documento | conferencia_conteudo
    config_json: str = Field(default="{}")
    is_active: bool = Field(default=True)

    skill: Optional["Skill"] = Relationship(back_populates="criteria")  # noqa: F821
