"""Schemas de critérios estruturados para skills.

Cinco tipos genéricos:
  1. presenca_documento — documento X existe? (rule-based)
  2. classificacao_documento — que tipo é? (rule-based)
  3. conferencia_conteudo — campo X no doc Y confere com ref Z? (IA)
  4. consistencia_historico — todos os históricos têm o mesmo valor extraído? (rule-based)
  5. conferencia_soma — soma de N lançamentos confere com valor na guia/DARF? (IA)
"""
from typing import Literal

from pydantic import BaseModel, Field


# ── Configs por tipo de critério ──────────────────────────────────────


class PresencaDocumentoConfig(BaseModel):
    """Verifica se um tipo de documento existe no lançamento."""
    documento_nome: str                     # "Relatório Analítico", "Comprovante", "NF"
    palavras_chave: list[str]               # ["Folha de Pagamento da Rotina", "VENCIMENTOS"]
    mime_types: list[str] = []              # ["image/jpeg"] — se vazio, aceita qualquer tipo
    obrigatorio: bool = True
    posicao: Literal["primeiro", "ultimo", "todos"] = "todos"


class CategoriaDoc(BaseModel):
    nome: str                               # "Relação Bancária"
    palavras_chave: list[str]               # ["RELAÇÃO BANCÁRIA", "transferência"]


class ClassificacaoDocumentoConfig(BaseModel):
    """Classifica documentos do lançamento por categorias do usuário."""
    categorias: list[CategoriaDoc]


class ConferenciaConteudoConfig(BaseModel):
    """Localiza campo X no documento Y e compara com referência Z."""
    campo: str                              # "valor", "competência", "favorecido", "CNPJ", texto livre
    buscar_em: str                          # "comprovante", "nota_fiscal", ou nome de categoria
    buscar_mime_types: list[str] = []       # ["image/jpeg"] — restringe tipo de doc
    comparar_com: str = ""                  # "lancamento.valor", "lancamento.historico", "periodo.mes_ano"
    instrucao_busca: str = ""               # Dica extra para a IA
    tipo_comparacao: Literal["igualdade", "contem", "numerico"] = "igualdade"
    tolerancia: float = 0.01
    posicao: Literal["primeiro", "ultimo", "todos"] = "todos"


class ConsistenciaHistoricoConfig(BaseModel):
    """Verifica que todos os históricos contêm o mesmo valor extraído por regex."""
    campo_descricao: str = "competência"    # Nome legível do campo verificado
    padrao_regex: str = r"(\d{1,2}/\d{4})" # Regex com grupo de captura


class ConferenciaSomaConfig(BaseModel):
    """Soma valores de todos os lançamentos e compara com valor encontrado em documento-guia.

    Uso: encargos sociais onde N lançamentos (GPS, INSS, IRRF...) somam ao valor de 1 DARF/guia.
    """
    campo: str = "valor total"              # O que pedir à IA para encontrar no documento
    buscar_em: str                          # Keywords do documento-guia: "DARF", "guia", "GPS"
    instrucao_busca: str = ""               # Dica extra para a IA
    tolerancia: float = 0.01


class DuplicidadeValorConfig(BaseModel):
    """Detecta lançamentos com valores iguais (possível duplicidade de pagamento).

    Agrupa lançamentos por valor e marca pares/grupos com mesmo valor como DIVERGENCIA.
    """
    tolerancia: float = 0.01               # Tolerância para considerar valores iguais
    campos_extras: list[str] = []          # Campos adicionais para comparar: ["data", "nome_sub_conta"]


# Mapa tipo → config class
CRITERION_CONFIG_MAP: dict[str, type[BaseModel]] = {
    "presenca_documento": PresencaDocumentoConfig,
    "classificacao_documento": ClassificacaoDocumentoConfig,
    "conferencia_conteudo": ConferenciaConteudoConfig,
    "consistencia_historico": ConsistenciaHistoricoConfig,
    "conferencia_soma": ConferenciaSomaConfig,
    "duplicidade_valor": DuplicidadeValorConfig,
}


# ── Resultado padronizado ─────────────────────────────────────────────


class CriterionResult(BaseModel):
    lancamento: str
    criterio_nome: str
    criterio_tipo: str
    documento_tipo: str = ""
    resultado: Literal["APROVADO", "DIVERGENCIA", "ITEM_AUSENTE"]
    detalhes: str = ""
    valores: dict = Field(default_factory=dict)
    # Dados do lançamento para referência direta no frontend
    lancamento_info: dict = Field(default_factory=dict)
    # Ex: {historico, valor, data, nome_conta, nome_sub_conta}


class CriterionGroupResult(BaseModel):
    """Resultados agrupados de um único critério."""
    criterio_nome: str
    criterio_tipo: str
    total: int = 0
    aprovados: int = 0
    divergencias: int = 0
    ausentes: int = 0
    itens: list[CriterionResult] = Field(default_factory=list)


class CriteriaExecutionResult(BaseModel):
    grupos: list[CriterionGroupResult] = Field(default_factory=list)
    resumo: dict = Field(default_factory=dict)


# ── DTOs de API ───────────────────────────────────────────────────────


class CriterionSyncItem(BaseModel):
    nome: str = Field(max_length=200)
    tipo: str = Field(max_length=50)
    config_json: str = "{}"
    is_active: bool = True


class CriteriaSyncRequest(BaseModel):
    criteria: list[CriterionSyncItem] = []


class CriterionResponse(BaseModel):
    id: int
    order: int
    nome: str
    tipo: str
    config_json: str
    is_active: bool

    model_config = {"from_attributes": True}
