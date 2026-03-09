"""Modelos de Skill, SkillStep e SkillExample."""
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, Relationship, SQLModel


class Skill(SQLModel, table=True):
    __tablename__ = "skills"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=100, index=True)
    description: str = Field(max_length=500, default="")
    icon: str = Field(default="📋", max_length=10)
    color: str = Field(default="#6366f1", max_length=9)
    macro_instruction: str = Field(default="")
    execution_mode: str = Field(default="chat", max_length=20)
    gosati_sections: Optional[str] = Field(default=None)
    gosati_filters: Optional[str] = Field(default=None)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    steps: list["SkillStep"] = Relationship(
        back_populates="skill",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "order_by": "SkillStep.order"},
    )
    examples: list["SkillExample"] = Relationship(
        back_populates="skill",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    criteria: list["SkillCriterion"] = Relationship(  # noqa: F821
        back_populates="skill",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "order_by": "SkillCriterion.order"},
    )


class SkillStep(SQLModel, table=True):
    __tablename__ = "skill_steps"

    id: Optional[int] = Field(default=None, primary_key=True)
    skill_id: int = Field(foreign_key="skills.id", index=True)
    order: int = Field(default=1)
    title: str = Field(max_length=200)
    instruction: str = Field(default="")
    expected_output: Optional[str] = Field(default=None)

    skill: Optional[Skill] = Relationship(back_populates="steps")


class SkillExample(SQLModel, table=True):
    __tablename__ = "skill_examples"

    id: Optional[int] = Field(default=None, primary_key=True)
    skill_id: int = Field(foreign_key="skills.id", index=True)
    filename: str
    file_path: str
    description: str = Field(default="")
    mime_type: str = Field(default="application/octet-stream")

    skill: Optional[Skill] = Relationship(back_populates="examples")
