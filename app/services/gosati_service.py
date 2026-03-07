"""Cliente SOAP para GoSATI / Zangari — consultas financeiras de condomínios."""

import gzip
import json
import logging
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import BASE_DIR, Settings
from app.core.exceptions import NotFoundError
from app.models.session import Session
from app.models.source import Source
from app.services.document_converter import extract_text_from_pdf

logger = logging.getLogger(__name__)

GOSATI_DIR = BASE_DIR / "data" / "gosati"

# Cache em memória da prestação de contas (evita refazer SOAP para listar comprovantes)
_prestacao_cache: dict[str, dict] = {}


def clear_prestacao_cache(key: str | None = None) -> None:
    """Limpa cache de prestação de contas.

    Se key fornecida (ex: '386_1_2026'), remove apenas essa entrada.
    Se None, limpa tudo.
    """
    if key:
        _prestacao_cache.pop(key, None)
    else:
        _prestacao_cache.clear()


class GoSatiError(Exception):
    """Raised when GoSati API returns an error."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_zangari_senha_from_env() -> str | None:
    """Lê ZANGARI_SENHA direto do .env (pydantic-settings trata # como comentário)."""
    env_path = Path(".env")
    if not env_path.exists():
        return None
    with open(env_path, "r") as f:
        for line in f:
            if line.startswith("ZANGARI_SENHA="):
                value = line.split("=", 1)[1].strip()
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                elif value.startswith("'") and value.endswith("'"):
                    value = value[1:-1]
                return value
    return None


def _xml_to_dict(element: ET.Element) -> dict | str | None:
    """Converte elemento XML em dicionário recursivamente."""
    result = {}

    if element.attrib:
        result["@attributes"] = dict(element.attrib)

    if element.text and element.text.strip():
        if len(element) == 0:
            return element.text.strip()
        result["#text"] = element.text.strip()

    children: dict = {}
    for child in element:
        child_data = _xml_to_dict(child)
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag

        if tag in children:
            if not isinstance(children[tag], list):
                children[tag] = [children[tag]]
            children[tag].append(child_data)
        else:
            children[tag] = child_data

    if children:
        result.update(children)

    return result if result else None


def _dict_to_text(data: dict, label: str) -> str:
    """Formata resposta GoSati como texto legível para o Gemini."""
    return f"=== {label} ===\n\n{json.dumps(data, ensure_ascii=False, indent=2)}"


_COMPRESSIBLE_IMAGES = frozenset(
    {"image/jpeg", "image/png", "image/bmp", "image/webp", "image/tiff", "image/gif"}
)
_MAX_IMAGE_KB = 120  # comprime imagens acima desse tamanho


def _compress_image(data: bytes, mime_type: str) -> tuple[bytes, str]:
    """Comprime imagem para reduzir payload ao Gemini.

    Converte para JPEG (quality=75, max 1600px) se resultar em arquivo menor.
    Retorna (bytes, mime_type) — pode mudar o mime para image/jpeg.
    """
    if mime_type not in _COMPRESSIBLE_IMAGES or len(data) <= _MAX_IMAGE_KB * 1024:
        return data, mime_type
    try:
        import io
        from PIL import Image

        img = Image.open(io.BytesIO(data))
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        max_dim = 800
        if max(img.size) > max_dim:
            img.thumbnail((max_dim, max_dim), Image.LANCZOS)
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=75, optimize=True)
        compressed = out.getvalue()
        if len(compressed) < len(data):
            logger.debug(
                "Imagem comprimida %s: %d KB → %d KB",
                mime_type, len(data) // 1024, len(compressed) // 1024,
            )
            return compressed, "image/jpeg"
    except Exception as e:
        logger.debug("Falha ao comprimir imagem (%s): %s", mime_type, e)
    return data, mime_type


def _is_binary_garbage(text: str, max_non_print_ratio: float = 0.15) -> bool:
    """Retorna True se o texto extraído contém lixo binário/nulo.

    Filtra PDFs escaneados onde pdfplumber extrai bytes nulos ou caracteres
    não-imprimíveis em vez de texto legível.
    """
    if not text:
        return True
    stripped = text.strip()
    if not stripped:
        return True
    total = len(stripped)
    # Nulos explícitos (bytes \x00)
    if stripped.count("\x00") > total * 0.05:
        return True
    # Excesso de não-imprimíveis (exceto espaço/tab/newline)
    non_print = sum(1 for c in stripped if ord(c) < 32 and c not in "\n\r\t ")
    if non_print / total > max_non_print_ratio:
        return True
    # Texto com conteúdo mínimo legível (pelo menos 10 caracteres não-espaço)
    meaningful = sum(1 for c in stripped if c not in " \n\r\t")
    if meaningful < 10:
        return True
    return False


def _detect_mime_type(data: bytes) -> str | None:
    """Detecta mime type a partir dos magic bytes."""
    if len(data) < 10:
        return None
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"\x89PNG":
        return "image/png"
    if data[:3] == b"GIF":
        return "image/gif"
    if data[:2] == b"BM":
        return "image/bmp"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:5] == b"%PDF-":
        return "application/pdf"
    if data[:4] in (b"II\x2a\x00", b"MM\x00\x2a"):
        return "image/tiff"
    return None


GOSATI_QUERY_LABELS = {
    "prestacao_contas": "Prestação de Contas",
    "fluxo_caixa": "Fluxo de Caixa",
    "inadimplencia": "Inadimplência",
    "periodo_fechamento": "Período de Fechamento",
    "previsao_orcamentaria": "Previsão Orçamentária",
    "relacao_lancamentos": "Relação de Lançamentos",
    "relacao_pendentes": "Relação de Pendentes",
}


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class GoSatiService:
    def __init__(self, db: AsyncSession, settings: Settings):
        self.db = db
        self.settings = settings
        self._senha: str | None = None

    def _get_senha(self) -> str:
        if self._senha is None:
            self._senha = _read_zangari_senha_from_env() or self.settings.zangari_senha
        return self._senha

    def _auth_params(self) -> str:
        return (
            f"<usuario>{self.settings.zangari_usuario}</usuario>\n"
            f"      <senha>{self._get_senha()}</senha>\n"
            f"      <chave>{self.settings.zangari_chave}</chave>"
        )

    # ------------------------------------------------------------------
    # SOAP transport
    # ------------------------------------------------------------------

    async def _send_soap_request(self, action: str, body: str) -> str:
        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": f'"http://gosati.com.br/webservices/{action}"',
            "User-Agent": "NotebookZang SOAP Client",
            "Accept-Encoding": "gzip, deflate",
        }
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    self.settings.zangari_url, content=body, headers=headers
                )
        except httpx.ConnectError as e:
            raise GoSatiError(f"Não foi possível conectar ao servidor GoSati: {e}")
        except httpx.TimeoutException:
            raise GoSatiError("Timeout ao conectar ao servidor GoSati (60s)")

        content_encoding = response.headers.get("Content-Encoding", "").lower()
        if content_encoding == "gzip" or response.content[:2] == b"\x1f\x8b":
            try:
                return gzip.decompress(response.content).decode("utf-8")
            except Exception:
                return response.text
        return response.text

    def _parse_soap_response(self, xml_text: str, result_tag: str) -> dict | None:
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            raise GoSatiError(f"Erro ao processar XML da resposta: {e}")

        # Strip namespaces
        for elem in root.iter():
            if "}" in elem.tag:
                elem.tag = elem.tag.split("}")[1]

        # Check for SOAP fault
        for fault in root.iter("Fault"):
            faultstring = ""
            for fs in fault.iter("faultstring"):
                faultstring = fs.text or ""
            msg = faultstring
            if "--->" in msg:
                inner = msg.split("--->")[-1].strip()
                for sep in ["\n", "   em ", "   at "]:
                    if sep in inner:
                        inner = inner.split(sep)[0].strip()
                msg = inner
            if ": " in msg and msg.split(": ", 1)[0].replace(".", "").isalpha():
                msg = msg.split(": ", 1)[1]
            raise GoSatiError(msg)

        # Find result element
        for body in root.iter("Body"):
            for child in body:
                if (result_tag + "Response") in child.tag:
                    for grandchild in child:
                        if (result_tag + "Result") in grandchild.tag:
                            return _xml_to_dict(grandchild)
        return None

    # ------------------------------------------------------------------
    # 7 query methods
    # ------------------------------------------------------------------

    async def consultar_prestacao_contas(
        self,
        condominio: int,
        mes: int | None = None,
        ano: int | None = None,
        demonstr_contas: bool = True,
        demonstr_despesas: bool = True,
        relat_devedores: bool = True,
        demonstr_receitas: bool = True,
        acompanh_cobranca: bool = True,
        orcado_gasto: bool = True,
    ) -> dict | None:
        if not mes:
            mes = date.today().month
        if not ano:
            ano = date.today().year

        data_inicial = f"{ano}-{mes:02d}-01"
        if mes == 12:
            ultimo_dia = date(ano + 1, 1, 1) - timedelta(days=1)
        else:
            ultimo_dia = date(ano, mes + 1, 1) - timedelta(days=1)
        data_final = ultimo_dia.strftime("%Y-%m-%d")
        data_contas = data_final

        soap_body = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:xsd="http://www.w3.org/2001/XMLSchema"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <PrestacaoContas xmlns="http://gosati.com.br/webservices/">
      <Condominio>{condominio}</Condominio>
      <Bloco_Ini></Bloco_Ini>
      <Bloco_Fin>ZZ</Bloco_Fin>
      <Data_Inicial>{data_inicial}T00:00:00</Data_Inicial>
      <Data_Final>{data_final}T23:59:59</Data_Final>
      <Mes>{mes}</Mes>
      <Ano>{ano}</Ano>
      <Data_Contas>{data_contas}T00:00:00</Data_Contas>
      <Demonstr_Contas>{str(demonstr_contas).lower()}</Demonstr_Contas>
      <Demonstr_Despesas>{str(demonstr_despesas).lower()}</Demonstr_Despesas>
      <Relat_Devedores>{str(relat_devedores).lower()}</Relat_Devedores>
      <Demonstr_Receitas>{str(demonstr_receitas).lower()}</Demonstr_Receitas>
      <Acompanh_Cobranca>{str(acompanh_cobranca).lower()}</Acompanh_Cobranca>
      <Orcado_gasto>{str(orcado_gasto).lower()}</Orcado_gasto>
      {self._auth_params()}
    </PrestacaoContas>
  </soap:Body>
</soap:Envelope>"""

        xml_text = await self._send_soap_request("PrestacaoContas", soap_body)
        return self._parse_soap_response(xml_text, "PrestacaoContas")

    async def consultar_fluxo_caixa(
        self, condominio: int, mes: int | None = None, ano: int | None = None
    ) -> dict | None:
        if not mes:
            mes = date.today().month
        if not ano:
            ano = date.today().year

        data_inicial = f"{ano}-{mes:02d}-01"
        if mes == 12:
            ultimo_dia = date(ano + 1, 1, 1) - timedelta(days=1)
        else:
            ultimo_dia = date(ano, mes + 1, 1) - timedelta(days=1)
        data_final = ultimo_dia.strftime("%Y-%m-%d")

        soap_body = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:xsd="http://www.w3.org/2001/XMLSchema"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <FluxoCaixa xmlns="http://gosati.com.br/webservices/">
      <Condominio>{condominio}</Condominio>
      <Data_Inicial>{data_inicial}T00:00:00</Data_Inicial>
      <Data_Final>{data_final}T23:59:59</Data_Final>
      {self._auth_params()}
    </FluxoCaixa>
  </soap:Body>
</soap:Envelope>"""

        xml_text = await self._send_soap_request("FluxoCaixa", soap_body)
        return self._parse_soap_response(xml_text, "FluxoCaixa")

    async def consultar_inadimplencia(self, condominio: int) -> dict | None:
        soap_body = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:xsd="http://www.w3.org/2001/XMLSchema"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <ConsultaInadimplenciaUnidade xmlns="http://gosati.com.br/webservices/">
      <Condominio>{condominio}</Condominio>
      {self._auth_params()}
    </ConsultaInadimplenciaUnidade>
  </soap:Body>
</soap:Envelope>"""

        xml_text = await self._send_soap_request("ConsultaInadimplenciaUnidade", soap_body)
        return self._parse_soap_response(xml_text, "ConsultaInadimplenciaUnidade")

    async def consultar_periodo_fechamento(
        self, condominio: int, ano: int | None = None
    ) -> dict | None:
        if not ano:
            ano = date.today().year

        soap_body = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:xsd="http://www.w3.org/2001/XMLSchema"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <PeriodoFechamento xmlns="http://gosati.com.br/webservices/">
      <Condominio>{condominio}</Condominio>
      <Ano>{ano}</Ano>
      {self._auth_params()}
    </PeriodoFechamento>
  </soap:Body>
</soap:Envelope>"""

        xml_text = await self._send_soap_request("PeriodoFechamento", soap_body)
        return self._parse_soap_response(xml_text, "PeriodoFechamento")

    async def consultar_previsao_orcamentaria(
        self, condominio: int, mes: int | None = None, ano: int | None = None
    ) -> dict | None:
        if not mes:
            mes = date.today().month
        if not ano:
            ano = date.today().year

        soap_body = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:xsd="http://www.w3.org/2001/XMLSchema"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <PrevisaoOrcamentaria xmlns="http://gosati.com.br/webservices/">
      <Condominio>{condominio}</Condominio>
      <Mes>{mes}</Mes>
      <Ano>{ano}</Ano>
      {self._auth_params()}
    </PrevisaoOrcamentaria>
  </soap:Body>
</soap:Envelope>"""

        xml_text = await self._send_soap_request("PrevisaoOrcamentaria", soap_body)
        return self._parse_soap_response(xml_text, "PrevisaoOrcamentaria")

    async def consultar_relacao_lancamentos(
        self, condominio: int, mes: int | None = None, ano: int | None = None
    ) -> dict | None:
        if not mes:
            mes = date.today().month
        if not ano:
            ano = date.today().year

        data_inicial = f"{ano}-{mes:02d}-01"
        if mes == 12:
            ultimo_dia = date(ano + 1, 1, 1) - timedelta(days=1)
        else:
            ultimo_dia = date(ano, mes + 1, 1) - timedelta(days=1)
        data_final = ultimo_dia.strftime("%Y-%m-%d")

        soap_body = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:xsd="http://www.w3.org/2001/XMLSchema"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <RelacaoLancamento xmlns="http://gosati.com.br/webservices/">
      <Condominio>{condominio}</Condominio>
      <DataInicial>{data_inicial}T00:00:00</DataInicial>
      <DataFinal>{data_final}T23:59:59</DataFinal>
      <Mes>{mes}</Mes>
      <Ano>{ano}</Ano>
      {self._auth_params()}
    </RelacaoLancamento>
  </soap:Body>
</soap:Envelope>"""

        xml_text = await self._send_soap_request("RelacaoLancamento", soap_body)
        return self._parse_soap_response(xml_text, "RelacaoLancamento")

    async def consultar_relacao_pendentes(
        self, condominio: int, ano: int | None = None
    ) -> dict | None:
        if not ano:
            ano = date.today().year

        soap_body = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:xsd="http://www.w3.org/2001/XMLSchema"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <RelacaoPendentes xmlns="http://gosati.com.br/webservices/">
      <Condominio>{condominio}</Condominio>
      <Bloco></Bloco>
      <Unidade></Unidade>
      <Vencimento_Inicial>{ano}-01-01T00:00:00</Vencimento_Inicial>
      <Vencimento_Final>{ano}-12-31T23:59:59</Vencimento_Final>
      <Data_Posicao>{ano}-12-31T00:00:00</Data_Posicao>
      <Atualizacao_Monetaria>false</Atualizacao_Monetaria>
      <Data_Calculo>{ano}-12-31T00:00:00</Data_Calculo>
      {self._auth_params()}
    </RelacaoPendentes>
  </soap:Body>
</soap:Envelope>"""

        xml_text = await self._send_soap_request("RelacaoPendentes", soap_body)
        return self._parse_soap_response(xml_text, "RelacaoPendentes")

    # ------------------------------------------------------------------
    # Comprovantes (receipt images)
    # ------------------------------------------------------------------

    def extrair_despesas_com_comprovante(self, prestacao_data: dict) -> list[dict]:
        """Extrai despesas que possuem comprovante (tem_docto=1 e catalogo_id)."""
        despesas = []
        try:
            diffgram = prestacao_data.get("diffgram", {})
            prestacao = diffgram.get("PrestacaoContas", {})
            raw_despesas = prestacao.get("Despesas", [])
            if not isinstance(raw_despesas, list):
                raw_despesas = [raw_despesas]

            for d in raw_despesas:
                if not isinstance(d, dict):
                    continue
                tem_docto = d.get("tem_docto", "0")
                catalogo_id = d.get("catalogo_id", "")
                if tem_docto == "1" and catalogo_id:
                    despesas.append({
                        "numero_lancamento": d.get("numero_lancamento", ""),
                        "historico": d.get("historico", ""),
                        "valor": d.get("valor", "0"),
                        "data": d.get("data", ""),
                        "nome_conta": d.get("nome_conta", ""),
                        "nome_conta_despesas": d.get("nome_conta_despesas", ""),
                        "nome_sub_conta": d.get("nome_sub_conta", ""),
                        "link_docto": d.get("link_docto", ""),
                        "catalogo_id": catalogo_id,
                    })
        except (KeyError, TypeError):
            pass
        return despesas

    # ------------------------------------------------------------------
    # Download via SOAP: RetornaDadosDoctos_Json + RetornaArquivo
    # ------------------------------------------------------------------

    async def listar_documentos_catalogo(self, catalogo_id: str) -> list[dict]:
        """Lista documentos de um catálogo via RetornaDadosDoctos_Json.

        Retorna lista de dicts: {id_do_catalogo, id_do_documento, extensao_docto, ...}
        """
        soap_body = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:xsd="http://www.w3.org/2001/XMLSchema"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <RetornaDadosDoctos_Json xmlns="http://gosati.com.br/webservices/">
      <Ids_Catalogos>{catalogo_id}</Ids_Catalogos>
      {self._auth_params()}
    </RetornaDadosDoctos_Json>
  </soap:Body>
</soap:Envelope>"""
        xml_text = await self._send_soap_request("RetornaDadosDoctos_Json", soap_body)
        root = ET.fromstring(xml_text)
        for elem in root.iter():
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if "Result" in tag and elem.text:
                data = json.loads(elem.text)
                return data.get("Dados", [])
        return []

    async def baixar_documento(self, catalogo_id: str, documento_id: str, extensao: str) -> bytes | None:
        """Baixa um documento via RetornaArquivo (retorna base64 decodificado)."""
        import base64
        soap_body = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:xsd="http://www.w3.org/2001/XMLSchema"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <RetornaArquivo xmlns="http://gosati.com.br/webservices/">
      <Id_Catalogo>{catalogo_id}</Id_Catalogo>
      <Id_Documento>{documento_id}</Id_Documento>
      <Extensao>{extensao}</Extensao>
      {self._auth_params()}
    </RetornaArquivo>
  </soap:Body>
</soap:Envelope>"""
        xml_text = await self._send_soap_request("RetornaArquivo", soap_body)
        root = ET.fromstring(xml_text)
        for elem in root.iter():
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if "Result" in tag and elem.text:
                return base64.b64decode(elem.text)
        return None

    async def baixar_comprovantes_catalogo(self, catalogo_id: str) -> list[tuple[bytes, str, dict]]:
        """Baixa TODOS os documentos de um catálogo.

        Retorna lista de (bytes, mime_type, catalog_meta).
        catalog_meta contém: id_do_catalogo, id_do_documento, titulo, descricao, extensao_docto.
        """
        documents: list[tuple[bytes, str, dict]] = []
        try:
            doc_list = await self.listar_documentos_catalogo(catalogo_id)
            if not doc_list:
                return documents

            for doc_info in doc_list:
                doc_id = str(doc_info.get("id_do_documento", ""))
                cat_id = str(doc_info.get("id_do_catalogo", ""))
                ext = doc_info.get("extensao_docto", "").strip()
                if not doc_id or not ext:
                    continue

                file_bytes = await self.baixar_documento(cat_id or catalogo_id, doc_id, ext)
                if not file_bytes:
                    logger.warning(
                        "RetornaArquivo vazio: catalogo=%s, doc=%s, ext=%s",
                        cat_id, doc_id, ext,
                    )
                    continue

                mime = _detect_mime_type(file_bytes)
                if not mime:
                    # Fallback por extensão
                    ext_map = {
                        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                        ".png": "image/png", ".gif": "image/gif",
                        ".pdf": "application/pdf", ".bmp": "image/bmp",
                    }
                    mime = ext_map.get(ext.lower(), "application/octet-stream")

                catalog_meta = {
                    "id_do_catalogo": cat_id,
                    "id_do_documento": doc_id,
                    "titulo": (doc_info.get("titulo") or "").strip(),
                    "descricao": (doc_info.get("descricao") or "").strip(),
                    "extensao_docto": ext,
                }
                documents.append((file_bytes, mime, catalog_meta))
                logger.debug(
                    "Documento baixado: catalogo=%s doc=%s ext=%s titulo='%s' (%d bytes, %s)",
                    cat_id, doc_id, ext, catalog_meta["titulo"], len(file_bytes), mime,
                )

        except Exception as e:
            logger.warning("Erro ao baixar documentos do catálogo %s: %s", catalogo_id, e)
        return documents

    # ------------------------------------------------------------------
    # High-level: query → save as Source
    # ------------------------------------------------------------------

    async def query_as_source(
        self,
        session_id: int,
        query_type: str,
        condominio: int,
        mes: int | None = None,
        ano: int | None = None,
    ) -> Source:
        """Executa consulta SOAP e salva o resultado como Source no banco."""
        session = await self.db.get(Session, session_id)
        if not session:
            raise NotFoundError(404, f"Session {session_id} não encontrada")

        data = await self._execute_query(query_type, condominio, mes, ano)

        label_base = GOSATI_QUERY_LABELS.get(query_type, query_type)
        period_suffix = ""
        if mes and ano:
            period_suffix = f" - {mes:02d}/{ano}"
        elif ano:
            period_suffix = f" - {ano}"
        label = f"{label_base}{period_suffix} (Cond. {condominio})"

        if data is None:
            raise GoSatiError(
                f"API GoSati não retornou dados para {label}. "
                "Verifique se o condomínio e período estão corretos."
            )

        text_content = _dict_to_text(data, label)
        content_bytes = text_content.encode("utf-8")

        # Salva em disco
        save_dir = GOSATI_DIR / str(session_id)
        save_dir.mkdir(parents=True, exist_ok=True)
        filename = f"gosati_{query_type}_{condominio}_{mes or 0}_{ano or 0}.txt"
        file_path = save_dir / filename
        file_path.write_bytes(content_bytes)

        source = Source(
            session_id=session_id,
            filename=filename,
            file_path=str(file_path),
            mime_type="text/plain",
            size_bytes=len(content_bytes),
            origin="gosati",
            label=label,
            text_path="",
            is_native=True,
        )
        self.db.add(source)
        session.source_count += 1
        await self.db.commit()
        await self.db.refresh(source)

        # Se prestação de contas, retorna dados para cache de comprovantes
        if query_type == "prestacao_contas":
            source._prestacao_data = data  # transient, não persiste

        return source

    async def query_filtered_as_source(
        self,
        session_id: int,
        condominio: int,
        mes: int,
        ano: int,
        sections: dict,
        filters: dict,
    ) -> Source:
        """Consulta GoSATI com seções seletivas e filtros, salva como Source."""
        session = await self.db.get(Session, session_id)
        if not session:
            raise NotFoundError(404, f"Session {session_id} não encontrada")

        # Mapeia seções para parâmetros do SOAP
        data = await self.consultar_prestacao_contas(
            condominio=condominio,
            mes=mes,
            ano=ano,
            demonstr_contas=sections.get("contas", False),
            demonstr_despesas=sections.get("despesas", False),
            relat_devedores=sections.get("devedores", False),
            demonstr_receitas=sections.get("receitas", False),
            acompanh_cobranca=sections.get("cobranca", False),
            orcado_gasto=sections.get("orcado_gasto", False),
        )

        if data is None:
            raise GoSatiError(
                f"API GoSati não retornou dados para Cond. {condominio} "
                f"({mes:02d}/{ano})."
            )

        # Aplica filtros pós-resposta
        if filters:
            data = self._apply_filters(data, filters)

        label = f"Prestação Filtrada - {mes:02d}/{ano} (Cond. {condominio})"
        text_content = _dict_to_text(data, label)
        content_bytes = text_content.encode("utf-8")

        save_dir = GOSATI_DIR / str(session_id)
        save_dir.mkdir(parents=True, exist_ok=True)
        filename = f"gosati_filtered_{condominio}_{mes}_{ano}.txt"
        file_path = save_dir / filename
        file_path.write_bytes(content_bytes)

        source = Source(
            session_id=session_id,
            filename=filename,
            file_path=str(file_path),
            mime_type="text/plain",
            size_bytes=len(content_bytes),
            origin="gosati",
            label=label,
            text_path="",
            is_native=True,
        )
        self.db.add(source)
        session.source_count += 1
        await self.db.commit()
        await self.db.refresh(source)
        return source

    @staticmethod
    def _apply_filters(data: dict, filters: dict) -> dict:
        """Filtra seções da prestação de contas por critérios.

        Suporta 3 campos: nome_conta_despesas, nome_sub_conta, historico.
        Lógica OR entre campos, OR dentro de cada campo (substring match).
        """
        diffgram = data.get("diffgram", {})
        prestacao = diffgram.get("PrestacaoContas", {})
        if not prestacao:
            return data

        # Parse filtros opcionais — normaliza para listas uppercase
        filter_fields: dict[str, list[str]] = {}
        for key in ("nome_conta_despesas", "nome_sub_conta", "historico"):
            raw = filters.get(key, [])
            if isinstance(raw, str):
                raw = [raw]
            values = [v.upper() for v in raw if v.strip()]
            if values:
                filter_fields[key] = values

        if not filter_fields:
            return data

        def _matches(d: dict) -> bool:
            """Match em QUALQUER campo = inclui (OR entre campos, OR dentro)."""
            for field, terms in filter_fields.items():
                val = d.get(field, "").upper()
                if any(term in val for term in terms):
                    return True
            return False

        # Filtra Despesas
        if "Despesas" in prestacao:
            despesas = prestacao["Despesas"]
            if isinstance(despesas, list):
                prestacao["Despesas"] = [
                    d for d in despesas
                    if isinstance(d, dict) and _matches(d)
                ]

        # Filtra Receitas
        if "Receitas" in prestacao:
            receitas = prestacao["Receitas"]
            if isinstance(receitas, list):
                prestacao["Receitas"] = [
                    r for r in receitas
                    if isinstance(r, dict) and _matches(r)
                ]

        data["diffgram"]["PrestacaoContas"] = prestacao
        return data

    async def save_comprovantes_as_sources(
        self,
        session_id: int,
        despesas: list[dict],
    ) -> list[Source]:
        """Baixa comprovantes via SOAP (catalogo_id) e salva como Source.

        Args:
            despesas: lista de dicts com {numero_lancamento, historico, valor, catalogo_id}
        """
        session = await self.db.get(Session, session_id)
        if not session:
            raise NotFoundError(404, f"Session {session_id} não encontrada")

        save_dir = GOSATI_DIR / str(session_id) / "comprovantes"
        save_dir.mkdir(parents=True, exist_ok=True)

        sources: list[Source] = []

        for desp_idx, desp in enumerate(despesas):
            catalogo_id = str(desp.get("catalogo_id", ""))
            if not catalogo_id:
                continue

            documents = await self.baixar_comprovantes_catalogo(catalogo_id)
            if not documents:
                logger.warning(
                    "Sessão %d: nenhum documento no catálogo %s (desp %d/%d)",
                    session_id, catalogo_id, desp_idx + 1, len(despesas),
                )
                continue

            lanc = desp.get("numero_lancamento", "")
            hist = desp.get("historico", "")[:60]
            valor = desp.get("valor", "")
            total_docs = len(documents)

            for doc_idx, (doc_bytes, mime_type, catalog_meta) in enumerate(documents):
                doc_bytes, mime_type = _compress_image(doc_bytes, mime_type)

                ext = {
                    "image/jpeg": ".jpg",
                    "image/png": ".png",
                    "image/gif": ".gif",
                    "image/bmp": ".bmp",
                    "image/webp": ".webp",
                    "image/tiff": ".tiff",
                    "application/pdf": ".pdf",
                }.get(mime_type, ".bin")

                filename = f"comprovante_{lanc}_{doc_idx}{ext}"
                file_path = save_dir / filename
                file_path.write_bytes(doc_bytes)

                # Extrai texto de PDFs
                text_path = ""
                is_native = True
                if mime_type == "application/pdf":
                    try:
                        extracted = extract_text_from_pdf(doc_bytes)
                        if extracted.strip() and not _is_binary_garbage(extracted):
                            txt_file = file_path.with_suffix(".extracted.txt")
                            txt_file.write_text(extracted, encoding="utf-8")
                            text_path = str(txt_file)
                            is_native = False
                    except Exception as e:
                        logger.warning("Falha extração PDF %s: %s", filename, e)

                # Label rico usando metadata do catálogo
                cat_titulo = catalog_meta.get("titulo", "")
                cat_descricao = catalog_meta.get("descricao", "")
                cat_id = catalog_meta.get("id_do_catalogo", "")

                if cat_titulo:
                    doc_type = cat_titulo
                elif total_docs == 1:
                    doc_type = "Comprovante"
                elif ext == ".pdf":
                    doc_type = "Relação Bancária"
                else:
                    doc_type = "Comprovante de Pagamento"

                label_parts = [f"{doc_type} Lanç.{lanc}"]
                if cat_descricao and cat_descricao != cat_titulo:
                    label_parts.append(f"({cat_descricao})")
                label_parts.append(f"— {hist} (R$ {valor})")
                if cat_id:
                    label_parts.append(f"[cat.{cat_id}]")
                label = " ".join(label_parts)

                source = Source(
                    session_id=session_id,
                    filename=filename,
                    file_path=str(file_path),
                    mime_type=mime_type,
                    size_bytes=len(doc_bytes),
                    origin="gosati",
                    label=label,
                    text_path=text_path,
                    is_native=is_native,
                )
                self.db.add(source)
                sources.append(source)
                session.source_count += 1

        if sources:
            await self.db.commit()
            for s in sources:
                await self.db.refresh(s)

        return sources

    # ------------------------------------------------------------------
    # Internal dispatch
    # ------------------------------------------------------------------

    async def _execute_query(
        self, query_type: str, condominio: int, mes: int | None, ano: int | None
    ) -> dict | None:
        dispatch = {
            "prestacao_contas": lambda: self.consultar_prestacao_contas(condominio, mes, ano),
            "fluxo_caixa": lambda: self.consultar_fluxo_caixa(condominio, mes, ano),
            "inadimplencia": lambda: self.consultar_inadimplencia(condominio),
            "periodo_fechamento": lambda: self.consultar_periodo_fechamento(condominio, ano),
            "previsao_orcamentaria": lambda: self.consultar_previsao_orcamentaria(condominio, mes, ano),
            "relacao_lancamentos": lambda: self.consultar_relacao_lancamentos(condominio, mes, ano),
            "relacao_pendentes": lambda: self.consultar_relacao_pendentes(condominio, ano),
        }
        fn = dispatch.get(query_type)
        if not fn:
            raise GoSatiError(f"Tipo de consulta inválido: {query_type}")
        return await fn()

    def format_as_text(self, data: dict | None, label: str) -> str:
        if data is None:
            return f"=== {label} ===\n\nNenhum dado retornado pela API."
        return _dict_to_text(data, label)
