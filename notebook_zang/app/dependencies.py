"""Injeção de dependência — FastAPI Depends."""
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models.base import get_db
from app.services.skill_service import SkillService
from app.services.session_service import SessionService
from app.services.source_service import SourceService


def get_skill_service(db: AsyncSession = Depends(get_db)) -> SkillService:
    return SkillService(db)


def get_session_service(db: AsyncSession = Depends(get_db)) -> SessionService:
    return SessionService(db)


def get_source_service(db: AsyncSession = Depends(get_db)) -> SourceService:
    return SourceService(db)
