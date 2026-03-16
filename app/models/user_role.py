"""Modelo para persistir roles de usuários."""
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


class UserRole(SQLModel, table=True):
    __tablename__ = "user_roles"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_email: str = Field(max_length=200, unique=True, index=True)
    role: str = Field(default="user", max_length=20)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
