"""Modelo de ChatMessage — persistência do histórico de chat por sessão."""
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


class ChatMessage(SQLModel, table=True):
    __tablename__ = "chat_messages"

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="sessions.id", index=True)
    role: str = Field(max_length=10)  # "user" | "model"
    text: str = Field(default="")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
