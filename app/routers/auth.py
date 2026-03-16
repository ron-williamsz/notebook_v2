"""Rotas de autenticação."""
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import COOKIE_NAME, log_audit, require_auth
from app.models.auth_session import AuthSession
from app.models.base import get_db
from app.schemas.auth import (
    ChangePasswordRequest,
    CondominioSelection,
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
)
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["Auth"])


def _svc(db: AsyncSession = Depends(get_db)) -> AuthService:
    return AuthService(db)


@router.post("/login", response_model=LoginResponse)
async def login(
    data: LoginRequest,
    request: Request,
    response: Response,
    svc: AuthService = Depends(_svc),
    db: AsyncSession = Depends(get_db),
):
    auth_session, senha_temporaria = await svc.login(data.email, data.senha)
    response.set_cookie(
        key=COOKIE_NAME,
        value=auth_session.id,
        httponly=True,
        samesite="lax",
        max_age=43200,  # 12 hours
        path="/",
    )
    await log_audit(db, auth_session, "login", request)
    return LoginResponse(
        user_name=auth_session.user_name,
        user_email=auth_session.user_email,
        senha_temporaria=senha_temporaria,
    )


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    auth_session: AuthSession = Depends(require_auth),
    svc: AuthService = Depends(_svc),
    db: AsyncSession = Depends(get_db),
):
    await log_audit(db, auth_session, "logout", request)
    await svc.logout(auth_session.id)
    response.delete_cookie(key=COOKIE_NAME, path="/")
    return {"detail": "Logout realizado"}


@router.get("/me", response_model=LoginResponse)
async def me(auth_session: AuthSession = Depends(require_auth)):
    return LoginResponse(
        user_name=auth_session.user_name,
        user_email=auth_session.user_email,
    )


@router.post("/forgot-password")
async def forgot_password(data: ForgotPasswordRequest, svc: AuthService = Depends(_svc)):
    await svc.forgot_password(data.email)
    return {"detail": "Se o email existir, as instruções foram enviadas"}


@router.post("/change-password")
async def change_password(
    data: ChangePasswordRequest,
    request: Request,
    auth_session: AuthSession = Depends(require_auth),
    svc: AuthService = Depends(_svc),
    db: AsyncSession = Depends(get_db),
):
    await svc.change_password(auth_session.id, data.senha_atual, data.nova_senha)
    await log_audit(db, auth_session, "change_password", request)
    return {"detail": "Senha alterada com sucesso"}


@router.get("/condominio")
async def get_condominio(auth_session: AuthSession = Depends(require_auth)):
    return {
        "codigo": auth_session.selected_cond_codigo,
        "nome": auth_session.selected_cond_nome,
    }


@router.patch("/condominio")
async def set_condominio(
    data: CondominioSelection,
    request: Request,
    auth_session: AuthSession = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    auth_session.selected_cond_codigo = data.codigo
    auth_session.selected_cond_nome = data.nome
    db.add(auth_session)
    await db.commit()
    await log_audit(
        db, auth_session, "select_condominio", request,
        details={"condominio": f"{data.codigo} - {data.nome}"},
    )
    return {"codigo": data.codigo, "nome": data.nome}
