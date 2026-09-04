from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import UserProfile, WebUser
from ..security import hash_password, validate_csrf_token, validate_password, verify_password
from ..services.auth_totp import (
    authenticator_configured,
    credential_secret,
    ensure_pending_credential,
    ensure_totp_schema,
    get_credential,
    login_2fa_enabled,
    provisioning_uri,
    qr_data_uri,
    verify_totp,
)
from ..services.user_defaults import ensure_user_defaults
from ..web import context, flash, templates


router = APIRouter(tags=["auth"])


def _email(value: str) -> str:
    return str(value or "").strip().lower()[:180]


def _valid_email(value: str) -> bool:
    value = _email(value)
    return bool("@" in value and "." in value.rsplit("@", 1)[-1])


def _pending_user(request: Request, db: Session, key: str) -> WebUser | None:
    raw = request.session.get(key)
    try:
        user_id = int(raw)
    except (TypeError, ValueError):
        return None
    return db.get(WebUser, user_id)


def _complete_login(request: Request, user: WebUser) -> None:
    request.session.clear()
    request.session["user_id"] = int(user.id)
    request.session["auth_version"] = int(user.auth_version or 1)


@router.get("/login")
def login_page(request: Request, db: Session = Depends(get_db)):
    if request.session.get("user_id"):
        return RedirectResponse("/dashboard", status_code=303)
    return templates.TemplateResponse(
        request,
        "auth/login.html",
        context(request, registration_enabled=True),
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

    email = _email(email)
    user = db.scalar(select(WebUser).where(WebUser.email == email))
    if user is None or not verify_password(password, user.password_hash):
        flash(request, "E-mail ou senha incorretos.", "error")
        return RedirectResponse("/login", status_code=303)

    if not user.active:
        flash(request, "Esta conta está desativada. Procure o administrador.", "error")
        return RedirectResponse("/login", status_code=303)

    ensure_totp_schema(db)

    # O Google Authenticator só é solicitado se o próprio usuário ativou o
    # segundo fator em Configurações > Segurança.
    if login_2fa_enabled(db, int(user.id)):
        request.session.clear()
        request.session["pending_2fa_user_id"] = int(user.id)
        return RedirectResponse("/login/authenticator", status_code=303)

    _complete_login(request, user)
    flash(request, f"Bem-vindo, {user.name}!", "success")
    return RedirectResponse("/dashboard", status_code=303)


@router.get("/login/authenticator")
def login_authenticator_page(request: Request, db: Session = Depends(get_db)):
    if request.session.get("user_id"):
        return RedirectResponse("/dashboard", status_code=303)

    user = _pending_user(request, db, "pending_2fa_user_id")
    if user is None:
        return RedirectResponse("/login", status_code=303)

    return templates.TemplateResponse(
        request,
        "auth/login_authenticator.html",
        context(request, email=user.email),
    )


@router.post("/login/authenticator")
def login_authenticator(
    request: Request,
    code: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada. Entre novamente.", "error")
        return RedirectResponse("/login", status_code=303)

    user = _pending_user(request, db, "pending_2fa_user_id")
    if user is None:
        return RedirectResponse("/login", status_code=303)

    credential = get_credential(db, int(user.id))
    if credential is None or not credential.enabled:
        request.session.clear()
        flash(request, "O Authenticator não está mais ativo nesta conta.", "info")
        return RedirectResponse("/login", status_code=303)

    if not verify_totp(credential_secret(credential), code):
        flash(request, "Código incorreto. Use o código atual do Google Authenticator.", "error")
        return RedirectResponse("/login/authenticator", status_code=303)

    _complete_login(request, user)
    flash(request, f"Bem-vindo, {user.name}!", "success")
    return RedirectResponse("/dashboard", status_code=303)


@router.get("/register")
def register_page(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/dashboard", status_code=303)
    return templates.TemplateResponse(request, "auth/register.html", context(request))


@router.post("/register")
def register(
    request: Request,
    name: str = Form(...),
    job_title: str = Form(""),
    phone: str = Form(""),
    email: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada. Tente novamente.", "error")
        return RedirectResponse("/register", status_code=303)

    email = _email(email)
    name = str(name or "").strip()[:180]
    phone = str(phone or "").strip()[:40]
    job_title = str(job_title or "").strip()[:120]

    if len(name) < 3:
        flash(request, "Informe seu nome completo.", "error")
        return RedirectResponse("/register", status_code=303)
    if not _valid_email(email):
        flash(request, "Informe um e-mail válido.", "error")
        return RedirectResponse("/register", status_code=303)
    if password != password_confirm:
        flash(request, "As senhas não coincidem.", "error")
        return RedirectResponse("/register", status_code=303)

    valid, message = validate_password(password)
    if not valid:
        flash(request, message, "error")
        return RedirectResponse("/register", status_code=303)

    existing = db.scalar(select(WebUser).where(WebUser.email == email))
    if existing is not None:
        flash(request, "Este e-mail já possui uma conta.", "info")
        return RedirectResponse("/login", status_code=303)

    user = WebUser(
        email=email,
        password_hash=hash_password(password),
        name=name,
        phone=phone or None,
        role="membro",
        active=True,
        is_owner=False,
    )
    db.add(user)
    db.flush()

    profile = UserProfile(user_id=user.id, job_title=job_title or None)
    db.add(profile)

    ensure_user_defaults(db, user)
    db.commit()

    _complete_login(request, user)
    flash(
        request,
        "Conta criada. Você pode ativar o Google Authenticator em Configurações > Segurança.",
        "success",
    )
    return RedirectResponse("/dashboard", status_code=303)


# ---------------------------------------------------------------------
# CONFIGURAÇÃO DO AUTHENTICATOR
# A ativação agora parte de Configurações > Segurança.
# ---------------------------------------------------------------------

@router.get("/setup-authenticator")
def setup_authenticator_page(request: Request, db: Session = Depends(get_db)):
    user = None

    if request.session.get("user_id"):
        try:
            user = db.get(WebUser, int(request.session["user_id"]))
        except (TypeError, ValueError):
            user = None
    else:
        user = _pending_user(request, db, "pending_totp_user_id")

    if user is None:
        return RedirectResponse("/login", status_code=303)

    ensure_totp_schema(db)
    credential = ensure_pending_credential(db, user)
    db.commit()

    secret = credential_secret(credential)
    uri = provisioning_uri(secret=secret, email=user.email)

    return templates.TemplateResponse(
        request,
        "auth/setup_authenticator.html",
        context(
            request,
            email=user.email,
            secret=secret,
            qr_data=qr_data_uri(uri),
            otpauth_uri=uri,
            settings_flow=bool(request.session.get("user_id")),
        ),
    )


@router.post("/setup-authenticator")
def setup_authenticator(
    request: Request,
    code: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada. Entre novamente.", "error")
        return RedirectResponse("/login", status_code=303)

    logged_user = None
    if request.session.get("user_id"):
        try:
            logged_user = db.get(WebUser, int(request.session["user_id"]))
        except (TypeError, ValueError):
            logged_user = None

    user = logged_user or _pending_user(request, db, "pending_totp_user_id")
    if user is None:
        return RedirectResponse("/login", status_code=303)

    credential = get_credential(db, int(user.id))
    if credential is None:
        flash(request, "Configuração não encontrada. Comece novamente.", "error")
        return RedirectResponse("/settings", status_code=303)

    if not verify_totp(credential_secret(credential), code):
        flash(request, "Código incorreto. Use o código atual do Google Authenticator.", "error")
        return RedirectResponse("/setup-authenticator", status_code=303)

    credential.enabled = True
    credential.login_2fa_enabled = True
    credential.confirmed_at = datetime.utcnow()
    credential.updated_at = datetime.utcnow()
    db.commit()

    request.session.pop("pending_totp_user_id", None)
    flash(request, "Google Authenticator ativado para o login.", "success")

    if logged_user is not None:
        return RedirectResponse("/settings", status_code=303)

    _complete_login(request, user)
    return RedirectResponse("/dashboard", status_code=303)


# Compatibilidade com URLs antigas.
@router.get("/verify-email")
@router.post("/verify-email")
@router.post("/verify-email/resend")
def old_verify_email(request: Request):
    return RedirectResponse("/login", status_code=303)


# ---------------------------------------------------------------------
# RECUPERAÇÃO DE SENHA
# Apenas o código ATUAL do Google Authenticator é aceito.
# Não existem mais códigos de recuperação nesse fluxo.
# ---------------------------------------------------------------------

@router.get("/forgot-password")
def forgot_password_page(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/dashboard", status_code=303)
    return templates.TemplateResponse(request, "auth/forgot_password.html", context(request))


@router.post("/forgot-password")
def forgot_password(
    request: Request,
    email: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada. Tente novamente.", "error")
        return RedirectResponse("/forgot-password", status_code=303)

    email = _email(email)
    if not _valid_email(email):
        flash(request, "Informe um e-mail válido.", "error")
        return RedirectResponse("/forgot-password", status_code=303)

    user = db.scalar(select(WebUser).where(WebUser.email == email, WebUser.active.is_(True)))
    request.session.clear()

    if user is None:
        flash(request, "Não foi possível iniciar a recuperação.", "info")
        return RedirectResponse("/login", status_code=303)

    ensure_totp_schema(db)
    if not authenticator_configured(db, int(user.id)):
        flash(
            request,
            "Esta conta não possui Google Authenticator configurado. "
            "Solicite ao administrador a redefinição da senha.",
            "info",
        )
        return RedirectResponse("/login", status_code=303)

    request.session["pending_reset_user_id"] = int(user.id)
    return RedirectResponse("/reset-password", status_code=303)


@router.get("/reset-password")
def reset_password_page(request: Request, db: Session = Depends(get_db)):
    if request.session.get("user_id"):
        return RedirectResponse("/dashboard", status_code=303)

    user = _pending_user(request, db, "pending_reset_user_id")
    if user is None:
        return RedirectResponse("/forgot-password", status_code=303)

    return templates.TemplateResponse(
        request,
        "auth/reset_password.html",
        context(request, email=user.email),
    )


@router.post("/reset-password")
def reset_password(
    request: Request,
    code: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada. Tente novamente.", "error")
        return RedirectResponse("/forgot-password", status_code=303)

    user = _pending_user(request, db, "pending_reset_user_id")
    if user is None:
        return RedirectResponse("/forgot-password", status_code=303)

    if password != password_confirm:
        flash(request, "As senhas não coincidem.", "error")
        return RedirectResponse("/reset-password", status_code=303)

    valid, message = validate_password(password)
    if not valid:
        flash(request, message, "error")
        return RedirectResponse("/reset-password", status_code=303)

    credential = get_credential(db, int(user.id))
    if credential is None or not credential.enabled:
        flash(request, "Google Authenticator não está configurado nesta conta.", "error")
        return RedirectResponse("/login", status_code=303)

    if not verify_totp(credential_secret(credential), code):
        flash(request, "Código inválido. Use o código atual do Google Authenticator.", "error")
        return RedirectResponse("/reset-password", status_code=303)

    user.password_hash = hash_password(password)
    user.auth_version = int(user.auth_version or 1) + 1
    db.commit()

    request.session.clear()
    flash(request, "Senha alterada com sucesso. Entre com sua nova senha.", "success")
    return RedirectResponse("/login", status_code=303)


@router.post("/reset-password/resend")
def old_reset_resend(request: Request):
    flash(request, "A recuperação usa o código atual do Google Authenticator.", "info")
    return RedirectResponse("/reset-password", status_code=303)


@router.post("/logout")
def logout(request: Request, csrf_token: str = Form(...)):
    if not validate_csrf_token(request.session, csrf_token):
        return RedirectResponse("/dashboard", status_code=303)
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
