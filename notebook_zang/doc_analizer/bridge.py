"""
Módulo ponte para integrar a classificação do doc_analizer no fluxo
de conferência (conferencia_service). Trabalha com bytes em memória
vindos do download da GoSati.
"""

import logging
from typing import Any

from .config import DOCUMENT_TYPES
from .classifier import classificar_documento, classificar_por_metadados
from .pdf_extractor import extrair_texto_pdf_bytes

logger = logging.getLogger(__name__)

# Confiança mínima para incluir dica no prompt do Gemini
CONFIANCA_MINIMA_DICA = 0.25


def classificar_documento_bytes(
    doc_bytes: bytes,
    mime_type: str,
    nome_arquivo: str = "",
    historico: str = "",
    nome_conta: str = "",
    nome_sub_conta: str = "",
) -> dict:
    """
    Classifica um documento a partir de bytes em memória.

    Para PDFs: extrai texto e classifica por keywords.
    Para imagens: usa metadados da despesa (historico, conta) como heurística.

    Returns:
        dict com tipo, nome_tipo, confianca, classificado_por, texto_extraido
    """
    texto_extraido = ""

    if mime_type == "application/pdf":
        try:
            texto_extraido = extrair_texto_pdf_bytes(doc_bytes, max_paginas=3)
        except Exception as e:
            logger.debug("Falha na extração de texto do PDF: %s", e)

    # Montar texto a partir dos metadados da despesa para heurística
    metadata_text = " ".join(filter(None, [historico, nome_conta, nome_sub_conta]))

    # Combinar texto extraído do PDF com metadados
    combined_text = (
        f"{texto_extraido}\n{metadata_text}" if texto_extraido else metadata_text
    )

    if not combined_text.strip():
        return {
            "tipo": "nao_identificado",
            "nome_tipo": "Não identificado",
            "confianca": 0.0,
            "classificado_por": "sem_dados",
            "texto_extraido": "",
        }

    classificacao = classificar_documento(combined_text, nome_arquivo)

    # Se confiança baixa e temos metadados, tentar regex como boost
    if classificacao["confianca"] < 0.4 and metadata_text.strip():
        tipo_meta = classificar_por_metadados(historico, nome_conta, nome_sub_conta)
        if tipo_meta and tipo_meta in DOCUMENT_TYPES:
            if classificacao["tipo"] != tipo_meta:
                classificacao["tipo"] = tipo_meta
                classificacao["nome_tipo"] = DOCUMENT_TYPES[tipo_meta]["nome"]
                classificacao["confianca"] = 0.5
                classificacao["classificado_por"] = "metadados_regex"

    classificacao["texto_extraido"] = texto_extraido[:500] if texto_extraido else ""
    return classificacao


def gerar_dica_tipo_documento(tipo: str) -> str:
    """
    Gera um snippet compacto de orientação por tipo de documento.

    Não é o prompt completo de extração — é uma dica concisa para
    injetar junto ao documento no prompt de conferência.
    """
    if tipo not in DOCUMENT_TYPES or tipo == "nao_identificado":
        return ""

    config = DOCUMENT_TYPES[tipo]

    campos_chave = list(config["campos_grifados"].keys())
    campos_str = ", ".join(campos_chave)

    verificacoes = config.get("verificacoes", [])
    verificacoes_str = "\n".join(f"  - {v}" for v in verificacoes)

    return (
        f"**Tipo identificado**: {config['nome']}\n"
        f"**Campos criticos a verificar**: {campos_str}\n"
        f"**Verificacoes especificas**:\n{verificacoes_str}"
    )


def enriquecer_lancamento(
    documentos: list[tuple[bytes, str]],
    despesa: dict[str, Any],
) -> dict[str, Any]:
    """
    Classifica todos os documentos de um lançamento e produz
    dados de enriquecimento para o prompt do Gemini.

    Args:
        documentos: Lista de (doc_bytes, mime_type) do lançamento
        despesa: Dict com metadados da despesa (historico, nome_conta, etc.)

    Returns:
        {
            "classificacoes": [{"page": int, "tipo": str, "nome_tipo": str, "confianca": float}],
            "dica_consolidada": str,
            "tipos_encontrados": list[str],
        }
    """
    classificacoes = []
    tipos_encontrados: set[str] = set()

    historico = despesa.get("historico", "")
    nome_conta = despesa.get("nome_conta", "")
    nome_sub_conta = despesa.get("nome_sub_conta", "")

    for idx, (doc_bytes, mime_type) in enumerate(documentos):
        try:
            classif = classificar_documento_bytes(
                doc_bytes,
                mime_type,
                historico=historico,
                nome_conta=nome_conta,
                nome_sub_conta=nome_sub_conta,
            )
        except Exception as e:
            logger.debug("Erro classificando página %d: %s", idx + 1, e)
            classif = {
                "tipo": "nao_identificado",
                "nome_tipo": "Não identificado",
                "confianca": 0.0,
            }

        classificacoes.append({
            "page": idx + 1,
            "tipo": classif["tipo"],
            "nome_tipo": classif.get("nome_tipo", ""),
            "confianca": classif.get("confianca", 0),
        })

        if (
            classif["tipo"] != "nao_identificado"
            and classif.get("confianca", 0) >= CONFIANCA_MINIMA_DICA
        ):
            tipos_encontrados.add(classif["tipo"])

    # Gerar dica consolidada para todos os tipos encontrados
    dicas = []
    for tipo in sorted(tipos_encontrados):
        dica = gerar_dica_tipo_documento(tipo)
        if dica:
            dicas.append(dica)

    dica_consolidada = "\n\n".join(dicas) if dicas else ""

    return {
        "classificacoes": classificacoes,
        "dica_consolidada": dica_consolidada,
        "tipos_encontrados": sorted(tipos_encontrados),
    }


def gerar_checklist_lancamento(
    despesa: dict, tipos_encontrados: list[str]
) -> str:
    """Gera checklist explícito de verificações para um lançamento.

    Baseado nos tipos de documento identificados, força o Gemini a
    responder item a item — não pode pular nenhuma verificação.
    """
    if not tipos_encontrados:
        return ""

    linhas = ["**CHECKLIST DE VERIFICACAO OBRIGATORIA:**"]
    linhas.append("Responda CADA item com OK / PENDENCIA / DIVERGENCIA:\n")

    # Regras gerais (sempre presentes)
    linhas.append("_Regras gerais:_")
    linhas.append("[ ] Possui documento comprobatorio?")
    linhas.append("[ ] Historico contem numero da NF (se aplicavel)?")
    linhas.append("[ ] Valor do comprovante confere com valor do lancamento?")
    linhas.append("[ ] Beneficiario/favorecido confere com emissor?")

    # Regras específicas por tipo encontrado
    for tipo in tipos_encontrados:
        if tipo not in DOCUMENT_TYPES:
            continue
        config = DOCUMENT_TYPES[tipo]
        verificacoes = config.get("verificacoes", [])
        if verificacoes:
            linhas.append(f"\n_Verificacoes {config['nome']}:_")
            for v in verificacoes:
                linhas.append(f"[ ] {v}")

    return "\n".join(linhas)
