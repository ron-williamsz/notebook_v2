import asyncio
import shutil
import subprocess
import time

from app.core.config import Settings

GCLOUD_CMD = shutil.which("gcloud") or shutil.which("gcloud.cmd") or "gcloud"

_cached_token: str | None = None
_token_expiry: float = 0.0
_lock = asyncio.Lock()

TOKEN_TTL_SECONDS = 3300  # 55 min (tokens duram 60 min)


def _run_gcloud() -> str:
    result = subprocess.run(
        [GCLOUD_CMD, "auth", "print-access-token"],
        capture_output=True,
        text=True,
        shell=(GCLOUD_CMD.endswith(".cmd")),
    )
    if result.returncode != 0:
        raise RuntimeError(f"gcloud auth failed: {result.stderr.strip()}")
    return result.stdout.strip()


async def get_access_token(settings: Settings) -> str:
    global _cached_token, _token_expiry

    if settings.gcp_access_token:
        return settings.gcp_access_token

    async with _lock:
        if _cached_token and time.monotonic() < _token_expiry:
            return _cached_token

        loop = asyncio.get_running_loop()
        _cached_token = await loop.run_in_executor(None, _run_gcloud)
        _token_expiry = time.monotonic() + TOKEN_TTL_SECONDS
        return _cached_token
