"""Schemas de request/response para Chat."""
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    message: str = Field(min_length=1)


class ChatSkillRequest(BaseModel):
    message: str = Field(
        default="Analise todos os documentos carregados seguindo rigorosamente as instruções e gere o relatório completo no formato especificado.",
        min_length=1,
    )
