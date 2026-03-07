"""Entry point para o Notebook Zang."""
import os
from pathlib import Path

import uvicorn

# Configura credenciais GCP se o arquivo existir localmente
_cred_path = Path(__file__).parent / ".gcp" / "credentials.json"
if _cred_path.exists() and not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(_cred_path)

from app.core.config import get_settings


def main():
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        log_level=settings.log_level.lower(),
        reload=True,
    )


if __name__ == "__main__":
    main()
