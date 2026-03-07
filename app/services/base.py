"""BaseService com autenticação GCP."""
import logging

import httpx

from app.core.auth import get_access_token
from app.core.config import Settings
from app.core.exceptions import AppError, AuthenticationError, NotFoundError, RateLimitError

logger = logging.getLogger(__name__)


class BaseService:
    def __init__(self, client: httpx.AsyncClient, settings: Settings):
        self.client = client
        self.settings = settings

    async def _get_headers(self) -> dict:
        token = await get_access_token(self.settings)
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        headers = await self._get_headers()
        headers.update(kwargs.pop("headers", {}))
        resp = await self.client.request(method, url, headers=headers, **kwargs)
        self._check_response(resp)
        return resp

    def _check_response(self, resp: httpx.Response) -> None:
        if resp.is_success:
            return
        body = None
        try:
            body = resp.json()
        except Exception:
            pass
        if resp.status_code == 401:
            raise AuthenticationError(401, "Autenticação falhou", body)
        if resp.status_code == 404:
            raise NotFoundError(404, "Recurso não encontrado", body)
        if resp.status_code == 429:
            raise RateLimitError(429, "Limite de requisições excedido", body)
        raise AppError(resp.status_code, f"Erro HTTP {resp.status_code}", body)
