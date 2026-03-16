"""Database engine e inicialização com SQLModel async."""
import logging

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()
engine = create_async_engine(
    settings.database_url,
    echo=False,
    connect_args={"timeout": 30},
)
async_session_maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# WAL mode + busy_timeout para suportar concorrência (app + worker)
@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragmas(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


async def _migrate_add_columns(conn) -> None:
    """Add new columns to existing tables (SQLite-safe)."""
    columns = [
        ("sessions", "gosati_query_type", "VARCHAR"),
        ("sessions", "gosati_condominio_codigo", "INTEGER"),
        ("sessions", "gosati_condominio_nome", "VARCHAR"),
        ("sessions", "gosati_mes", "INTEGER"),
        ("sessions", "gosati_ano", "INTEGER"),
        ("skills", "execution_mode", "VARCHAR DEFAULT 'chat'"),
        ("skills", "gosati_sections", "TEXT"),
        ("skills", "gosati_filters", "TEXT"),
        ("auth_sessions", "selected_cond_codigo", "INTEGER"),
        ("auth_sessions", "selected_cond_nome", "VARCHAR"),
        ("auth_sessions", "role", "VARCHAR DEFAULT 'user'"),
    ]
    for table, column, col_type in columns:
        try:
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
            logger.info("Migration: added %s.%s", table, column)
        except Exception:
            pass  # column already exists

    # Marca skills de conferência com execution_mode correto
    try:
        await conn.execute(text(
            "UPDATE skills SET execution_mode = 'conferencia' "
            "WHERE execution_mode = 'chat' AND "
            "(name LIKE '%prestação%' OR name LIKE '%prestacao%')"
        ))
    except Exception:
        pass


async def _seed_admin_roles(conn) -> None:
    """Garante que emails de ADMIN_EMAILS existam na tabela user_roles."""
    admin_list = [e.strip().lower() for e in settings.admin_emails.split(",") if e.strip()]
    for email in admin_list:
        try:
            existing = await conn.execute(
                text("SELECT id FROM user_roles WHERE user_email = :email"),
                {"email": email},
            )
            if not existing.first():
                await conn.execute(
                    text("INSERT INTO user_roles (user_email, role, updated_at) VALUES (:email, 'admin', datetime('now'))"),
                    {"email": email},
                )
                logger.info("Seed: admin role for %s", email)
        except Exception:
            pass


async def init_db():
    """Cria todas as tabelas no banco e aplica migrações."""
    from app.models import Skill, SkillStep, SkillExample, Session, Source, ChatMessage, AuthSession, AuditLog, UserRole  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
        await _migrate_add_columns(conn)
        await _seed_admin_roles(conn)


async def get_db() -> AsyncSession:
    """Dependency do FastAPI — fornece sessão do banco."""
    async with async_session_maker() as session:
        yield session
