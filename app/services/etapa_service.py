"""Serviço de Etapas — busca lançamentos e documentos por Skill + análise IA.

Pipeline:
  1. Auto-fetch GoSATI (seções + filtros da Skill)
  2. Baixa comprovantes das despesas filtradas
  3. Retorna lista estruturada de lançamentos com referência aos documentos
  4. Análise IA dos lançamentos + documentos via Gemini (se skill tiver macro_instruction)
"""
import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator

from google import genai
from google.genai import types as genai_types
from google.genai.types import Content, GenerateContentConfig, Part
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.config import BASE_DIR, Settings
from app.core.exceptions import NotFoundError
from app.models.etapa import Etapa
from app.models.session import Session
from app.models.skill import Skill
from app.models.source import Source
from app.services.criteria_engine import CriteriaEngine
from app.services.gosati_service import GoSatiService
from app.services.skill_service import SkillService
from app.services.source_service import SourceService

logger = logging.getLogger(__name__)


def _resolve_path(stored_path: str) -> Path:
    """Resolve file_path stored in DB, handling environment changes (e.g. Mac → Docker)."""
    fp = Path(stored_path)
    if fp.exists():
        return fp
    match = re.search(r"[/\\](data[/\\].+)$", stored_path)
    if match:
        resolved = BASE_DIR / match.group(1).replace("\\", "/")
        if resolved.exists():
            return resolved
    return fp


class EtapaService:
    def __init__(self, db: AsyncSession, settings: Settings):
        self.db = db
        self.settings = settings
        self.skill_svc = SkillService(db)
        self.source_svc = SourceService(db)
        self._gemini_client = genai.Client(
            vertexai=True,
            project=settings.gcp_project_id,
            location=settings.gemini_location,
            http_options=genai_types.HttpOptions(
                timeout=180_000,
            ),
        )

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def list_by_session(self, session_id: int) -> list[dict]:
        """Lista etapas de uma sessão com dados da skill."""
        result = await self.db.execute(
            select(Etapa)
            .where(Etapa.session_id == session_id)
            .order_by(Etapa.order)
        )
        etapas = result.scalars().all()
        out = []
        dirty = False
        for e in etapas:
            # Auto-fix: etapas com status "running" mas que não estão de fato
            # executando (conexão SSE caiu). Se tem resultado, marca done.
            if e.status == "running":
                if e.result_text:
                    e.status = "done"
                    e.updated_at = datetime.now(timezone.utc)
                    dirty = True
                elif (datetime.now(timezone.utc) - e.updated_at.replace(tzinfo=timezone.utc)).total_seconds() > 600:
                    # Mais de 10 min sem atualização → provavelmente morreu
                    e.status = "error"
                    e.error_message = "Execução interrompida (timeout)"
                    e.updated_at = datetime.now(timezone.utc)
                    dirty = True

            skill = await self.db.get(Skill, e.skill_id)
            out.append({
                "id": e.id,
                "session_id": e.session_id,
                "skill_id": e.skill_id,
                "skill_name": skill.name if skill else "Skill removida",
                "skill_icon": skill.icon if skill else "",
                "skill_color": skill.color if skill else "#6366f1",
                "order": e.order,
                "status": e.status,
                "result_text": e.result_text,
                "error_message": e.error_message,
                "created_at": e.created_at.isoformat(),
                "updated_at": e.updated_at.isoformat(),
            })
        if dirty:
            await self.db.commit()
        return out

    async def create(self, session_id: int, skill_id: int) -> dict:
        """Cria nova etapa para a sessão."""
        session = await self.db.get(Session, session_id)
        if not session:
            raise NotFoundError(404, f"Session {session_id} não encontrada")

        skill = await self.skill_svc.get_by_id(skill_id)

        result = await self.db.execute(
            select(Etapa)
            .where(Etapa.session_id == session_id)
            .order_by(Etapa.order.desc())
        )
        last = result.scalars().first()
        next_order = (last.order + 1) if last else 1

        etapa = Etapa(
            session_id=session_id,
            skill_id=skill_id,
            order=next_order,
        )
        self.db.add(etapa)
        await self.db.commit()
        await self.db.refresh(etapa)

        return {
            "id": etapa.id,
            "session_id": etapa.session_id,
            "skill_id": etapa.skill_id,
            "skill_name": skill.name,
            "skill_icon": skill.icon,
            "skill_color": skill.color,
            "order": etapa.order,
            "status": etapa.status,
            "result_text": etapa.result_text,
            "error_message": etapa.error_message,
            "created_at": etapa.created_at.isoformat(),
            "updated_at": etapa.updated_at.isoformat(),
        }

    async def delete(self, session_id: int, etapa_id: int) -> None:
        """Remove uma etapa."""
        etapa = await self.db.get(Etapa, etapa_id)
        if not etapa or etapa.session_id != session_id:
            raise NotFoundError(404, f"Etapa {etapa_id} não encontrada")
        await self.db.delete(etapa)
        await self.db.commit()

    # ------------------------------------------------------------------
    # Execução: busca lançamentos + documentos + análise IA
    # ------------------------------------------------------------------

    async def execute(
        self, session_id: int, etapa_id: int,
        cond_codigo_override: int | None = None,
        request=None,
    ) -> AsyncGenerator[str, None]:
        """Busca lançamentos, documentos e executa análise IA via Gemini."""
        etapa = await self.db.get(Etapa, etapa_id)
        if not etapa or etapa.session_id != session_id:
            raise NotFoundError(404, f"Etapa {etapa_id} não encontrada")

        etapa.status = "running"
        etapa.updated_at = datetime.now(timezone.utc)
        await self.db.commit()

        async def _check_cancelled():
            if request and await request.is_disconnected():
                raise asyncio.CancelledError("Client disconnected")

        try:
            skill = await self.skill_svc.get_by_id(etapa.skill_id)

            # Fase 1: Auto-fetch GoSATI se configurado
            if skill.gosati_sections:
                progress_msgs = []
                await self._auto_fetch_gosati(
                    session_id, skill,
                    progress_cb=lambda msg: progress_msgs.append(msg),
                    cond_codigo_override=cond_codigo_override,
                )
                for msg in progress_msgs:
                    yield f"data: {json.dumps({'progress': msg})}\n\n"

            await _check_cancelled()

            # Fase 2: Monta resultado estruturado
            yield f"data: {json.dumps({'progress': 'Organizando lançamentos...'})}\n\n"
            result = await self._build_lancamentos_result(session_id)
            yield f"data: {json.dumps({'result': result})}\n\n"

            await _check_cancelled()

            # Fase 3: Execução por modo
            await self.db.refresh(skill, ["steps", "examples", "criteria"])

            if skill.execution_mode == "criterios" and skill.criteria:
                # Modo critérios estruturados
                yield f"data: {json.dumps({'progress': 'Executando critérios...'})}\n\n"
                criteria_result = await self._execute_criteria(
                    session_id, skill, result,
                    progress_cb=lambda msg: None,
                )
                result["type"] = "criterios"
                result["criterios"] = criteria_result
                yield f"data: {json.dumps({'criteria_result': criteria_result})}\n\n"

            elif skill.steps:
                # Prepara contexto compartilhado (docs + metadata) uma vez
                base_parts = await self._build_analysis_context(
                    session_id, skill, result
                )
                step_results = []

                for i, step in enumerate(skill.steps):
                    await _check_cancelled()
                    step_title = step.title or f"Etapa {i + 1}"
                    yield f"data: {json.dumps({'progress': f'Analisando: {step_title}...'})}\n\n"
                    yield f"data: {json.dumps({'step_start': {'index': i, 'title': step_title}})}\n\n"

                    step_text = ""
                    async for chunk in self._run_step_analysis(
                        skill, step, base_parts, result
                    ):
                        await _check_cancelled()
                        step_text += chunk
                        yield f"data: {json.dumps({'step_chunk': {'index': i, 'text': chunk}})}\n\n"

                    step_results.append({
                        "title": step_title,
                        "instruction": step.instruction,
                        "response": step_text,
                    })

                result["analise_steps"] = step_results

            # Salva resultado combinado
            etapa.result_text = json.dumps(result, ensure_ascii=False)
            etapa.status = "done"
            etapa.updated_at = datetime.now(timezone.utc)
            await self.db.commit()

            yield "data: [DONE]\n\n"

        except asyncio.CancelledError:
            logger.info("Etapa %d cancelada pelo usuário", etapa_id)
            etapa.status = "cancelled"
            etapa.error_message = "Execução cancelada pelo usuário"
            etapa.updated_at = datetime.now(timezone.utc)
            await self.db.commit()
            yield f"data: {json.dumps({'error': 'Execução cancelada'})}\n\n"

        except Exception as e:
            logger.error(f"Erro ao executar etapa {etapa_id}: {e}")
            etapa.status = "error"
            etapa.error_message = str(e)
            etapa.updated_at = datetime.now(timezone.utc)
            await self.db.commit()
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

        finally:
            # Safety net: se o generator parou de ser consumido (conexão SSE caiu)
            # e o status ainda está "running", corrige para o estado correto.
            try:
                await self.db.rollback()  # limpa qualquer transação pendente
                await self.db.refresh(etapa)
                if etapa.status == "running":
                    if etapa.result_text:
                        etapa.status = "done"
                        logger.info("Etapa %d: SSE desconectou mas resultado já salvo → done", etapa_id)
                    else:
                        etapa.status = "error"
                        etapa.error_message = "Conexão perdida durante execução"
                        logger.warning("Etapa %d: SSE desconectou sem resultado → error", etapa_id)
                    etapa.updated_at = datetime.now(timezone.utc)
                    await self.db.commit()
            except Exception as cleanup_err:
                logger.warning("Etapa %d: cleanup falhou: %s", etapa_id, cleanup_err)

    async def _build_lancamentos_result(self, session_id: int) -> dict:
        """Monta estrutura de lançamentos com documentos a partir das Sources."""
        sources = await self.source_svc.list_by_session(session_id)

        # Separa: texto da prestação vs documentos binários
        prestacao_text = None
        prestacao_source_id = None
        doc_sources: list[Source] = []

        for src in sources:
            if src.mime_type == "text/plain" and src.origin == "gosati":
                # Lê o texto da prestação para extrair lançamentos
                prestacao_source_id = src.id
                try:
                    prestacao_text = _resolve_path(src.file_path).read_text(encoding="utf-8")
                except Exception:
                    pass
            elif src.origin == "gosati":
                doc_sources.append(src)

        # Extrai lançamentos do JSON da prestação
        lancamentos = self._parse_lancamentos(prestacao_text)

        # Associa documentos aos lançamentos pelo nº do lançamento no label
        lancamento_docs: dict[str, list[dict]] = {}
        orphan_docs: list[dict] = []

        for src in doc_sources:
            doc_info = {
                "source_id": src.id,
                "label": src.label or src.filename,
                "filename": src.filename,
                "mime_type": src.mime_type,
                "size_bytes": src.size_bytes,
            }
            # Extrai nº lançamento do label
            m = re.search(r"Lanç\.(\d+)", src.label or "")
            if m:
                lanc_num = m.group(1)
                lancamento_docs.setdefault(lanc_num, []).append(doc_info)
            else:
                orphan_docs.append(doc_info)

        # Enriquece lançamentos com seus documentos
        for lanc in lancamentos:
            num = lanc.get("numero_lancamento", "")
            lanc["documentos"] = lancamento_docs.get(str(num), [])

        return {
            "type": "lancamentos",
            "total": len(lancamentos),
            "lancamentos": lancamentos,
            "documentos_avulsos": orphan_docs,
            "prestacao_source_id": prestacao_source_id,
        }

    @staticmethod
    def _parse_lancamentos(prestacao_text: str | None) -> list[dict]:
        """Extrai lançamentos do texto JSON da prestação filtrada."""
        if not prestacao_text:
            return []

        try:
            # Remove header "=== ... ===" antes do JSON
            json_start = prestacao_text.find("{")
            if json_start < 0:
                return []
            data = json.loads(prestacao_text[json_start:])
        except (json.JSONDecodeError, ValueError):
            return []

        diffgram = data.get("diffgram", {})
        prestacao = diffgram.get("PrestacaoContas", {})
        raw_despesas = prestacao.get("Despesas", [])
        if not isinstance(raw_despesas, list):
            raw_despesas = [raw_despesas]

        lancamentos = []
        for d in raw_despesas:
            if not isinstance(d, dict):
                continue
            lancamentos.append({
                "numero_lancamento": d.get("numero_lancamento", ""),
                "historico": d.get("historico", ""),
                "valor": d.get("valor", "0"),
                "data": d.get("data", ""),
                "nome_conta": d.get("nome_conta", ""),
                "nome_sub_conta": d.get("nome_sub_conta", ""),
                "tem_docto": d.get("tem_docto", "0") == "1",
                "documentos": [],
            })
        return lancamentos

    # ------------------------------------------------------------------
    # Análise IA via Gemini — por etapa da skill
    # ------------------------------------------------------------------

    async def _build_analysis_context(
        self, session_id: int, skill, lancamentos_result: dict
    ) -> list[Part]:
        """Constrói as Parts compartilhadas: documentos + metadata dos lançamentos."""
        parts: list[Part] = []
        lancamentos = lancamentos_result.get("lancamentos", [])

        # Anexar documentos (imagens/PDFs)
        sources = await self.source_svc.list_by_session(session_id)
        doc_sources = [s for s in sources if s.origin == "gosati" and s.mime_type != "text/plain"]

        doc_count = 0
        for src in doc_sources:
            if doc_count >= 40:
                break
            try:
                file_path = _resolve_path(src.file_path)
                if not file_path.exists():
                    continue
                data = file_path.read_bytes()
                parts.append(Part.from_bytes(data=data, mime_type=src.mime_type))

                # Monta descrição rica do documento
                doc_desc = f"[Documento: {src.label or src.filename}]"

                # Se tem texto extraído (PDF), inclui para o modelo analisar
                if src.text_path:
                    txt_path = _resolve_path(src.text_path)
                    if txt_path.exists():
                        extracted_text = txt_path.read_text(encoding="utf-8")[:2000]
                        # Limpa sequências longas de _/- que contaminam o modelo
                        extracted_text = re.sub(r"[_]{4,}", " ", extracted_text)
                        extracted_text = re.sub(r"[-]{4,}", "---", extracted_text)
                        doc_desc += f"\n[Texto extraído do PDF:\n{extracted_text}\n]"

                parts.append(Part.from_text(text=doc_desc))
                doc_count += 1
            except Exception as e:
                logger.warning("Erro ao ler documento %s: %s", src.filename, e)

        # Anexar exemplos da skill
        for ex in skill.examples:
            try:
                ex_path = _resolve_path(ex.file_path)
                if not ex_path.exists():
                    continue
                ex_data = ex_path.read_bytes()
                parts.append(Part.from_bytes(data=ex_data, mime_type=ex.mime_type))
                parts.append(Part.from_text(
                    text=f"[Exemplo de referência: {ex.filename} — {ex.description}]"
                ))
            except Exception as e:
                logger.warning("Erro ao ler exemplo %s: %s", ex.filename, e)

        # Metadata dos lançamentos
        metadata_lines = []
        for lanc in lancamentos:
            meta = (
                f"### Lancto. {lanc.get('numero_lancamento', '?')}\n"
                f"- **Histórico**: {lanc.get('historico', '')}\n"
                f"- **Valor**: R$ {lanc.get('valor', '0')}\n"
                f"- **Data**: {lanc.get('data', '')}\n"
                f"- **Conta**: {lanc.get('nome_conta', '')}\n"
                f"- **Sub-conta**: {lanc.get('nome_sub_conta', '')}\n"
                f"- **Documentos**: {len(lanc.get('documentos', []))} arquivo(s)\n"
            )
            metadata_lines.append(meta)

        context_text = (
            f"## Dados disponíveis\n\n"
            f"Total: {len(lancamentos)} lançamento(s)\n\n"
            + "\n".join(metadata_lines)
        )
        parts.append(Part.from_text(text=context_text))

        return parts

    async def _run_step_analysis(
        self, skill, step, base_parts: list[Part], lancamentos_result: dict
    ) -> AsyncGenerator[str, None]:
        """Executa uma etapa de análise da skill via Gemini streaming."""
        # System instruction: macro da skill (contexto geral) ou default
        system_instruction = (
            skill.macro_instruction.strip()
            if skill.macro_instruction and skill.macro_instruction.strip()
            else "Você é um analista especializado em condomínios. Analise os dados fornecidos."
        )

        # Prompt específico da etapa
        step_prompt = (
            f"## Etapa de análise: {step.title}\n\n"
            f"**Instrução**: {step.instruction}\n\n"
            f"Analise os lançamentos e documentos fornecidos de acordo com esta instrução. "
            f"Seja objetivo e referência os números dos lançamentos quando relevante."
        )

        parts = list(base_parts) + [Part.from_text(text=step_prompt)]

        try:
            stream = await self._gemini_client.aio.models.generate_content_stream(
                model=self.settings.gemini_model,
                contents=[Content(role="user", parts=parts)],
                config=GenerateContentConfig(
                    system_instruction=system_instruction,
                    max_output_tokens=self.settings.gemini_max_output_tokens,
                    temperature=self.settings.gemini_temperature,
                    frequency_penalty=0.5,
                    presence_penalty=0.3,
                ),
            )
            async for response in stream:
                if response.text:
                    # Sanitiza separadores de tabela markdown com traços infinitos
                    yield re.sub(r"-{4,}", "---", response.text)
        except Exception as e:
            logger.error("Erro na análise IA (step '%s'): %s", step.title, e)
            yield f"\n\n**Erro na análise:** {e}"

    # ------------------------------------------------------------------
    # Auto-fetch GoSATI
    # ------------------------------------------------------------------

    async def _auto_fetch_gosati(self, session_id: int, skill, progress_cb=None, cond_codigo_override: int | None = None) -> None:
        """Auto-fetch GoSATI data + comprovantes based on skill config."""
        session = await self.db.get(Session, session_id)
        if not session:
            return
        # Usa condomínio do auth (override) ou o salvo na sessão
        cond_codigo = cond_codigo_override or session.gosati_condominio_codigo
        if not cond_codigo:
            return
        mes = session.gosati_mes
        ano = session.gosati_ano
        if not mes or not ano:
            return

        try:
            sections = json.loads(skill.gosati_sections)
        except (json.JSONDecodeError, TypeError):
            return
        try:
            filters = json.loads(skill.gosati_filters) if skill.gosati_filters else {}
        except (json.JSONDecodeError, TypeError):
            filters = {}

        # Verifica se já existem sources GoSATI (docs binários) para esta sessão.
        # Se sim, reutiliza — apenas recria o texto filtrado.
        # Isso evita que etapas subsequentes apaguem docs de etapas anteriores.
        sources = await self.source_svc.list_by_session(session_id)
        existing_gosati_docs = [
            s for s in sources
            if s.origin == "gosati" and s.mime_type != "text/plain"
        ]
        existing_gosati_text = [
            s for s in sources
            if s.origin == "gosati" and s.mime_type == "text/plain"
        ]
        has_existing_docs = len(existing_gosati_docs) > 0

        # Só remove o texto filtrado anterior (será recriado com filtros da skill atual)
        if existing_gosati_text:
            deleted_text_ids = {src.id for src in existing_gosati_text}
            for src in existing_gosati_text:
                await self.db.delete(src)
                session.source_count = max(0, session.source_count - 1)
            # Invalidate stale prestacao_source_id refs in etapa results
            await self.source_svc._invalidate_etapa_source_refs(session_id, deleted_text_ids)
            await self.db.commit()

        gosati_svc = GoSatiService(self.db, self.settings)

        # 1. Consulta GoSATI (sempre, para obter dados atualizados e aplicar filtros)
        if progress_cb:
            progress_cb("Consultando GoSATI...")

        raw_data = await gosati_svc.consultar_prestacao_contas(
            condominio=cond_codigo,
            mes=mes,
            ano=ano,
            demonstr_contas=sections.get("contas", False),
            demonstr_despesas=sections.get("despesas", False),
            relat_devedores=sections.get("devedores", False),
            demonstr_receitas=sections.get("receitas", False),
            acompanh_cobranca=sections.get("cobranca", False),
            orcado_gasto=sections.get("orcado_gasto", False),
        )

        if not raw_data:
            logger.warning("GoSATI não retornou dados para sessão %d", session_id)
            return

        # Conta total de despesas para dashboard de cobertura
        try:
            _all = raw_data.get("diffgram", {}).get("PrestacaoContas", {}).get("Despesas", [])
            if not isinstance(_all, list):
                _all = [_all]
            session.gosati_total_despesas = len(_all)
        except Exception:
            pass

        # 2. Extrai despesas com comprovante ANTES de filtrar
        despesas_com_link = gosati_svc.extrair_despesas_com_comprovante(raw_data)

        # 2b. exclude_analyzed: remove lançamentos já analisados por outras etapas
        exclude_analyzed = filters.pop("exclude_analyzed", False) if filters else False

        # 3. Aplica filtros e salva como Source texto
        filtered_data = raw_data
        if filters:
            filtered_data = GoSatiService._apply_filters(raw_data, filters)

        if exclude_analyzed:
            analyzed_nums = await self._get_analyzed_lancamentos(session_id)
            if analyzed_nums:
                diffgram = filtered_data.get("diffgram", {})
                prestacao = diffgram.get("PrestacaoContas", {})
                despesas = prestacao.get("Despesas", [])
                if isinstance(despesas, list):
                    prestacao["Despesas"] = [
                        d for d in despesas
                        if str(d.get("numero_lancamento", "")) not in analyzed_nums
                    ]
                despesas_com_link = [
                    d for d in despesas_com_link
                    if str(d.get("numero_lancamento", "")) not in analyzed_nums
                ]

        from app.services.gosati_service import _dict_to_text, GOSATI_DIR
        label = f"Prestação Filtrada - {mes:02d}/{ano} (Cond. {cond_codigo})"
        text_content = _dict_to_text(filtered_data, label)
        content_bytes = text_content.encode("utf-8")

        save_dir = GOSATI_DIR / str(session_id)
        save_dir.mkdir(parents=True, exist_ok=True)
        filename = f"gosati_filtered_{cond_codigo}_{mes}_{ano}.txt"
        file_path = save_dir / filename
        file_path.write_bytes(content_bytes)

        text_source = Source(
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
        self.db.add(text_source)
        session.source_count += 1
        await self.db.commit()

        # 4. Filtra despesas com comprovante pelos mesmos filtros da Skill (OR multi-campo)
        import unicodedata

        def _strip_accents(text: str) -> str:
            nfkd = unicodedata.normalize("NFKD", text)
            return "".join(c for c in nfkd if not unicodedata.combining(c)).upper()

        filter_fields: dict[str, list[str]] = {}
        for key in ("nome_conta_despesas", "nome_sub_conta", "historico"):
            raw = filters.get(key, [])
            if isinstance(raw, str):
                raw = [raw]
            values = [_strip_accents(v) for v in raw if v.strip()]
            if values:
                filter_fields[key] = values

        if filter_fields:
            def _matches_desp(d: dict) -> bool:
                for field, terms in filter_fields.items():
                    val = _strip_accents(d.get(field, ""))
                    if any(t in val for t in terms):
                        return True
                return False
            despesas_com_link = [d for d in despesas_com_link if _matches_desp(d)]

        # 5. Baixa comprovantes via SOAP (catalogo_id → RetornaArquivo)
        logger.info(
            "Auto-fetch: %d despesas com link após filtros (sessão %d)",
            len(despesas_com_link), session_id,
        )
        # Debug: verifica se 3938352 está incluído
        _debug_lancs = [str(d.get("numero_lancamento","")) for d in despesas_com_link]
        if "3938352" in _debug_lancs:
            _d = next(d for d in despesas_com_link if str(d.get("numero_lancamento",""))=="3938352")
            logger.info("DEBUG 3938352 INCLUÍDO: catalogo_id=%s", _d.get("catalogo_id",""))
        else:
            logger.info("DEBUG 3938352 NÃO ESTÁ em despesas_com_link")
        if despesas_com_link:
            if has_existing_docs:
                # Mapa de lançamentos locais (existentes) e da origem (GoSATI)
                existing_lanc_nums = set()
                existing_lanc_sources: dict[str, list[Source]] = {}
                for src in existing_gosati_docs:
                    m = re.search(r"Lanç\.(\d+)", src.label or "")
                    if m:
                        lanc = m.group(1)
                        existing_lanc_nums.add(lanc)
                        existing_lanc_sources.setdefault(lanc, []).append(src)

                gosati_lanc_nums = set(
                    str(d.get("numero_lancamento", ""))
                    for d in despesas_com_link
                )

                # Docs novos no GoSATI que ainda não temos localmente
                missing = [
                    d for d in despesas_com_link
                    if str(d.get("numero_lancamento", "")) not in existing_lanc_nums
                ]

                # Docs locais cujo lançamento não existe mais no GoSATI (removidos na origem)
                orphaned_lancs = existing_lanc_nums - gosati_lanc_nums
                orphaned_sources: list[Source] = []
                for lanc in orphaned_lancs:
                    orphaned_sources.extend(existing_lanc_sources.get(lanc, []))

                logger.info(
                    "Auto-fetch: despesas_com_link=%d, existing_lanc=%d, missing=%d, orphaned=%d",
                    len(despesas_com_link), len(existing_lanc_nums),
                    len(missing), len(orphaned_sources),
                )

                # Remove docs órfãos (comprovantes removidos na origem)
                if orphaned_sources:
                    for src in orphaned_sources:
                        logger.info(
                            "Auto-fetch: removendo doc órfão id=%s label='%s' (sessão %d)",
                            src.id, src.label, session_id,
                        )
                        for path in [src.file_path, src.text_path]:
                            if path:
                                try:
                                    os.remove(path)
                                except FileNotFoundError:
                                    pass
                        await self.db.delete(src)
                        session.source_count = max(0, session.source_count - 1)
                    await self.db.commit()
                    if progress_cb:
                        progress_cb(f"Removidos {len(orphaned_sources)} comprovante(s) não mais presentes no GoSATI...")

                if missing:
                    if progress_cb:
                        progress_cb(f"Baixando {len(missing)} comprovante(s) faltante(s)...")
                    saved = await gosati_svc.save_comprovantes_as_sources(
                        session_id=session_id,
                        despesas=missing,
                        gemini_client=self._gemini_client,
                    )
                    logger.info(
                        "Auto-fetch: %d comprovantes complementares para sessão %d",
                        len(saved), session_id,
                    )
                elif not orphaned_sources:
                    if progress_cb:
                        progress_cb(f"Reutilizando {len(existing_gosati_docs)} comprovantes existentes...")
                    logger.info(
                        "Auto-fetch: reutilizando %d docs existentes para sessão %d",
                        len(existing_gosati_docs), session_id,
                    )
            else:
                if progress_cb:
                    progress_cb(f"Baixando comprovantes de {len(despesas_com_link)} lançamento(s)...")
                saved = await gosati_svc.save_comprovantes_as_sources(
                    session_id=session_id,
                    despesas=despesas_com_link,
                    gemini_client=self._gemini_client,
                )
                logger.info(
                    "Auto-fetch: %d comprovantes baixados para sessão %d",
                    len(saved), session_id,
                )

        elif has_existing_docs:
            # Nenhuma despesa com comprovante no GoSATI, mas temos docs locais
            # → todos os comprovantes foram removidos na origem
            logger.info(
                "Auto-fetch: GoSATI retornou 0 despesas com comprovante, "
                "mas existem %d docs locais — removendo todos (sessão %d)",
                len(existing_gosati_docs), session_id,
            )
            for src in existing_gosati_docs:
                logger.info(
                    "Auto-fetch: removendo doc órfão id=%s label='%s' (sessão %d)",
                    src.id, src.label, session_id,
                )
                for path in [src.file_path, src.text_path]:
                    if path:
                        try:
                            os.remove(path)
                        except FileNotFoundError:
                            pass
                await self.db.delete(src)
                session.source_count = max(0, session.source_count - 1)
            await self.db.commit()
            if progress_cb:
                progress_cb(f"Removidos {len(existing_gosati_docs)} comprovante(s) — não há mais comprovantes no GoSATI")

        logger.info(
            "Auto-fetch GoSATI para etapa sessão %d (skill %s, cond %d, %02d/%d) — "
            "%d despesas com comprovante",
            session_id, skill.name, cond_codigo, mes, ano,
            len(despesas_com_link),
        )

    # ------------------------------------------------------------------
    # Execução por Critérios Estruturados
    # ------------------------------------------------------------------

    async def _execute_criteria(
        self,
        session_id: int,
        skill,
        lancamentos_result: dict,
        progress_cb=None,
    ) -> dict:
        """Executa critérios estruturados da skill sobre os lançamentos."""
        lancamentos = lancamentos_result.get("lancamentos", [])
        docs_by_lanc = await self._load_docs_by_lancamento(session_id, lancamentos)

        engine = CriteriaEngine(self._gemini_client, self.settings)
        result = await engine.execute(
            criteria=skill.criteria,
            lancamentos=lancamentos,
            docs_by_lancamento=docs_by_lanc,
            progress_cb=progress_cb,
        )
        return result.model_dump()

    async def _load_docs_by_lancamento(
        self, session_id: int, lancamentos: list[dict]
    ) -> dict[str, list[dict]]:
        """Carrega documentos por lançamento com texto extraído e file_path."""
        sources = await self.source_svc.list_by_session(session_id)
        doc_sources = [s for s in sources if s.origin == "gosati" and s.mime_type != "text/plain"]

        docs_by_lanc: dict[str, list[dict]] = {}

        for src in doc_sources:
            doc_info = {
                "source_id": src.id,
                "label": src.label or src.filename,
                "filename": src.filename,
                "mime_type": src.mime_type,
                "file_path": src.file_path,
            }
            # Carrega texto extraído se disponível
            if src.text_path:
                txt_path = _resolve_path(src.text_path)
                if txt_path.exists():
                    try:
                        doc_info["texto_extraido"] = txt_path.read_text(encoding="utf-8")[:3000]
                    except Exception:
                        pass

            # Associa ao lançamento pelo nº no label
            m = re.search(r"Lanç\.(\d+)", src.label or "")
            if m:
                lanc_num = m.group(1)
                docs_by_lanc.setdefault(lanc_num, []).append(doc_info)

        return docs_by_lanc

    async def _get_analyzed_lancamentos(self, session_id: int) -> set[str]:
        """Retorna set de numero_lancamento já analisados em etapas 'done' desta sessão."""
        from sqlmodel import select
        from app.models.etapa import Etapa

        result = await self.db.execute(
            select(Etapa).where(
                Etapa.session_id == session_id,
                Etapa.status == "done",
            )
        )
        analyzed = set()
        for etapa in result.scalars().all():
            if not etapa.result_text:
                continue
            try:
                data = json.loads(etapa.result_text)
                for lanc in data.get("lancamentos", []):
                    num = str(lanc.get("numero_lancamento", ""))
                    if num:
                        analyzed.add(num)
            except (json.JSONDecodeError, KeyError):
                pass
        return analyzed
