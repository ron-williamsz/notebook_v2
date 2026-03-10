from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # GCP
    gcp_project_id: str = ""
    gcp_project_number: str = ""
    gcp_location: str = "global"
    gcp_endpoint_location: str = "global"
    gcp_access_token: str | None = None

    # Gemini
    gemini_model: str = "gemini-2.5-flash"
    gemini_location: str = "global"
    gemini_max_output_tokens: int = 8192
    gemini_temperature: float = 0.3
    gemini_image_ocr: bool = True

    # GoSATI / Zangari
    zangari_usuario: str = ""
    zangari_senha: str = ""
    zangari_chave: str = ""
    zangari_url: str = "https://sistemas.zangari.com.br/administracaoweb/wsDocumentos.asmx"

    # BD FOR ALL (lista de condomínios)
    bdforall_url: str = "https://api.bdforall.grupozangari.com.br"
    bdforall_email: str = ""
    bdforall_senha: str = ""

    # Auth
    auth_username: str = "admin"
    auth_password: str = "admin"

    # App
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"
    database_url: str = f"sqlite+aiosqlite:///{BASE_DIR / 'data' / 'db' / 'notebook_zang.db'}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
