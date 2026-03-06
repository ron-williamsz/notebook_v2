"""
Classificador de documentos condominiais.
Combina análise por nome de arquivo + conteúdo textual + heurísticas.
"""

import re
import unicodedata
from typing import Optional, Tuple
from .config import DOCUMENT_TYPES, CLASSIFICACAO_PRIORIDADE


# ============================================================================
# CLASSIFICAÇÃO POR REGEX NOS METADADOS DA DESPESA (para imagens sem texto)
# ============================================================================

MAPEAMENTO_HISTORICO = [
    (re.compile(r"DARF|RECEITA FEDERAL", re.I), "darf"),
    (re.compile(r"FGTS|CAIXA ECONOMICA|SEFIP|GFD", re.I), "guia_fgts"),
    (re.compile(r"GPS\s*[-/]|INSS\s*[-/]|INSS\s+EMPRESA|PREVIDENCIA", re.I), "gps"),
    (re.compile(r"ISS\s*[-/]|DAMSP", re.I), "damsp"),
    (re.compile(r"NFE?\s*\d|NF[\s.:]+\d|NOTA\s+FISCAL", re.I), "nota_fiscal_sp"),
    (re.compile(r"NFTS|NOTA.*TOMADOR", re.I), "modelo_nfts"),
    (re.compile(r"SABESP|AGUA\s+E?\s*ESGOTO|CONSUMO\s+DE?\s*AGUA", re.I), "fatura_sabesp"),
    (re.compile(r"ENEL|ELETROPAULO|ENERGIA\s+ELETRICA|CONSUMO\s+ENERGIA", re.I), "fatura_enel"),
    (re.compile(r"FOLHA|SALARIO|ADIANTAMENTO\s+(?:QUINZ|SALAR)", re.I), "folha_pagamento"),
    (re.compile(r"RELACAO\s+BANCARIA", re.I), "relacao_bancaria"),
    (re.compile(r"SINDIF|CONTRIB.*ASSISTENCIAL|TAXA\s+SINDICAL", re.I), "sindificios"),
    (re.compile(r"COPIA|IMPRESSAO|REPROGRAFIA|XEROX", re.I), "despesa_copias"),
]


def _remover_acentos(texto: str) -> str:
    """Remove acentos mantendo caracteres base (é→e, ã→a, ç→c)."""
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalizar(texto: str) -> str:
    return re.sub(r'\s+', ' ', _remover_acentos(texto).lower().strip())


def calcular_score(texto: str, doc_config: dict) -> float:
    """Score de 0 a 1 baseado em keywords encontradas no texto."""
    texto_norm = normalizar(texto)
    score = 0.0

    # Keywords de alta confiança valem mais
    for kw in doc_config.get("keywords_alta", []):
        if _remover_acentos(kw).lower() in texto_norm:
            score += 3.0

    # Keywords médias
    for kw in doc_config.get("keywords_media", []):
        if _remover_acentos(kw).lower() in texto_norm:
            score += 1.0

    # Penalizar se keywords negativos encontrados
    for kw in doc_config.get("keywords_negativos", []):
        if _remover_acentos(kw).lower() in texto_norm:
            score -= 5.0

    return score


def classificar_por_nome(nome_arquivo: str) -> Optional[str]:
    """Classificação rápida pelo nome do arquivo (padrão: 'N Tipo.pdf')."""
    nome = nome_arquivo.lower()
    mapa = {
        "sabesp": "fatura_sabesp",
        "enel": "fatura_enel",
        "eletropaulo": "fatura_enel",
        "nota fiscal sp": "nota_fiscal_sp",
        "nota fiscal - fora": "nota_fiscal_fora_sp",
        "nfts": "modelo_nfts",
        "despesa com cópia": "despesa_copias",
        "despesa com copia": "despesa_copias",
        "modelo analitico": "folha_analitica",
        "modelo analítico": "folha_analitica",
        "analitico": "folha_analitica",
        "analítico": "folha_analitica",
        "relação bancária": "relacao_bancaria",
        "relacao bancaria": "relacao_bancaria",
        "folha de pagamento": "folha_pagamento",
        "13o salario": "folha_pagamento",
        "holerite": "folha_pagamento",
        "balancete": "balancete",
        "prestação de contas": "balancete",
        "prestacao de contas": "balancete",
    }
    for chave, tipo in mapa.items():
        if chave in nome:
            return tipo
    return None


def classificar_documento(
    texto: str,
    nome_arquivo: str = "",
    threshold_confianca: float = 0.3
) -> dict:
    """
    Classifica documento. Retorna dict com tipo, confiança e detalhes.
    
    Args:
        texto: Texto extraído do PDF (primeiras ~3 páginas)
        nome_arquivo: Nome original do arquivo
        threshold_confianca: Mínimo para considerar classificação válida
        
    Returns:
        {
            "tipo": str,
            "nome_tipo": str,
            "confianca": float,
            "classificado_por": str,  # "nome_arquivo" | "conteudo" | "fallback_llm"
            "scores": dict,
            "requer_llm": bool,
        }
    """
    scores = {}
    for tipo_id in CLASSIFICACAO_PRIORIDADE:
        scores[tipo_id] = calcular_score(texto, DOCUMENT_TYPES[tipo_id])

    # Melhor match por conteúdo
    melhor_tipo = max(scores, key=scores.get)
    melhor_score = scores[melhor_tipo]

    # Match por nome do arquivo
    tipo_nome = classificar_por_nome(nome_arquivo) if nome_arquivo else None

    # Normalizar scores contra o score máximo teórico do tipo
    score_maximo_tipo = DOCUMENT_TYPES[melhor_tipo].get("score_maximo", 1.0)
    confianca = (
        min(1.0, max(0.0, melhor_score / score_maximo_tipo))
        if score_maximo_tipo > 0
        else 0.0
    )

    # Se nome e conteúdo concordam, alta confiança
    classificado_por = "conteudo"
    if tipo_nome:
        if tipo_nome == melhor_tipo:
            confianca = min(1.0, confianca + 0.3)
            classificado_por = "nome_arquivo+conteudo"
        elif scores.get(tipo_nome, 0) > 0:
            melhor_tipo = tipo_nome
            confianca = 0.6
            classificado_por = "nome_arquivo"
        else:
            # Nome sugere um tipo, conteúdo outro — sinal de dúvida
            classificado_por = "conflito"
            confianca *= 0.5

    requer_llm = confianca < threshold_confianca

    return {
        "tipo": melhor_tipo,
        "nome_tipo": DOCUMENT_TYPES[melhor_tipo]["nome"],
        "confianca": round(confianca, 3),
        "classificado_por": classificado_por,
        "scores": {k: round(v, 2) for k, v in sorted(scores.items(), key=lambda x: -x[1])},
        "requer_llm": requer_llm,
    }


def prompt_classificacao_llm(texto_amostra: str) -> str:
    """
    Gera prompt para a LLM classificar quando a heurística não tem confiança.
    Enviar para Vertex/NotebookLM quando requer_llm=True.
    """
    tipos = "\n".join([
        f"  - `{tid}`: {DOCUMENT_TYPES[tid]['nome']}"
        for tid in CLASSIFICACAO_PRIORIDADE
    ])

    return f"""Classifique o documento abaixo em um dos tipos de documentos condominiais.

Tipos disponíveis:
{tipos}

Texto extraído do documento (primeiros 2000 caracteres):
---
{texto_amostra[:2000]}
---

Responda APENAS com o identificador do tipo, exemplo: fatura_sabesp
Se não identificar, responda: nao_identificado"""


def classificar_por_metadados(
    historico: str, nome_conta: str = "", nome_sub_conta: str = ""
) -> Optional[str]:
    """Classificação rápida por regex nos metadados da despesa GoSATI.

    Útil quando o comprovante é imagem (sem texto extraível) e a
    classificação por keywords tem confiança baixa.
    """
    texto = f"{historico} {nome_conta} {nome_sub_conta}"
    for padrao, tipo in MAPEAMENTO_HISTORICO:
        if padrao.search(texto):
            return tipo
    return None
