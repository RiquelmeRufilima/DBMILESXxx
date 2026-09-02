from __future__ import annotations

import ipaddress
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from ..config import LOCAL_ADMIN_ENABLED, LOCAL_CONTROL_HASH_FILE, MAX_TEAM_USERS
from ..database import get_db
from ..models import WebCompany, WebUser
from ..security import hash_password, validate_csrf_token, validate_password, verify_password
from ..services.team_accounts import can_create_team_user, team_user_count
from ..services.realtime import manager, profile_event
from ..services.user_defaults import ensure_user_defaults
from ..web import context, flash, templates

router = APIRouter(prefix="/controle-local", tags=["local-control"], include_in_schema=False)


def _loopback_host(value: str) -> bool:
    value = (value or "").strip().lower().strip("[]")
    if value in {"localhost", "testclient", "testserver"}:
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def _is_loopback(request: Request) -> bool:
    """Libera o painel apenas quando cliente e endereço acessado são locais.

    A checagem dupla evita que um proxy público seja confundido com localhost
    apenas porque a conexão interna chegou por 127.0.0.1.
    """
    if not LOCAL_ADMIN_ENABLED:
        return False
    client_host = request.client.host if request.client else ""
    requested_host = request.url.hostname or ""
    return _loopback_host(client_host) and _loopback_host(requested_host)


def _guard(request: Request) -> None:
    if not _is_loopback(request):
        raise HTTPException(status_code=404, detail="Not Found")


def _has_master_password() -> bool:
    return LOCAL_CONTROL_HASH_FILE.exists() and bool(LOCAL_CONTROL_HASH_FILE.read_text(encoding="utf-8").strip())


def _read_master_hash() -> str:
    if not _has_master_password():
        return ""
    return LOCAL_CONTROL_HASH_FILE.read_text(encoding="utf-8").strip()


def _write_master_hash(value: str) -> None:
    LOCAL_CONTROL_HASH_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_CONTROL_HASH_FILE.write_text(value, encoding="utf-8")


def _logged(request: Request) -> bool:
    return bool(request.session.get("local_control_authenticated"))


def _redirect_dashboard() -> RedirectResponse:
    return RedirectResponse("/controle-local", status_code=303)


@router.get("")
def local_control_home(request: Request, db: Session = Depends(get_db)):
    _guard(request)
    if not _has_master_password():
        return templates.TemplateResponse(
            request,
            "local_control/setup.html",
            context(request, local_control=True),
        )
    if not _logged(request):
        return templates.TemplateResponse(
            request,
            "local_control/login.html",
            context(request, local_control=True),
        )

    companies = db.scalars(select(WebCompany).order_by(WebCompany.name)).all()
    users = db.scalars(
        select(WebUser)
        .options(selectinload(WebUser.company), selectinload(WebUser.profile))
        .order_by(WebUser.is_owner.desc(), WebUser.company_id, WebUser.name)
    ).all()
    company_counts = {
        company.id: team_user_count(db, company.id)
        for company in companies
    }
    active_count = int(db.scalar(select(func.count(WebUser.id)).where(WebUser.active.is_(True))) or 0)
    return templates.TemplateResponse(
        request,
        "local_control/dashboard.html",
        context(
            request,
            local_control=True,
            companies=companies,
            users=users,
            company_counts=company_counts,
            active_count=active_count,
            max_team_users=MAX_TEAM_USERS,
        ),
    )


@router.post("/configurar")
def setup_master_password(
    request: Request,
    password: str = Form(...),
    password_confirm: str = Form(...),
    csrf_token: str = Form(...),
):
    _guard(request)
    if _has_master_password():
        return _redirect_dashboard()
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada.", "error")
        return _redirect_dashboard()
    if password != password_confirm:
        flash(request, "As senhas não coincidem.", "error")
        return _redirect_dashboard()
    valid, message = validate_password(password)
    if not valid:
        flash(request, message, "error")
        return _redirect_dashboard()
    _write_master_hash(hash_password(password))
    request.session["local_control_authenticated"] = True
    flash(request, "Painel local protegido e configurado.", "success")
    return _redirect_dashboard()


@router.post("/entrar")
def local_control_login(
    request: Request,
    password: str = Form(...),
    csrf_token: str = Form(...),
):
    _guard(request)
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada.", "error")
        return _redirect_dashboard()
    if not verify_password(password, _read_master_hash()):
        flash(request, "Senha mestre incorreta.", "error")
        return _redirect_dashboard()
    request.session["local_control_authenticated"] = True
    flash(request, "Painel local desbloqueado.", "success")
    return _redirect_dashboard()


@router.post("/sair")
def local_control_logout(request: Request, csrf_token: str = Form(...)):
    _guard(request)
    if validate_csrf_token(request.session, csrf_token):
        request.session.pop("local_control_authenticated", None)
    return _redirect_dashboard()


def _require_login(request: Request) -> None:
    _guard(request)
    if not _logged(request):
        raise HTTPException(status_code=403, detail="Painel local bloqueado")


@router.post("/senha-mestra")
def change_master_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    new_password_confirm: str = Form(...),
    csrf_token: str = Form(...),
):
    _require_login(request)
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada.", "error")
        return _redirect_dashboard()
    if not verify_password(current_password, _read_master_hash()):
        flash(request, "Senha mestre atual incorreta.", "error")
        return _redirect_dashboard()
    if new_password != new_password_confirm:
        flash(request, "As novas senhas não coincidem.", "error")
        return _redirect_dashboard()
    valid, message = validate_password(new_password)
    if not valid:
        flash(request, message, "error")
        return _redirect_dashboard()
    _write_master_hash(hash_password(new_password))
    flash(request, "Senha mestre alterada.", "success")
    return _redirect_dashboard()


@router.post("/empresas/criar")
def create_company(
    request: Request,
    name: str = Form(...),
    email: str = Form(""),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    _require_login(request)
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada.", "error")
        return _redirect_dashboard()
    name = name.strip()
    if len(name) < 2:
        flash(request, "Informe o nome da empresa.", "error")
        return _redirect_dashboard()
    db.add(WebCompany(name=name, email=email.strip().lower() or None))
    db.commit()
    flash(request, f"Empresa {name} criada.", "success")
    return _redirect_dashboard()


@router.post("/usuarios/criar")
def create_user(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    company_id: str = Form(""),
    role: str = Form("membro"),
    is_owner: str = Form(""),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    _require_login(request)
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada.", "error")
        return _redirect_dashboard()

    name = name.strip()
    email = email.strip().lower()
    owner = is_owner in {"1", "true", "on", "yes"}
    company_value = int(company_id) if company_id.isdigit() else None
    role = role if role in {"membro", "gerente", "admin"} else "membro"
    if owner:
        role = "admin"
    if len(name) < 2 or "@" not in email or "." not in email:
        flash(request, "Informe nome e e-mail válidos.", "error")
        return _redirect_dashboard()
    if db.scalar(select(WebUser.id).where(WebUser.email == email)):
        flash(request, "Este e-mail já está em uso.", "error")
        return _redirect_dashboard()
    valid, message = validate_password(password)
    if not valid:
        flash(request, message, "error")
        return _redirect_dashboard()
    if company_value and not owner and not can_create_team_user(db, company_value):
        flash(request, f"Essa empresa já atingiu {MAX_TEAM_USERS} usuários adicionais.", "error")
        return _redirect_dashboard()

    if company_value and owner:
        db.execute(update(WebUser).where(WebUser.company_id == company_value).values(is_owner=False))

    user = WebUser(
        company_id=company_value,
        email=email,
        password_hash=hash_password(password),
        name=name,
        role=role,
        active=True,
        is_owner=bool(owner and company_value),
        auth_version=1,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    ensure_user_defaults(db, user)
    flash(request, f"Acesso de {name} criado.", "success")
    return _redirect_dashboard()


@router.post("/usuarios/{user_id}/dados")
async def update_user(
    user_id: int,
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    company_id: str = Form(""),
    role: str = Form("membro"),
    active: str = Form(""),
    is_owner: str = Form(""),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    _require_login(request)
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada.", "error")
        return _redirect_dashboard()
    user = db.get(WebUser, user_id)
    if user is None:
        flash(request, "Usuário não encontrado.", "error")
        return _redirect_dashboard()

    new_name = name.strip()
    new_email = email.strip().lower()
    new_company_id = int(company_id) if company_id.isdigit() else None
    new_owner = is_owner in {"1", "true", "on", "yes"} and bool(new_company_id)
    new_active = active in {"1", "true", "on", "yes"}
    new_role = role if role in {"membro", "gerente", "admin"} else "membro"
    if new_owner:
        new_role = "admin"
    if len(new_name) < 2 or "@" not in new_email or "." not in new_email:
        flash(request, "Informe nome e e-mail válidos.", "error")
        return _redirect_dashboard()
    duplicate = db.scalar(select(WebUser.id).where(WebUser.email == new_email, WebUser.id != user.id))
    if duplicate:
        flash(request, "Este e-mail já pertence a outro acesso.", "error")
        return _redirect_dashboard()
    moving_as_member = new_company_id and not new_owner and new_company_id != user.company_id
    changing_owner_to_member_same_company = new_company_id and not new_owner and user.is_owner
    if (moving_as_member or changing_owner_to_member_same_company) and not can_create_team_user(db, new_company_id):
        flash(request, f"A empresa de destino já atingiu {MAX_TEAM_USERS} usuários adicionais.", "error")
        return _redirect_dashboard()

    if new_company_id and new_owner:
        db.execute(
            update(WebUser)
            .where(WebUser.company_id == new_company_id, WebUser.id != user.id)
            .values(is_owner=False)
        )

    access_changed = (
        user.email != new_email
        or user.active != new_active
        or user.company_id != new_company_id
        or user.role != new_role
        or user.is_owner != new_owner
    )
    user.name = new_name
    user.email = new_email
    user.company_id = new_company_id
    user.role = new_role
    user.active = new_active
    user.is_owner = new_owner
    if access_changed:
        user.auth_version = int(user.auth_version or 1) + 1
    db.commit()
    db.refresh(user)
    if access_changed:
        await manager.disconnect_user(user.id)
    if user.company_id and user.active:
        await manager.broadcast(user.company_id, profile_event(user))
    flash(request, f"Acesso de {user.name} atualizado. O novo e-mail de login já está valendo.", "success")
    return _redirect_dashboard()


@router.post("/usuarios/{user_id}/senha")
async def reset_user_password(
    user_id: int,
    request: Request,
    password: str = Form(...),
    password_confirm: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    _require_login(request)
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada.", "error")
        return _redirect_dashboard()
    user = db.get(WebUser, user_id)
    if user is None:
        flash(request, "Usuário não encontrado.", "error")
        return _redirect_dashboard()
    if password != password_confirm:
        flash(request, "As senhas não coincidem.", "error")
        return _redirect_dashboard()
    valid, message = validate_password(password)
    if not valid:
        flash(request, message, "error")
        return _redirect_dashboard()
    user.password_hash = hash_password(password)
    user.auth_version = int(user.auth_version or 1) + 1
    db.commit()
    await manager.disconnect_user(user.id)
    flash(request, f"Senha de {user.name} redefinida. Sessões antigas foram encerradas.", "success")
    return _redirect_dashboard()
