"""ARQ Worker — processa jobs de pipeline em background."""
import asyncio
import logging

from arq import create_pool, cron
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.models.base import init_db, async_session_maker
from app.services.pipeline_service import execute_pipeline_job, execute_single_etapa_job

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


async def run_pipeline(ctx: dict, session_id: int, etapa_ids: list[int]) -> str:
    """ARQ job wrapper para execute_pipeline_job."""
    logger.info("Worker: iniciando pipeline sessão %d (%d etapas)", session_id, len(etapa_ids))
    await execute_pipeline_job(session_id, etapa_ids)
    return f"Pipeline sessão {session_id} finalizado"


async def run_single_etapa(ctx: dict, session_id: int, etapa_id: int) -> str:
    """ARQ job wrapper para execução individual de etapa."""
    logger.info("Worker: executando etapa %d (sessão %d)", etapa_id, session_id)
    await execute_single_etapa_job(session_id, etapa_id)
    return f"Etapa {etapa_id} finalizada"


async def startup(ctx: dict) -> None:
    """Inicialização do worker — conecta ao banco."""
    logger.info("Worker: inicializando...")
    await init_db()
    logger.info("Worker: pronto")


async def sync_condominios(ctx: dict) -> str:
    """Cron job: sincroniza condomínios com BD FOR ALL."""
    logger.info("Worker cron: sincronizando condomínios...")
    try:
        from app.services.condominio_service import CondominioService
        settings = get_settings()
        async with async_session_maker() as db:
            svc = CondominioService(db)
            result = await svc.sync_from_bdforall(settings)
        logger.info("Worker cron: sync finalizado — %s", result)
        return f"Sync: {result['criados']} criados, {result['atualizados']} atualizados, {result['total']} total"
    except Exception:
        logger.exception("Worker cron: falha ao sincronizar condomínios")
        return "Sync: falhou"


async def shutdown(ctx: dict) -> None:
    """Cleanup do worker."""
    logger.info("Worker: encerrando...")


def _parse_redis_url(url: str) -> RedisSettings:
    """Converte redis URL para RedisSettings do ARQ."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    return RedisSettings(
        host=parsed.hostname or "redis",
        port=parsed.port or 6379,
        database=int(parsed.path.lstrip("/") or 0),
        password=parsed.password,
    )


class WorkerSettings:
    """Configuração do ARQ Worker."""
    functions = [run_pipeline, run_single_etapa]
    cron_jobs = [
        cron(sync_condominios, hour={6}, minute={0}, run_at_startup=False),
    ]
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 4
    job_timeout = 1800  # 30 min max por job
    redis_settings = _parse_redis_url(get_settings().redis_url)


if __name__ == "__main__":
    from arq import run_worker
    run_worker(WorkerSettings)  # type: ignore[arg-type]
