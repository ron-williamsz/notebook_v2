"""Rotas de páginas HTML."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.dependencies import get_auth_session
from app.models.auth_session import AuthSession

templates = Jinja2Templates(directory="app/templates")
router = APIRouter(tags=["Pages"])


def _ctx(request: Request, auth: AuthSession, **extra) -> dict:
    """Monta context base com user_name e condomínio para templates."""
    return {
        "request": request,
        "user_name": auth.user_name,
        "cond_codigo": auth.selected_cond_codigo,
        "cond_nome": auth.selected_cond_nome,
        "is_admin": getattr(auth, "role", "user") == "admin",
        **extra,
    }


# --- Public ---

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, auth: AuthSession | None = Depends(get_auth_session)):
    if auth:
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request})


# --- Protected ---

@router.get("/selecionar-condominio", response_class=HTMLResponse)
async def condominio_page(request: Request, auth: AuthSession | None = Depends(get_auth_session)):
    if not auth:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse("selecionar_condominio.html", _ctx(request, auth))


@router.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request, auth: AuthSession | None = Depends(get_auth_session)):
    if not auth:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse("dashboard.html", _ctx(request, auth))


@router.get("/notebooks/{session_id}", response_class=HTMLResponse)
async def notebook_page(request: Request, session_id: int, auth: AuthSession | None = Depends(get_auth_session)):
    if not auth:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse("notebook.html", _ctx(request, auth, session_id=session_id))


# --- Admin (role check) ---

@router.get("/admin/skills", response_class=HTMLResponse)
async def skills_admin_page(request: Request, auth: AuthSession | None = Depends(get_auth_session)):
    if not auth:
        return RedirectResponse("/login", status_code=302)
    if getattr(auth, "role", "user") != "admin":
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse("admin/skills.html", _ctx(request, auth))


@router.get("/admin/skills/new", response_class=HTMLResponse)
async def skill_new_page(request: Request, auth: AuthSession | None = Depends(get_auth_session)):
    if not auth:
        return RedirectResponse("/login", status_code=302)
    if getattr(auth, "role", "user") != "admin":
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse("admin/skill_editor.html", _ctx(request, auth, skill_id=0))


@router.get("/admin/skills/{skill_id}", response_class=HTMLResponse)
async def skill_editor_page(request: Request, skill_id: int, auth: AuthSession | None = Depends(get_auth_session)):
    if not auth:
        return RedirectResponse("/login", status_code=302)
    if getattr(auth, "role", "user") != "admin":
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse("admin/skill_editor.html", _ctx(request, auth, skill_id=skill_id))


@router.get("/admin/audit", response_class=HTMLResponse)
async def audit_page(request: Request, auth: AuthSession | None = Depends(get_auth_session)):
    if not auth:
        return RedirectResponse("/login", status_code=302)
    if getattr(auth, "role", "user") != "admin":
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse("admin/audit.html", _ctx(request, auth))


@router.get("/admin/users", response_class=HTMLResponse)
async def users_admin_page(request: Request, auth: AuthSession | None = Depends(get_auth_session)):
    if not auth:
        return RedirectResponse("/login", status_code=302)
    if getattr(auth, "role", "user") != "admin":
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse("admin/users.html", _ctx(request, auth))
