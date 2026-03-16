"""Serviço de autenticação via BD FOR ALL."""
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.config import get_settings
from app.core.exceptions import AuthenticationError
from app.models.auth_session import AuthSession

logger = logging.getLogger(__name__)
settings = get_settings()


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.base_url = settings.bdforall_url.rstrip("/")

    async def login(self, email: str, senha: str) -> tuple[AuthSession, bool]:
        """Autentica no BD FOR ALL e cria sessão local.

        Returns (auth_session, senha_temporaria).
        """
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.post(
                f"{self.base_url}/api/auth/login",
                params={"email": email, "senha": senha},
            )

        if resp.status_code == 401:
            raise AuthenticationError(401, "Email ou senha incorretos")
        if resp.status_code != 200:
            logger.error("BD FOR ALL login error: %s %s", resp.status_code, resp.text)
            raise AuthenticationError(502, "Erro ao conectar com o servidor de autenticação")

        data = resp.json()
        token = data.get("access_token")
        senha_temporaria = data.get("senha_temporaria", False)
        user = data.get("user", {})

        if not token:
            raise AuthenticationError(502, "Resposta inválida do servidor de autenticação")

        # Determine role
        admin_list = [e.strip().lower() for e in settings.admin_emails.split(",") if e.strip()]
        role = "admin" if email.strip().lower() in admin_list else "user"

        # Create local auth session
        auth_session = AuthSession(
            user_id=user.get("id", 0),
            user_name=user.get("name", email.split("@")[0]),
            user_email=email,
            bdforall_token=token,
            role=role,
        )
        self.db.add(auth_session)
        await self.db.commit()
        await self.db.refresh(auth_session)

        return auth_session, senha_temporaria

    async def logout(self, session_id: str) -> None:
        """Deleta a sessão de auth."""
        result = await self.db.execute(
            select(AuthSession).where(AuthSession.id == session_id)
        )
        auth_session = result.scalar_one_or_none()
        if auth_session:
            await self.db.delete(auth_session)
            await self.db.commit()

    async def get_session(self, session_id: str) -> AuthSession | None:
        """Busca sessão e valida expiração."""
        result = await self.db.execute(
            select(AuthSession).where(AuthSession.id == session_id)
        )
        auth_session = result.scalar_one_or_none()
        if not auth_session:
            return None

        now = datetime.now(timezone.utc)
        expires = auth_session.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)

        if now > expires:
            await self.db.delete(auth_session)
            await self.db.commit()
            return None

        return auth_session

    async def forgot_password(self, email: str) -> None:
        """Proxy para forgot-password do BD FOR ALL."""
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.post(
                f"{self.base_url}/api/auth/forgot-password",
                json={"email": email},
            )

        if resp.status_code not in (200, 201, 204):
            detail = "Erro ao enviar email de recuperação"
            try:
                detail = resp.json().get("detail", detail)
            except Exception:
                pass
            raise AuthenticationError(resp.status_code, detail)

    async def change_password(
        self, session_id: str, senha_atual: str, nova_senha: str
    ) -> None:
        """Proxy para change-password do BD FOR ALL."""
        auth_session = await self.get_session(session_id)
        if not auth_session:
            raise AuthenticationError(401, "Sessão inválida")

        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.post(
                f"{self.base_url}/api/auth/change-password",
                json={"senha_atual": senha_atual, "nova_senha": nova_senha},
                headers={"Authorization": f"Bearer {auth_session.bdforall_token}"},
            )

        if resp.status_code not in (200, 201, 204):
            detail = "Erro ao alterar senha"
            try:
                detail = resp.json().get("detail", detail)
            except Exception:
                pass
            raise AuthenticationError(resp.status_code, detail)
