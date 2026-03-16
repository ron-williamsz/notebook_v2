"""Modelo de sessão de autenticação (server-side sessions)."""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


class AuthSession(SQLModel, table=True):
    __tablename__ = "auth_sessions"

    id: str = Field(default_factory=lambda: uuid.uuid4().hex, primary_key=True)
    user_id: int
    user_name: str
    user_email: str
    bdforall_token: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc) + timedelta(hours=12)
    )
    role: str = Field(default="user", max_length=20)  # "user" or "admin"
    selected_cond_codigo: int | None = Field(default=None)
    selected_cond_nome: str | None = Field(default=None)
