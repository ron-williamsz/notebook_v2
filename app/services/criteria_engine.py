"""Motor de execução de critérios estruturados.

Processa critérios em fases:
  A) Rule-based: presenca_documento, classificacao_documento, consistencia_historico
  B) IA 1:1: conferencia_conteudo (Gemini, 1 doc vs 1 lançamento)
  C) IA N:1: conferencia_soma (Gemini, soma de N lançamentos vs 1 guia/DARF)
"""
import json
import logging
import re
from pathlib import Path
from typing import Any

from google.genai import Client as GenaiClient
from google.genai.types import Content, GenerateContentConfig, Part

from app.core.config import Settings
from app.schemas.criterio import (
    CRITERION_CONFIG_MAP,
    ClassificacaoDocumentoConfig,
    ConferenciaConteudoConfig,
    ConferenciaSomaConfig,
    ConsistenciaHistoricoConfig,
    CriteriaExecutionResult,
    CriterionGroupResult,
    CriterionResult,
    PresencaDocumentoConfig,
)

logger = logging.getLogger(__name__)


def _resolve_path(p: str) -> Path:
    """Resolve path cross-environment."""
    path = Path(p)
    if path.exists():
        return path
    for base in ("/app", "/Users"):
        if p.startswith(base):
            alt = Path(p.replace("/app/", "").replace(str(Path.cwd()) + "/", ""))
            if alt.exists():
                return alt
    return path


class CriteriaEngine:
    def __init__(self, gemini_client: GenaiClient, settings: Settings):
        self._gemini = gemini_client
        self._settings = settings

    @staticmethod
    def _lanc_info(lanc: dict) -> dict:
        """Extrai info do lançamento para referência no resultado."""
        return {
            "historico": lanc.get("historico", ""),
            "valor": lanc.get("valor", "0"),
            "data": lanc.get("data", ""),
            "nome_conta": lanc.get("nome_conta", ""),
            "nome_sub_conta": lanc.get("nome_sub_conta", ""),
        }

    async def execute(
        self,
        criteria: list,
        lancamentos: list[dict],
        docs_by_lancamento: dict[str, list[dict]],
        progress_cb=None,
    ) -> CriteriaExecutionResult:
        """Executa todos os critérios sobre os lançamentos."""
        # Index lançamentos por numero para lookup rápido
        lanc_map = {str(l["numero_lancamento"]): l for l in lancamentos}
        grupos: list[CriterionGroupResult] = []

        for criterion in criteria:
            if not criterion.is_active:
                continue

            config_cls = CRITERION_CONFIG_MAP.get(criterion.tipo)
            if not config_cls:
                logger.warning("Tipo de critério desconhecido: %s", criterion.tipo)
                continue

            config = config_cls.model_validate_json(criterion.config_json)

            if progress_cb:
                progress_cb(f"Avaliando: {criterion.nome}...")

            if criterion.tipo == "presenca_documento":
                results = self._eval_presenca(
                    config, criterion.nome, lancamentos, docs_by_lancamento
                )
            elif criterion.tipo == "classificacao_documento":
                results = self._eval_classificacao(
                    config, criterion.nome, lancamentos, docs_by_lancamento
                )
            elif criterion.tipo == "conferencia_conteudo":
                results = await self._eval_conferencia(
                    config, criterion.nome, lancamentos, docs_by_lancamento
                )
            elif criterion.tipo == "consistencia_historico":
                results = self._eval_consistencia_historico(
                    config, criterion.nome, lancamentos
                )
            elif criterion.tipo == "conferencia_soma":
                results = await self._eval_conferencia_soma(
                    config, criterion.nome, lancamentos, docs_by_lancamento
                )
            else:
                continue

            # Popula lancamento_info em cada resultado
            for r in results:
                lanc = lanc_map.get(r.lancamento)
                if lanc:
                    r.lancamento_info = self._lanc_info(lanc)

            # Agrupa
            grupo = CriterionGroupResult(
                criterio_nome=criterion.nome,
                criterio_tipo=criterion.tipo,
                total=len(results),
                aprovados=sum(1 for r in results if r.resultado == "APROVADO"),
                divergencias=sum(1 for r in results if r.resultado == "DIVERGENCIA"),
                ausentes=sum(1 for r in results if r.resultado == "ITEM_AUSENTE"),
                itens=results,
            )
            grupos.append(grupo)

        return self._aggregate(grupos, lancamentos)

    # ── Rule-based: presenca_documento ────────────────────────────────

    def _eval_presenca(
        self,
        config: PresencaDocumentoConfig,
        criterio_nome: str,
        lancamentos: list[dict],
        docs_by_lanc: dict[str, list[dict]],
    ) -> list[CriterionResult]:
        results = []
        lanc_list = self._filter_by_posicao(lancamentos, config.posicao)

        for lanc in lanc_list:
            num = lanc["numero_lancamento"]
            docs = docs_by_lanc.get(num, [])
            found = False

            for doc in docs:
                # Filtro por mime_type (ex: image/jpeg para comprovantes)
                if config.mime_types:
                    doc_mime = doc.get("mime_type", "")
                    if not any(mt in doc_mime for mt in config.mime_types):
                        continue
                texto = (doc.get("texto_extraido") or doc.get("label") or "").lower()
                if any(kw.lower() in texto for kw in config.palavras_chave):
                    found = True
                    break

            if found:
                results.append(CriterionResult(
                    lancamento=num,
                    criterio_nome=criterio_nome,
                    criterio_tipo="presenca_documento",
                    documento_tipo=config.documento_nome,
                    resultado="APROVADO",
                    detalhes=f"{config.documento_nome} encontrado",
                ))
            else:
                resultado = "ITEM_AUSENTE" if config.obrigatorio else "APROVADO"
                results.append(CriterionResult(
                    lancamento=num,
                    criterio_nome=criterio_nome,
                    criterio_tipo="presenca_documento",
                    documento_tipo=config.documento_nome,
                    resultado=resultado,
                    detalhes=f"{config.documento_nome} não encontrado"
                    if config.obrigatorio
                    else f"{config.documento_nome} não encontrado (opcional)",
                ))

        return results

    # ── Rule-based: classificacao_documento ────────────────────────────

    def _eval_classificacao(
        self,
        config: ClassificacaoDocumentoConfig,
        criterio_nome: str,
        lancamentos: list[dict],
        docs_by_lanc: dict[str, list[dict]],
    ) -> list[CriterionResult]:
        results = []

        for lanc in lancamentos:
            num = lanc["numero_lancamento"]
            docs = docs_by_lanc.get(num, [])
            classificacoes = []

            for doc in docs:
                texto = (doc.get("texto_extraido") or doc.get("label") or "").lower()
                matched = None
                for cat in config.categorias:
                    if any(kw.lower() in texto for kw in cat.palavras_chave):
                        matched = cat.nome
                        break
                classificacoes.append(matched or "Não identificado")

            results.append(CriterionResult(
                lancamento=num,
                criterio_nome=criterio_nome,
                criterio_tipo="classificacao_documento",
                resultado="APROVADO",
                detalhes=", ".join(classificacoes) if classificacoes else "Sem documentos",
            ))

        return results

    # ── IA: conferencia_conteudo ──────────────────────────────────────

    async def _eval_conferencia(
        self,
        config: ConferenciaConteudoConfig,
        criterio_nome: str,
        lancamentos: list[dict],
        docs_by_lanc: dict[str, list[dict]],
    ) -> list[CriterionResult]:
        results = []
        batch: list[dict] = []

        # Filtra lançamentos por posição (primeiro/último/todos)
        lanc_list = self._filter_by_posicao(lancamentos, config.posicao)

        for lanc in lanc_list:
            num = lanc["numero_lancamento"]
            docs = docs_by_lanc.get(num, [])

            # Encontra o documento alvo pelo tipo (buscar_em) + mime_type
            target_doc = self._find_doc_by_type(
                docs, config.buscar_em, config.buscar_mime_types or None
            )
            if not target_doc:
                results.append(CriterionResult(
                    lancamento=num,
                    criterio_nome=criterio_nome,
                    criterio_tipo="conferencia_conteudo",
                    documento_tipo=config.buscar_em,
                    resultado="ITEM_AUSENTE",
                    detalhes=f"Documento '{config.buscar_em}' não encontrado para conferência",
                ))
                continue

            # Resolve valor de referência
            ref_value = self._resolve_reference(config.comparar_com, lanc)

            batch.append({
                "lancamento": num,
                "doc": target_doc,
                "campo": config.campo,
                "ref_value": ref_value,
                "instrucao": config.instrucao_busca,
                "tipo_comparacao": config.tipo_comparacao,
                "tolerancia": config.tolerancia,
                "criterio_nome": criterio_nome,
            })

            # Processa em batches de 5
            if len(batch) >= 5:
                batch_results = await self._process_ai_batch(batch)
                results.extend(batch_results)
                batch = []

        # Processa batch restante
        if batch:
            batch_results = await self._process_ai_batch(batch)
            results.extend(batch_results)

        return results

    async def _process_ai_batch(self, batch: list[dict]) -> list[CriterionResult]:
        """Processa um batch de conferências via Gemini."""
        results = []

        for item in batch:
            try:
                result = await self._ai_check_single(item)
                results.append(result)
            except Exception as e:
                logger.error("Erro IA conferência lanç. %s: %s", item["lancamento"], e)
                results.append(CriterionResult(
                    lancamento=item["lancamento"],
                    criterio_nome=item["criterio_nome"],
                    criterio_tipo="conferencia_conteudo",
                    resultado="DIVERGENCIA",
                    detalhes=f"Erro na conferência: {e}",
                ))

        return results

    async def _ai_check_single(self, item: dict) -> CriterionResult:
        """Executa conferência de um único lançamento via Gemini."""
        doc = item["doc"]
        parts = []

        # Adiciona documento (bytes)
        file_path = _resolve_path(doc.get("file_path", ""))
        if file_path.exists():
            data = file_path.read_bytes()
            parts.append(Part.from_bytes(data=data, mime_type=doc.get("mime_type", "application/octet-stream")))

        # Se tem texto extraído, inclui também
        if doc.get("texto_extraido"):
            parts.append(Part.from_text(text=f"[Texto extraído do documento]\n{doc['texto_extraido'][:3000]}"))

        # Prompt
        instrucao_extra = f"\nDica: {item['instrucao']}" if item.get("instrucao") else ""
        prompt = (
            f"Analise o documento anexo.\n"
            f"Campo a localizar: {item['campo']}\n"
            f"Valor de referência: {item['ref_value']}\n"
            f"{instrucao_extra}\n\n"
            f"Responda em JSON: {{\"valor_encontrado\": \"...\", \"confere\": true/false, \"observacao\": \"...\"}}"
        )
        parts.append(Part.from_text(text=prompt))

        response = await self._gemini.aio.models.generate_content(
            model=self._settings.gemini_model,
            contents=[Content(role="user", parts=parts)],
            config=GenerateContentConfig(
                system_instruction="Você é um auditor. Analise o documento e responda APENAS em JSON.",
                max_output_tokens=1024,
                temperature=0.1,
                response_mime_type="application/json",
            ),
        )

        ai_result = self._parse_ai_json(response.text)
        if ai_result is None:
            return CriterionResult(
                lancamento=item["lancamento"],
                criterio_nome=item["criterio_nome"],
                criterio_tipo="conferencia_conteudo",
                resultado="DIVERGENCIA",
                detalhes=f"Resposta IA não-JSON: {response.text[:200] if response.text else 'vazio'}",
            )

        confere = ai_result.get("confere", False)
        valor_encontrado = ai_result.get("valor_encontrado", "")
        observacao = ai_result.get("observacao", "")

        return CriterionResult(
            lancamento=item["lancamento"],
            criterio_nome=item["criterio_nome"],
            criterio_tipo="conferencia_conteudo",
            documento_tipo=item["doc"].get("label", ""),
            resultado="APROVADO" if confere else "DIVERGENCIA",
            detalhes=observacao or (f"Encontrado: {valor_encontrado}" if valor_encontrado else ""),
            valores={"encontrado": valor_encontrado, "esperado": str(item["ref_value"])},
        )

    # ── Rule-based: consistencia_historico ─────────────────────────────

    def _eval_consistencia_historico(
        self,
        config: ConsistenciaHistoricoConfig,
        criterio_nome: str,
        lancamentos: list[dict],
    ) -> list[CriterionResult]:
        """Verifica que todos os históricos contêm o mesmo valor (regex)."""
        results = []
        pattern = re.compile(config.padrao_regex)

        # Extrai valor de cada histórico
        valores: dict[str, str] = {}  # num_lanc → valor extraído
        for lanc in lancamentos:
            num = lanc["numero_lancamento"]
            historico = lanc.get("historico", "")
            m = pattern.search(historico)
            valores[num] = m.group(1) if m else ""

        # Determina valor majoritário (moda)
        contagem: dict[str, int] = {}
        for v in valores.values():
            if v:
                contagem[v] = contagem.get(v, 0) + 1
        valor_esperado = max(contagem, key=contagem.get) if contagem else ""

        for lanc in lancamentos:
            num = lanc["numero_lancamento"]
            encontrado = valores.get(num, "")

            if not encontrado:
                results.append(CriterionResult(
                    lancamento=num,
                    criterio_nome=criterio_nome,
                    criterio_tipo="consistencia_historico",
                    resultado="DIVERGENCIA",
                    detalhes=f"{config.campo_descricao} não encontrada no histórico",
                    valores={"encontrado": "(vazio)", "esperado": valor_esperado},
                ))
            elif encontrado == valor_esperado:
                results.append(CriterionResult(
                    lancamento=num,
                    criterio_nome=criterio_nome,
                    criterio_tipo="consistencia_historico",
                    resultado="APROVADO",
                    detalhes=f"{config.campo_descricao}: {encontrado}",
                    valores={"encontrado": encontrado, "esperado": valor_esperado},
                ))
            else:
                results.append(CriterionResult(
                    lancamento=num,
                    criterio_nome=criterio_nome,
                    criterio_tipo="consistencia_historico",
                    resultado="DIVERGENCIA",
                    detalhes=f"{config.campo_descricao} divergente",
                    valores={"encontrado": encontrado, "esperado": valor_esperado},
                ))

        return results

    # ── IA: conferencia_soma ──────────────────────────────────────────

    async def _eval_conferencia_soma(
        self,
        config: ConferenciaSomaConfig,
        criterio_nome: str,
        lancamentos: list[dict],
        docs_by_lanc: dict[str, list[dict]],
    ) -> list[CriterionResult]:
        """Soma valores de todos os lançamentos e compara com documento-guia via IA.

        Fluxo:
          1. Soma lancamento.valor de todos os lançamentos
          2. Procura documento-guia (DARF, GPS) em TODOS os lançamentos
          3. Envia à IA para extrair valor do documento
          4. Compara soma vs valor extraído
          5. Todos os lançamentos recebem o mesmo veredito
        """
        results = []

        # 1. Calcula soma
        soma = 0.0
        for lanc in lancamentos:
            try:
                soma += float(lanc.get("valor", 0))
            except (ValueError, TypeError):
                pass
        soma_str = f"{soma:.2f}"

        # 2. Procura documento-guia em TODOS os lançamentos
        guia_doc = None
        guia_lanc_num = None
        for lanc in lancamentos:
            num = lanc["numero_lancamento"]
            docs = docs_by_lanc.get(num, [])
            found = self._find_doc_by_type(docs, config.buscar_em)
            if found:
                guia_doc = found
                guia_lanc_num = num
                break

        if not guia_doc:
            # Guia não encontrada — todos ITEM_AUSENTE
            for lanc in lancamentos:
                results.append(CriterionResult(
                    lancamento=lanc["numero_lancamento"],
                    criterio_nome=criterio_nome,
                    criterio_tipo="conferencia_soma",
                    resultado="ITEM_AUSENTE",
                    detalhes=f"Documento-guia '{config.buscar_em}' não encontrado em nenhum lançamento",
                    valores={"soma_lancamentos": soma_str},
                ))
            return results

        # 3. Envia à IA para extrair valor da guia
        try:
            valor_guia = await self._ai_extract_valor_guia(config, guia_doc, soma_str)
        except Exception as e:
            logger.error("Erro IA conferência soma: %s", e)
            for lanc in lancamentos:
                results.append(CriterionResult(
                    lancamento=lanc["numero_lancamento"],
                    criterio_nome=criterio_nome,
                    criterio_tipo="conferencia_soma",
                    resultado="DIVERGENCIA",
                    detalhes=f"Erro na conferência da guia: {e}",
                ))
            return results

        # 4. Compara
        confere = valor_guia.get("confere", False)
        valor_encontrado = valor_guia.get("valor_encontrado", "")
        observacao = valor_guia.get("observacao", "")
        veredito = "APROVADO" if confere else "DIVERGENCIA"

        # 5. Resultado para cada lançamento (mesmo veredito)
        for lanc in lancamentos:
            num = lanc["numero_lancamento"]
            valor_lanc = lanc.get("valor", "0")
            detalhe = f"Parcela: R$ {float(valor_lanc):,.2f}"
            if num == guia_lanc_num:
                detalhe = f"Guia encontrada aqui. {observacao}" if observacao else detalhe

            results.append(CriterionResult(
                lancamento=num,
                criterio_nome=criterio_nome,
                criterio_tipo="conferencia_soma",
                documento_tipo=config.buscar_em,
                resultado=veredito,
                detalhes=detalhe,
                valores={
                    "encontrado": valor_encontrado,
                    "esperado": soma_str,
                },
            ))

        return results

    async def _ai_extract_valor_guia(
        self, config: ConferenciaSomaConfig, doc: dict, soma_ref: str
    ) -> dict:
        """Extrai valor total de um documento-guia via Gemini.

        IMPORTANTE: A IA só EXTRAI o valor. A comparação numérica é feita no código
        para evitar alucinações (IA pode dizer 'confere' quando não confere).
        """
        parts = []

        file_path = _resolve_path(doc.get("file_path", ""))
        if file_path.exists():
            data = file_path.read_bytes()
            parts.append(Part.from_bytes(
                data=data,
                mime_type=doc.get("mime_type", "application/octet-stream"),
            ))

        if doc.get("texto_extraido"):
            parts.append(Part.from_text(
                text=f"[Texto extraído do documento]\n{doc['texto_extraido'][:3000]}"
            ))

        instrucao_extra = f"\nDica: {config.instrucao_busca}" if config.instrucao_busca else ""
        prompt = (
            f"Analise o documento-guia anexo.\n"
            f"Campo a localizar: {config.campo}\n"
            f"{instrucao_extra}\n\n"
            f"Extraia APENAS o valor numérico do campo solicitado. "
            f"NÃO faça comparações — apenas extraia o valor.\n\n"
            f"Responda em JSON: {{\"valor_encontrado\": \"...\", \"observacao\": \"...\"}}"
        )
        parts.append(Part.from_text(text=prompt))

        response = await self._gemini.aio.models.generate_content(
            model=self._settings.gemini_model,
            contents=[Content(role="user", parts=parts)],
            config=GenerateContentConfig(
                system_instruction="Você é um auditor. Extraia o valor solicitado do documento e responda APENAS em JSON.",
                max_output_tokens=1024,
                temperature=0.1,
                response_mime_type="application/json",
            ),
        )

        ai_result = self._parse_ai_json(response.text)
        if ai_result is None:
            return {
                "valor_encontrado": "",
                "confere": False,
                "observacao": f"Resposta IA não-JSON: {response.text[:200] if response.text else 'vazio'}",
            }

        # Comparação numérica feita NO CÓDIGO, não pela IA
        valor_str = str(ai_result.get("valor_encontrado", ""))
        valor_guia = self._parse_valor_br(valor_str)
        soma_float = float(soma_ref)

        if valor_guia is None:
            ai_result["confere"] = False
            ai_result["observacao"] = f"Não foi possível interpretar o valor: {valor_str}"
        else:
            diff = abs(valor_guia - soma_float)
            tolerancia_abs = soma_float * config.tolerancia
            ai_result["confere"] = diff <= tolerancia_abs
            if ai_result["confere"]:
                ai_result["observacao"] = f"Valor guia R$ {valor_guia:,.2f} confere com soma R$ {soma_float:,.2f}"
            else:
                ai_result["observacao"] = (
                    f"DIVERGÊNCIA: Guia R$ {valor_guia:,.2f} ≠ Soma R$ {soma_float:,.2f} "
                    f"(diferença: R$ {diff:,.2f})"
                )

        logger.info(
            "conferencia_soma: guia=%s, soma=%s, confere=%s",
            valor_str, soma_ref, ai_result["confere"],
        )
        return ai_result

    # ── Helpers ───────────────────────────────────────────────────────

    def _filter_by_posicao(
        self, lancamentos: list[dict], posicao: str
    ) -> list[dict]:
        """Filtra lançamentos por posição (primeiro/último/todos)."""
        if posicao == "todos" or not lancamentos:
            return lancamentos
        if posicao == "primeiro":
            return [lancamentos[0]]
        if posicao == "ultimo":
            return [lancamentos[-1]]
        return lancamentos

    @staticmethod
    def _parse_ai_json(text: str | None) -> dict | None:
        """Parseia JSON da resposta IA, tolerando markdown wrappers."""
        if not text:
            return None
        # Tentativa direta
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            pass
        # Remove markdown code blocks (```json ... ``` ou ``` ... ```)
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)
        try:
            return json.loads(cleaned)
        except (json.JSONDecodeError, ValueError):
            pass
        # Extrai primeiro objeto JSON { ... }
        m = re.search(r"\{[^{}]*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except (json.JSONDecodeError, ValueError):
                pass
        return None

    @staticmethod
    def _parse_valor_br(s: str) -> float | None:
        """Parseia valor monetário BR/US: 60.691,97 ou 60,691.97 ou R$ 60691.97."""
        if not s:
            return None
        # Remove prefixo monetário e espaços
        clean = re.sub(r"[R$\s]", "", s.strip())
        if not clean:
            return None
        # Detecta formato BR (ponto como milhar, vírgula como decimal)
        # Ex: 60.691,97 → 60691.97
        if "," in clean and "." in clean:
            if clean.rindex(",") > clean.rindex("."):
                # BR: 60.691,97
                clean = clean.replace(".", "").replace(",", ".")
            else:
                # US: 60,691.97
                clean = clean.replace(",", "")
        elif "," in clean:
            # Só vírgula: pode ser 60691,97 (BR) ou 60,691 (US milhar)
            parts = clean.split(",")
            if len(parts) == 2 and len(parts[1]) <= 2:
                clean = clean.replace(",", ".")
            else:
                clean = clean.replace(",", "")
        try:
            return float(clean)
        except ValueError:
            return None

    def _find_doc_by_type(
        self, docs: list[dict], tipo_busca: str, mime_types: list[str] | None = None
    ) -> dict | None:
        """Encontra documento pelo tipo/nome usando keywords + mime_type opcional."""
        tipo_lower = tipo_busca.lower()
        for doc in docs:
            if mime_types:
                doc_mime = doc.get("mime_type", "")
                if not any(mt in doc_mime for mt in mime_types):
                    continue
            texto = (doc.get("texto_extraido") or doc.get("label") or "").lower()
            if tipo_lower in texto:
                return doc
        # Fallback: se tem um único doc (respeitando mime_type), usa ele
        candidates = docs
        if mime_types:
            candidates = [d for d in docs if any(mt in d.get("mime_type", "") for mt in mime_types)]
        if len(candidates) == 1:
            return candidates[0]
        return None

    def _resolve_reference(self, ref: str, lancamento: dict) -> Any:
        """Resolve referência como 'lancamento.valor' ou 'periodo.mes_ano'."""
        if not ref:
            return ""
        if ref.startswith("lancamento."):
            field = ref.split(".", 1)[1]
            return lancamento.get(field, "")
        if ref == "periodo.mes_ano":
            # Extrai competência do histórico (ex: "FOLHA DE PAGTO 12/2025" → "12/2025")
            historico = lancamento.get("historico", "")
            m = re.search(r"(\d{1,2}/\d{4})", historico)
            if m:
                return m.group(1)
            # Fallback: data do lançamento
            data = lancamento.get("data", "")
            if data:
                parts = data.split("T")[0].split("-")
                if len(parts) >= 2:
                    return f"{parts[1]}/{parts[0]}"
            return ""
        if ref == "historico.consumo":
            # Extrai consumo do histórico: "2708 m³", "21360 kWh"
            historico = lancamento.get("historico", "")
            m = re.search(r"([\d.,]+)\s*(m³|m3|kwh|kWh|KWH)", historico, re.IGNORECASE)
            if m:
                return m.group(1).strip()
            return ""
        return ref

    def _aggregate(
        self, grupos: list[CriterionGroupResult], lancamentos: list[dict]
    ) -> CriteriaExecutionResult:
        """Agrega grupos em resumo global."""
        total_verificacoes = sum(g.total for g in grupos)
        aprovados = sum(g.aprovados for g in grupos)
        divergencias = sum(g.divergencias for g in grupos)
        ausentes = sum(g.ausentes for g in grupos)

        return CriteriaExecutionResult(
            grupos=grupos,
            resumo={
                "total_lancamentos": len(lancamentos),
                "total_verificacoes": total_verificacoes,
                "aprovados": aprovados,
                "divergencias": divergencias,
                "itens_ausentes": ausentes,
            },
        )
