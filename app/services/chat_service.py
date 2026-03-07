"""Serviço de chat com Gemini — integra Skills e Sources."""
import asyncio
import json
import logging
from collections import defaultdict
from typing import AsyncGenerator

from google import genai
from google.genai import types as genai_types
from google.genai.types import Content, Part
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.config import Settings
from app.models.chat_message import ChatMessage as ChatMessageRecord
from app.models.session import Session
from app.services.gosati_service import GoSatiService
from app.services.skill_service import SkillService
from app.services.source_service import SourceService

logger = logging.getLogger(__name__)

# Cache em memória (por session) — apenas para docs e contexto Gemini
_document_cache: dict[int, dict[int, dict]] = defaultdict(dict)
_sent_docs: dict[int, set[int]] = defaultdict(set)  # docs já enviados ao Gemini
_gemini_contents: dict[int, list[Content]] = defaultdict(list)  # contexto Gemini em memória

# Limite por lote de binários (imagens/PDFs). PDFs com texto extraído
# são enviados como texto e não contam nesses limites.
MAX_BINARY_BYTES_PER_TURN = 15 * 1024 * 1024  # 15 MB por lote
MAX_BINARY_FILES_PER_TURN = 40               # máx arquivos por lote


def _build_batches(
    binary_ids: list[int], doc_cache: dict[int, dict]
) -> list[list[int]]:
    """Divide IDs de docs binários em lotes por tamanho e quantidade."""
    batches: list[list[int]] = []
    current: list[int] = []
    current_size = 0
    for src_id in binary_ids:
        doc = doc_cache.get(src_id)
        if not doc:
            continue
        size = len(doc["content"])
        if current and (
            current_size + size > MAX_BINARY_BYTES_PER_TURN
            or len(current) >= MAX_BINARY_FILES_PER_TURN
        ):
            batches.append(current)
            current = []
            current_size = 0
        current.append(src_id)
        current_size += size
    if current:
        batches.append(current)
    return batches


def clear_session_cache(session_id: int) -> None:
    """Limpa todo o cache em memória de uma sessão (docs, sent, contexto Gemini)."""
    _gemini_contents.pop(session_id, None)
    _document_cache.pop(session_id, None)
    _sent_docs.pop(session_id, None)
    logger.info("Cache em memória limpo para sessão %d", session_id)


class ChatService:
    def __init__(self, db: AsyncSession, settings: Settings):
        self.db = db
        self.settings = settings
        self.skill_svc = SkillService(db)
        self.source_svc = SourceService(db)

    async def chat_stream(
        self, session_id: int, message: str
    ) -> AsyncGenerator[str, None]:
        """Chat livre (sem skill ativa)."""
        async for chunk in self._generate(session_id, message, skill_id=None):
            yield chunk

    async def chat_with_skill(
        self, session_id: int, skill_id: int, message: str
    ) -> AsyncGenerator[str, None]:
        """Chat com skill ativa — processa em lotes se houver muitos binários."""
        # Cada execução de skill = contexto LIMPO.
        # Evita degradação por acúmulo de análises anteriores na mesma sessão.
        await self.clear_history(session_id)

        # Pré-carrega cache de documentos (fontes da sessão, não histórico de chat)
        sources = await self.source_svc.list_by_session(session_id)
        for src in sources:
            if src.id not in _document_cache.get(session_id, {}):
                try:
                    content, mime_type = self.source_svc.get_content_for_llm(src)
                    _document_cache[session_id][src.id] = {
                        "content": content,
                        "mime_type": mime_type,
                        "filename": src.filename,
                        "label": src.label or src.filename,
                    }
                except Exception as e:
                    logger.warning(f"Erro ao ler source {src.id}: {e}")

        # Identifica binários e divide em lotes
        binary_ids = [
            src_id
            for src_id, doc in _document_cache.get(session_id, {}).items()
            if isinstance(doc["content"], bytes)
        ]
        batches = _build_batches(binary_ids, _document_cache.get(session_id, {}))

        if len(batches) <= 1:
            # Volume normal — fluxo único
            async for chunk in self._generate(session_id, message, skill_id=skill_id):
                yield chunk
            return

        # --- Processamento em múltiplos lotes ---
        total_mb = sum(
            len(_document_cache[session_id][sid]["content"])
            for sid in binary_ids
            if sid in _document_cache.get(session_id, {})
        ) / 1024 / 1024
        logger.info(
            "Sessão %d: %d binários (%.1f MB) em %d lotes",
            session_id, len(binary_ids), total_mb, len(batches),
        )

        # IDs dos documentos de texto (leves) — só devem ir no lote final,
        # não nos intermediários, para evitar que o Gemini liste todos os
        # lançamentos da relação e marque como "comprovante não disponível"
        text_doc_ids = {
            src_id
            for src_id, doc in _document_cache.get(session_id, {}).items()
            if not isinstance(doc["content"], bytes)
        }

        # Salva comprimento do contexto ANTES dos lotes intermediários
        # para colapsar o histórico antes do lote final
        pre_batch_len = len(_gemini_contents[session_id])

        all_binary_ids = set(binary_ids)
        intermediate_analyses: list[str] = []

        for batch_idx, batch_ids in enumerate(batches):
            is_last = batch_idx == len(batches) - 1
            batch_set = set(batch_ids)

            # Marca temporariamente lotes futuros como "enviados" para que
            # _generate() inclua apenas o lote atual
            already_sent = set(_sent_docs.get(session_id, set()))
            future_ids = all_binary_ids - batch_set - already_sent
            _sent_docs[session_id].update(future_ids)

            try:
                if is_last:
                    # Colapsa histórico intermediário: substitui por resumo compacto
                    # para que o lote final veja contexto limpo + skill prompt
                    _gemini_contents[session_id] = _gemini_contents[session_id][:pre_batch_len]
                    if intermediate_analyses:
                        combined = "\n\n".join(intermediate_analyses)
                        _gemini_contents[session_id].append(
                            Content(role="user", parts=[Part(text=(
                                "[Tabela de comprovantes extraídos nos lotes anteriores — "
                                "use estes dados para cruzar com a relação de lançamentos "
                                "e gerar o relatório final:]\n\n"
                                f"{combined}"
                            ))])
                        )
                        _gemini_contents[session_id].append(
                            Content(role="model", parts=[Part(text=(
                                "Tabela dos lotes anteriores registrada. "
                                "Prosseguindo com o relatório final."
                            ))])
                        )

                    async for chunk in self._generate(session_id, message, skill_id=skill_id):
                        yield chunk

                else:
                    # Lotes intermediários: suprime docs de texto para que o Gemini
                    # veja APENAS os comprovantes binários desta mensagem
                    _sent_docs[session_id].update(text_doc_ids)

                    yield f"data: {json.dumps({'progress': f'Analisando documentos — lote {batch_idx + 1} de {len(batches)}...'})}\n\n"

                    # Injeta metadados dos lançamentos deste lote para que o Gemini
                    # possa correlacionar sem depender dos text docs completos
                    meta_lines = []
                    for src_id in batch_ids:
                        doc = _document_cache.get(session_id, {}).get(src_id)
                        if doc:
                            meta_lines.append(f"  - {doc.get('label') or doc['filename']}")
                    meta_header = (
                        "Metadados dos comprovantes neste lote:\n" + "\n".join(meta_lines) + "\n\n"
                        if meta_lines else ""
                    )

                    batch_msg = (
                        f"{meta_header}"
                        "Para cada comprovante (imagem ou PDF) visível acima, extraia os dados "
                        "em formato de tabela com as colunas:\n"
                        "| Nº Lançamento | Beneficiário/Favorecido | Valor | Data | Tipo (NF/DARF/Boleto/GPS/Outro) |\n"
                        "Inclua apenas comprovantes visíveis. Sem narrativa, apenas a tabela."
                    )

                    async for chunk in self._generate(session_id, batch_msg, skill_id=None):
                        if '"error"' in chunk:
                            yield chunk
                            return
                        # descarta texto ao cliente — contexto salvo internamente

                    # Coleta resposta do modelo (tabela estruturada) para o resumo final
                    ctx = _gemini_contents.get(session_id, [])
                    if ctx and ctx[-1].role == "model":
                        parts = ctx[-1].parts
                        if parts and hasattr(parts[0], "text") and parts[0].text:
                            intermediate_analyses.append(
                                f"=== Lote {batch_idx + 1}/{len(batches)} ===\n{parts[0].text}"
                            )

            finally:
                # Restaura: remove IDs futuros marcados temporariamente
                _sent_docs[session_id].difference_update(future_ids)
                # Restaura docs de texto (disponíveis para o lote final)
                if not is_last:
                    _sent_docs[session_id].difference_update(text_doc_ids)

    async def _ensure_gemini_context(self, session_id: int) -> None:
        """Carrega histórico do banco para o contexto Gemini se ainda não estiver em memória."""
        if _gemini_contents.get(session_id):
            return  # já carregado
        stmt = (
            select(ChatMessageRecord)
            .where(ChatMessageRecord.session_id == session_id)
            .order_by(ChatMessageRecord.created_at)
        )
        result = await self.db.execute(stmt)
        messages = result.scalars().all()
        for msg in messages:
            _gemini_contents[session_id].append(
                Content(role=msg.role, parts=[Part(text=msg.text)])
            )

    async def _save_message(self, session_id: int, role: str, text: str) -> None:
        """Salva uma mensagem no banco."""
        record = ChatMessageRecord(session_id=session_id, role=role, text=text)
        self.db.add(record)
        await self.db.commit()

    async def _auto_fetch_gosati(self, session_id: int, skill) -> None:
        """Auto-fetch GoSATI data based on skill config. Replaces existing GoSATI sources."""
        session = await self.db.get(Session, session_id)
        if not session or not session.gosati_condominio_codigo:
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

        # Remove sources GoSATI anteriores (manuais ou de outra skill)
        sources = await self.source_svc.list_by_session(session_id)
        for src in sources:
            if src.origin == "gosati":
                await self.db.delete(src)
                session.source_count = max(0, session.source_count - 1)
        await self.db.commit()

        # Limpa cache de docs em memória (fontes antigas removidas)
        _document_cache.pop(session_id, None)
        _sent_docs.pop(session_id, None)

        gosati_svc = GoSatiService(self.db, self.settings)
        await gosati_svc.query_filtered_as_source(
            session_id=session_id,
            condominio=session.gosati_condominio_codigo,
            mes=mes,
            ano=ano,
            sections=sections,
            filters=filters,
        )
        logger.info(
            "Auto-fetch GoSATI para sessão %d (skill %s, cond %d, %02d/%d)",
            session_id, skill.name, session.gosati_condominio_codigo, mes, ano,
        )

    async def _generate(
        self, session_id: int, message: str, skill_id: int | None
    ) -> AsyncGenerator[str, None]:
        """Gera resposta via Gemini com streaming."""
        # Garante que o contexto Gemini está carregado do banco
        await self._ensure_gemini_context(session_id)

        # Monta system instruction
        system_instruction = "Você é um assistente especializado em análise de dados."
        skill = None
        if skill_id:
            skill = await self.skill_svc.get_by_id(skill_id)
            skill_prompt = await self.skill_svc.build_prompt(skill_id)
            system_instruction = skill_prompt

            # Auto-fetch GoSATI se a Skill define gosati_sections
            if skill.gosati_sections:
                await self._auto_fetch_gosati(session_id, skill)

        # Instrução anti-repetição: evita loops ao transcrever códigos de barras/boletos
        system_instruction += (
            "\n\nREGRA OBRIGATÓRIA: Nunca reproduza códigos de barras, linhas digitáveis, "
            "chaves PIX longas, sequências numéricas extensas ou qualquer outro dado "
            "que seja apenas uma longa sequência de dígitos. "
            "Para comprovantes bancários, registre apenas: tipo do comprovante, "
            "beneficiário/favorecido, valor e data. Jamais transcreva a linha digitável completa."
        )

        # Injeta contexto do condomínio se houver seleção GoSATI
        session = await self.db.get(Session, session_id)
        if session and session.gosati_condominio_codigo:
            cond_context = (
                f"\nO condomínio em análise é: {session.gosati_condominio_codigo}"
                f" — {session.gosati_condominio_nome or 'N/A'}"
                f" (período {session.gosati_mes or '?'}/{session.gosati_ano or '?'})."
            )
            system_instruction += cond_context

        # Carrega documentos da sessão (usa get_content_for_llm para conversão)
        sources = await self.source_svc.list_by_session(session_id)
        for src in sources:
            if src.id not in _document_cache.get(session_id, {}):
                try:
                    content, mime_type = self.source_svc.get_content_for_llm(src)
                    _document_cache[session_id][src.id] = {
                        "content": content,
                        "mime_type": mime_type,
                        "filename": src.filename,
                        "label": src.label or src.filename,
                    }
                except Exception as e:
                    logger.warning(f"Erro ao ler source {src.id}: {e}")

        # Monta partes dos documentos que ainda não foram enviados
        # Separa texto (leve) de binário (pesado) e aplica limites
        doc_parts = []
        text_docs = []
        binary_docs = []
        docs_in_this_turn: set[int] = set()  # para rollback em caso de erro
        for src_id, doc in _document_cache.get(session_id, {}).items():
            if src_id not in _sent_docs.get(session_id, set()):
                if isinstance(doc["content"], bytes):
                    binary_docs.append((src_id, doc))
                else:
                    text_docs.append((src_id, doc))

        # Texto sempre vai (leve) — usa label enriquecido quando disponível
        for src_id, doc in text_docs:
            doc_label = doc.get("label") or doc["filename"]
            doc_parts.append(Part(text=f"[Documento: {doc_label}]\n{doc['content']}"))
            _sent_docs[session_id].add(src_id)
            docs_in_this_turn.add(src_id)

        # Binários com limite de tamanho e quantidade
        binary_total = 0
        binary_count = 0
        skipped_names = []
        for src_id, doc in binary_docs:
            size = len(doc["content"])
            if (binary_total + size > MAX_BINARY_BYTES_PER_TURN
                    or binary_count >= MAX_BINARY_FILES_PER_TURN):
                skipped_names.append(doc.get("label") or doc["filename"])
                _sent_docs[session_id].add(src_id)  # marca como "enviado" para não ficar preso
                docs_in_this_turn.add(src_id)
                continue
            # Inclui label como contexto antes da imagem/PDF binário
            doc_label = doc.get("label") or doc["filename"]
            doc_parts.append(Part(text=f"[Comprovante: {doc_label}]"))
            doc_parts.append(Part.from_bytes(data=doc["content"], mime_type=doc["mime_type"]))
            binary_total += size
            binary_count += 1
            _sent_docs[session_id].add(src_id)
            docs_in_this_turn.add(src_id)

        if skipped_names:
            doc_parts.append(Part(text=(
                f"[ATENÇÃO: {len(skipped_names)} comprovante(s) binário(s) NÃO foram incluídos "
                f"por limite de tamanho. NÃO analise, NÃO invente e NÃO extrapole dados sobre "
                f"comprovantes que não foram fornecidos. Analise SOMENTE os documentos acima. "
                f"Se um lançamento não possui comprovante visível, registre como 'comprovante não disponível'.]"
            )))
            logger.warning(
                "Sessão %d: %d binários omitidos (limite %d MB / %d arquivos)",
                session_id, len(skipped_names),
                MAX_BINARY_BYTES_PER_TURN // (1024*1024), MAX_BINARY_FILES_PER_TURN,
            )

        # Monta mensagem do usuário com docs novos
        user_parts = doc_parts + [Part(text=message)]
        _gemini_contents[session_id].append(
            Content(role="user", parts=user_parts)
        )

        # Salva mensagem do usuário no banco
        await self._save_message(session_id, "user", message)

        # Client com retry nativo do SDK e endpoint global
        client = genai.Client(
            vertexai=True,
            project=self.settings.gcp_project_id,
            location=self.settings.gemini_location,
            http_options=genai_types.HttpOptions(
                timeout=180_000,  # 3 minutos
                retry_options=genai_types.HttpRetryOptions(
                    attempts=5,
                    initial_delay=2.0,
                    max_delay=60.0,
                    http_status_codes=[408, 429, 500, 502, 503, 504],
                ),
            ),
        )

        try:
            response = client.models.generate_content_stream(
                model=self.settings.gemini_model,
                contents=_gemini_contents[session_id],
                config={
                    "system_instruction": system_instruction,
                    "temperature": self.settings.gemini_temperature,
                    "max_output_tokens": self.settings.gemini_max_output_tokens,
                    "frequency_penalty": 0.5,  # penaliza repetição de tokens
                    "presence_penalty": 0.3,   # penaliza tokens já usados
                },
            )

            full_response = ""
            for chunk in response:
                if chunk.text:
                    full_response += chunk.text
                    yield f"data: {json.dumps({'text': chunk.text})}\n\n"

            # Substitui a mensagem do usuário no histórico por versão texto-only:
            # remove os binários/docs para evitar acúmulo de tokens no contexto
            if doc_parts:
                _gemini_contents[session_id][-1] = Content(
                    role="user", parts=[Part(text=message)]
                )

            # Salva resposta no contexto Gemini e no banco
            _gemini_contents[session_id].append(
                Content(role="model", parts=[Part(text=full_response)])
            )
            await self._save_message(session_id, "model", full_response)
            yield "data: [DONE]\n\n"

        except Exception as e:
            logger.error(f"Erro no Gemini: {e}")
            # Remove a mensagem do usuário do contexto Gemini se falhou
            if _gemini_contents[session_id]:
                _gemini_contents[session_id].pop()
            # Reverte _sent_docs para que os docs sejam re-enviados no retry
            _sent_docs.get(session_id, set()).difference_update(docs_in_this_turn)
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    async def get_history(self, session_id: int) -> list[dict]:
        """Retorna histórico do chat persistido no banco."""
        stmt = (
            select(ChatMessageRecord)
            .where(ChatMessageRecord.session_id == session_id)
            .order_by(ChatMessageRecord.created_at)
        )
        result = await self.db.execute(stmt)
        messages = result.scalars().all()
        return [{"role": msg.role, "text": msg.text} for msg in messages]

    async def clear_history(self, session_id: int) -> None:
        """Remove todas as mensagens do chat de uma sessão do banco e da memória."""
        stmt = select(ChatMessageRecord).where(ChatMessageRecord.session_id == session_id)
        result = await self.db.execute(stmt)
        messages = result.scalars().all()
        for msg in messages:
            await self.db.delete(msg)
        await self.db.commit()
        clear_session_cache(session_id)
