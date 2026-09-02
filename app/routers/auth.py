from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import REGISTRATION_ENABLED
from ..database import get_db
from ..models import WebUser
from ..security import hash_password, validate_csrf_token, validate_password, verify_password
from ..web import context, flash, templates

router = APIRouter(tags=["auth"])


@router.get("/login")
def login_page(request: Request, db: Session = Depends(get_db)):
    if request.session.get("user_id"):
        return RedirectResponse("/dashboard", status_code=303)
    return templates.TemplateResponse(
        request,
        "auth/login.html",
        context(request, registration_enabled=REGISTRATION_ENABLED),
    )


@router.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada. Tente novamente.", "error")
        return RedirectResponse("/login", status_code=303)

    user = db.scalar(select(WebUser).where(WebUser.email == email.strip().lower()))
    if user is None or not user.active or not verify_password(password, user.password_hash):
        flash(request, "E-mail ou senha incorretos.", "error")
        return RedirectResponse("/login", status_code=303)

    request.session.clear()
    request.session["user_id"] = user.id
    request.session["auth_version"] = int(user.auth_version or 1)
    flash(request, f"Bem-vindo, {user.name}!", "success")
    return RedirectResponse("/dashboard", status_code=303)


@router.get("/register")
def register_page(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/dashboard", status_code=303)
    if not REGISTRATION_ENABLED:
        flash(request, "Novos acessos são criados pelo administrador da empresa.", "info")
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(request, "auth/register.html", context(request))


@router.post("/register")
def register(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    if not REGISTRATION_ENABLED:
        flash(request, "Cadastro público desativado. Solicite seu acesso ao administrador.", "error")
        return RedirectResponse("/login", status_code=303)
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada. Tente novamente.", "error")
        return RedirectResponse("/register", status_code=303)

    email = email.strip().lower()
    name = name.strip()
    if len(name) < 3:
        flash(request, "Informe seu nome completo.", "error")
        return RedirectResponse("/register", status_code=303)
    if "@" not in email or "." not in email:
        flash(request, "Informe um e-mail válido.", "error")
        return RedirectResponse("/register", status_code=303)
    if password != password_confirm:
        flash(request, "As senhas não coincidem.", "error")
        return RedirectResponse("/register", status_code=303)
    valid, message = validate_password(password)
    if not valid:
        flash(request, message, "error")
        return RedirectResponse("/register", status_code=303)
    if db.scalar(select(WebUser.id).where(WebUser.email == email)):
        flash(request, "Este e-mail já está cadastrado.", "error")
        return RedirectResponse("/login", status_code=303)

    user = WebUser(
        email=email,
        password_hash=hash_password(password),
        name=name,
        role="membro",
        active=True,
        is_owner=False,
    )
    db.add(user)
    db.commit()
    request.session.clear()
    request.session["user_id"] = user.id
    request.session["auth_version"] = int(user.auth_version or 1)
    flash(request, "Conta criada com sucesso.", "success")
    return RedirectResponse("/dashboard", status_code=303)


@router.post("/logout")
def logout(request: Request, csrf_token: str = Form(...)):
    if not validate_csrf_token(request.session, csrf_token):
        return RedirectResponse("/dashboard", status_code=303)
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
