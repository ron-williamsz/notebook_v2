"""Modelo de log de auditoria."""
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_logs"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    user_name: str
    user_email: str
    action: str = Field(max_length=50, index=True)
    resource_type: str = Field(default="", max_length=50)
    resource_id: Optional[str] = Field(default=None)
    details: Optional[str] = Field(default=None)
    ip_address: Optional[str] = Field(default=None, max_length=45)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), index=True
    )
