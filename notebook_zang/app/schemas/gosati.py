"""Schemas de request/response para GoSATI."""

from pydantic import BaseModel, Field


class GoSatiQuery(BaseModel):
    query_type: str = Field(
        ...,
        description=(
            "Tipo de consulta: prestacao_contas, fluxo_caixa, inadimplencia, "
            "periodo_fechamento, previsao_orcamentaria, relacao_lancamentos, "
            "relacao_pendentes"
        ),
    )
    condominio: int = Field(..., description="Código do condomínio")
    mes: int | None = Field(None, ge=1, le=12, description="Mês (1-12)")
    ano: int | None = Field(None, ge=2000, le=2100, description="Ano")


class GoSatiSourceResponse(BaseModel):
    source_id: int
    label: str
    query_type: str
    size: int


class ComprovantesListRequest(BaseModel):
    condominio: int = Field(..., description="Código do condomínio")
    mes: int | None = Field(None, ge=1, le=12, description="Mês (1-12)")
    ano: int | None = Field(None, ge=2000, le=2100, description="Ano")


class DespesaComprovante(BaseModel):
    numero_lancamento: str = ""
    historico: str = ""
    valor: str = ""
    data: str = ""
    nome_conta: str = ""
    nome_sub_conta: str = ""
    link_docto: str = ""
    catalogo_id: str = ""


class ComprovantesListResponse(BaseModel):
    despesas: list[DespesaComprovante]
    total: int


class ComprovanteLinkInfo(BaseModel):
    link_docto: str = ""
    numero_lancamento: str = ""
    historico: str = ""
    valor: str = ""
    catalogo_id: str = ""


class ComprovantesDownloadRequest(BaseModel):
    despesas: list[ComprovanteLinkInfo] = Field(
        default=[], description="Lista com info do lançamento + catalogo_id"
    )


class ComprovantesDownloadResponse(BaseModel):
    downloaded: int
    source_ids: list[int]
