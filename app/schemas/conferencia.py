from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ConferenciaStatus(str, Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    ANALYZING = "analyzing"
    CONSOLIDATING = "consolidating"
    COMPLETED = "completed"
    ERROR = "error"


class ConferenciaStartRequest(BaseModel):
    condominio: int = Field(..., description="Codigo do condominio")
    mes: int = Field(..., ge=1, le=12, description="Mes (1-12)")
    ano: int = Field(..., ge=2000, le=2100, description="Ano")
    batch_size: int = Field(5, ge=1, le=10, description="Despesas por lote")
    tipo_conta: str = Field("propria", description="Tipo de conta: 'propria' ou 'pool'")


class ConferenciaBatchResult(BaseModel):
    batch_index: int
    despesas_count: int
    findings: str


class ConferenciaProgressEvent(BaseModel):
    status: ConferenciaStatus
    message: str
    batch_current: int = 0
    batch_total: int = 0
    percent: int = 0
    batch_result: ConferenciaBatchResult | None = None
    final_report: str | None = None
    condominio_nome: str | None = None
    condominio_codigo: int | None = None
    pendencias: list[dict[str, Any]] | None = None
    error: str | None = None
