"""Serviço de upload e gerenciamento de Sources — com conversão automática."""
import logging
import os
import re
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.config import BASE_DIR
from app.core.exceptions import NotFoundError
from app.models.session import Session
from app.models.source import Source
from app.services.document_converter import (
    convert_to_text,
    extract_text_from_pdf,
    is_supported,
    needs_conversion,
)

logger = logging.getLogger(__name__)

UPLOADS_DIR = BASE_DIR / "data" / "uploads"


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


class SourceService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_by_session(self, session_id: int) -> list[Source]:
        result = await self.db.execute(
            select(Source).where(Source.session_id == session_id).order_by(Source.created_at)
        )
        return result.scalars().all()

    async def upload(self, session_id: int, file: UploadFile) -> Source:
        # Valida session
        session = await self.db.get(Session, session_id)
        if not session:
            raise NotFoundError(404, f"Session {session_id} não encontrada")

        filename = file.filename or "arquivo"

        # Salva arquivo original em disco
        upload_dir = UPLOADS_DIR / str(session_id)
        upload_dir.mkdir(parents=True, exist_ok=True)
        file_path = upload_dir / filename
        content = await file.read()
        file_path.write_bytes(content)

        # Conversão automática
        text_path = ""
        is_native = True

        if needs_conversion(filename):
            # XLSX, DOCX, HTML → converte para .txt
            is_native = False
            try:
                extracted = convert_to_text(content, filename)
                txt_file = file_path.with_suffix(".converted.txt")
                txt_file.write_text(extracted, encoding="utf-8")
                text_path = str(txt_file)
                logger.info(f"Convertido {filename} → {len(extracted)} chars")
            except Exception as e:
                logger.error(f"Falha na conversão de {filename}: {e}")

        elif Path(filename).suffix.lower() == ".pdf":
            # PDF: Gemini lê direto, mas extrai texto como backup
            try:
                extracted = extract_text_from_pdf(content)
                if extracted.strip():
                    txt_file = file_path.with_suffix(".extracted.txt")
                    txt_file.write_text(extracted, encoding="utf-8")
                    text_path = str(txt_file)
            except Exception as e:
                logger.warning(f"Extração PDF falhou: {e}")

        source = Source(
            session_id=session_id,
            filename=filename,
            file_path=str(file_path),
            mime_type=file.content_type or "application/octet-stream",
            size_bytes=len(content),
            origin="upload",
            label=filename,
            text_path=text_path,
            is_native=is_native,
        )
        self.db.add(source)

        session.source_count += 1
        await self.db.commit()
        await self.db.refresh(source)
        return source

    async def delete(self, session_id: int, source_id: int) -> None:
        source = await self.db.get(Source, source_id)
        if not source or source.session_id != session_id:
            raise NotFoundError(404, f"Source {source_id} não encontrada")

        # Remove arquivos do disco (original + convertido)
        for path in [source.file_path, source.text_path]:
            if path:
                try:
                    os.remove(path)
                except FileNotFoundError:
                    pass

        session = await self.db.get(Session, session_id)
        if session and session.source_count > 0:
            session.source_count -= 1

        await self.db.delete(source)
        await self.db.commit()

    async def delete_by_origin(self, session_id: int, origin: str) -> int:
        """Remove todas as sources de uma sessão com determinada origin."""
        sources = await self.list_by_session(session_id)
        count = 0
        for source in sources:
            if source.origin == origin:
                for path in [source.file_path, source.text_path]:
                    if path:
                        try:
                            os.remove(path)
                        except FileNotFoundError:
                            pass
                await self.db.delete(source)
                count += 1

        if count:
            session = await self.db.get(Session, session_id)
            if session:
                session.source_count = max(0, session.source_count - count)
            await self.db.commit()
        return count

    def get_content_for_llm(self, source: Source) -> tuple[bytes | str, str]:
        """Retorna o conteúdo que deve ser enviado ao Gemini.

        Para texto (text/*, csv, json, xml, txt): string UTF-8 (leve, sem limite)
        Para nativos binários (PDF, imagens): bytes do original + mime_type
        Para convertidos (xlsx, docx): texto extraído + text/plain
        """
        # Se tem texto extraído/convertido, usa ele (leve)
        if source.text_path:
            return _resolve_path(source.text_path).read_text(encoding="utf-8"), "text/plain"

        if source.is_native and source.file_path:
            resolved = _resolve_path(source.file_path)
            # Arquivos text/* devem ser retornados como string, não bytes
            if source.mime_type and source.mime_type.startswith("text/"):
                return resolved.read_text(encoding="utf-8", errors="replace"), "text/plain"
            return resolved.read_bytes(), source.mime_type

        if source.file_path:
            return _resolve_path(source.file_path).read_bytes(), source.mime_type

        return "", "text/plain"
