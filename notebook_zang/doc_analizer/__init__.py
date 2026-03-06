"""
doc_analyzer — Sistema de análise inteligente de documentos condominiais.

Módulos:
    config          - Tipos de documentos e campos de extração
    classifier      - Classificação automática de documentos
    pdf_extractor   - Extração de texto e tabelas de PDFs
    bridge          - Ponte de integração com conferencia_service (bytes em memória)
"""

from .config import DOCUMENT_TYPES, CLASSIFICACAO_PRIORIDADE
from .classifier import classificar_documento, classificar_por_metadados
from .pdf_extractor import extrair_texto_pdf, extrair_texto_pdf_bytes
from .bridge import (
    classificar_documento_bytes,
    gerar_dica_tipo_documento,
    gerar_checklist_lancamento,
    enriquecer_lancamento,
)
