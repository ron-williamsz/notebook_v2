"""
Utilitário para extração de texto de PDFs.
Usa pdfplumber como principal e pypdf como fallback.
Suporta tanto caminhos de arquivo quanto bytes em memória.
"""

import io
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


def extrair_texto_pdf(caminho_pdf: str, max_paginas: int = 5) -> str:
    """
    Extrai texto de um PDF. Tenta pdfplumber primeiro, depois pypdf.
    
    Args:
        caminho_pdf: Caminho completo do arquivo PDF
        max_paginas: Máximo de páginas a extrair (padrão: 5)
        
    Returns:
        Texto extraído concatenado
    """
    if not os.path.exists(caminho_pdf):
        raise FileNotFoundError(f"PDF não encontrado: {caminho_pdf}")

    texto = _extrair_pdfplumber(caminho_pdf, max_paginas)
    
    if not texto or len(texto.strip()) < 50:
        texto = _extrair_pypdf(caminho_pdf, max_paginas)

    if not texto or len(texto.strip()) < 50:
        texto = _extrair_pdftotext(caminho_pdf, max_paginas)

    return texto or ""


def _extrair_pdfplumber(caminho: str, max_pag: int) -> Optional[str]:
    try:
        import pdfplumber
        textos = []
        with pdfplumber.open(caminho) as pdf:
            for i, page in enumerate(pdf.pages[:max_pag]):
                t = page.extract_text()
                if t:
                    textos.append(t)
        return "\n\n".join(textos)
    except Exception as e:
        print(f"[pdfplumber] Erro: {e}")
        return None


def _extrair_pypdf(caminho: str, max_pag: int) -> Optional[str]:
    try:
        from pypdf import PdfReader
        reader = PdfReader(caminho)
        textos = []
        for page in reader.pages[:max_pag]:
            t = page.extract_text()
            if t:
                textos.append(t)
        return "\n\n".join(textos)
    except Exception as e:
        print(f"[pypdf] Erro: {e}")
        return None


def _extrair_pdftotext(caminho: str, max_pag: int) -> Optional[str]:
    try:
        import subprocess
        result = subprocess.run(
            ["pdftotext", "-layout", "-l", str(max_pag), caminho, "-"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            return result.stdout
    except Exception as e:
        print(f"[pdftotext] Erro: {e}")
    return None


def extrair_texto_pdf_bytes(pdf_bytes: bytes, max_paginas: int = 3) -> str:
    """
    Extrai texto de um PDF a partir de bytes em memória.
    Versão leve para classificação (menos páginas por padrão).

    Args:
        pdf_bytes: Conteúdo do PDF em bytes
        max_paginas: Máximo de páginas a extrair (padrão: 3)

    Returns:
        Texto extraído concatenado
    """
    if not pdf_bytes or len(pdf_bytes) < 100:
        return ""

    texto = _extrair_pdfplumber_bytes(pdf_bytes, max_paginas)

    if not texto or len(texto.strip()) < 50:
        texto = _extrair_pypdf_bytes(pdf_bytes, max_paginas)

    return texto or ""


def _extrair_pdfplumber_bytes(pdf_bytes: bytes, max_pag: int) -> Optional[str]:
    try:
        import pdfplumber
        textos = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages[:max_pag]:
                t = page.extract_text()
                if t:
                    textos.append(t)
        return "\n\n".join(textos)
    except Exception as e:
        logger.debug("[pdfplumber-bytes] Erro: %s", e)
        return None


def _extrair_pypdf_bytes(pdf_bytes: bytes, max_pag: int) -> Optional[str]:
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(pdf_bytes))
        textos = []
        for page in reader.pages[:max_pag]:
            t = page.extract_text()
            if t:
                textos.append(t)
        return "\n\n".join(textos)
    except Exception as e:
        logger.debug("[pypdf-bytes] Erro: %s", e)
        return None


def extrair_tabelas_pdf(caminho_pdf: str) -> list:
    """Extrai tabelas estruturadas do PDF (útil para folha de pagamento e extratos)."""
    try:
        import pdfplumber
        tabelas = []
        with pdfplumber.open(caminho_pdf) as pdf:
            for i, page in enumerate(pdf.pages):
                page_tables = page.extract_tables()
                for j, table in enumerate(page_tables):
                    tabelas.append({
                        "pagina": i + 1,
                        "tabela_idx": j + 1,
                        "dados": table,
                    })
        return tabelas
    except Exception as e:
        print(f"[tabelas] Erro: {e}")
        return []
