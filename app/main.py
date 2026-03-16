"""Inicialização do FastAPI — Notebook Zang."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.dependencies import require_auth
from app.core.exception_handlers import register_handlers
from app.core.http_client import close_client, init_client
from app.core.redis import close_redis
from app.models.base import init_db
from app.routers import audit, auth, chat, condominios, conferencia, etapas, gosati, pages, pipeline, sessions, skills, sources

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_client()
    await init_db()
    yield
    await close_redis()
    await close_client()


app = FastAPI(
    title="Notebook Zang",
    description="Notebook com Skills customizáveis para análise de dados",
    version="0.1.0",
    lifespan=lifespan,
)

register_handlers(app)

# Static files
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# Auth API (public)
app.include_router(auth.router, prefix="/api/v1")

# Protected API routes (require auth)
app.include_router(skills.router, prefix="/api/v1", dependencies=[Depends(require_auth)])
app.include_router(sessions.router, prefix="/api/v1", dependencies=[Depends(require_auth)])
app.include_router(sources.router, prefix="/api/v1", dependencies=[Depends(require_auth)])
app.include_router(chat.router, prefix="/api/v1", dependencies=[Depends(require_auth)])
app.include_router(gosati.router, prefix="/api/v1", dependencies=[Depends(require_auth)])
app.include_router(gosati.gosati_utils_router, prefix="/api/v1", dependencies=[Depends(require_auth)])
app.include_router(condominios.router, prefix="/api/v1", dependencies=[Depends(require_auth)])
app.include_router(conferencia.router, prefix="/api/v1", dependencies=[Depends(require_auth)])
app.include_router(etapas.router, prefix="/api/v1", dependencies=[Depends(require_auth)])
app.include_router(pipeline.router, prefix="/api/v1", dependencies=[Depends(require_auth)])
app.include_router(audit.router, prefix="/api/v1", dependencies=[Depends(require_auth)])

# HTML pages (auth handled per-route in pages.py)
app.include_router(pages.router)


@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "ok"}
