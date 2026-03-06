"""Modelo de Source (arquivo/dado carregado em uma session)."""
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, Relationship, SQLModel


class Source(SQLModel, table=True):
    __tablename__ = "sources"

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="sessions.id", index=True)
    filename: str
    file_path: str = Field(default="")
    mime_type: str = Field(default="application/octet-stream")
    size_bytes: int = Field(default=0)
    origin: str = Field(default="upload")  # "upload" | "gosati"
    label: str = Field(default="")
    text_path: str = Field(default="")  # caminho do .txt extraído (se convertido)
    is_native: bool = Field(default=True)  # True = Gemini lê direto; False = precisa do .txt
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    session: Optional["Session"] = Relationship(back_populates="sources")
