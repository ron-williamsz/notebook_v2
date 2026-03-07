"""Schemas de request/response para Sources."""
from datetime import datetime

from pydantic import BaseModel


class SourceResponse(BaseModel):
    id: int
    session_id: int
    filename: str
    mime_type: str
    size_bytes: int
    origin: str
    label: str
    created_at: datetime

    model_config = {"from_attributes": True}
