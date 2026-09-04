from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import UserProfile, WebUser
from ..security import hash_password, validate_csrf_token, validate_password, verify_password
from ..services.auth_totp import (
    authenticator_enabled,
    credential_secret,
    ensure_pending_credential,
    ensure_totp_schema,
    generate_recovery_codes,
    get_credential,
    provisioning_uri,
    qr_data_uri,
    verify_totp,
    verify_totp_or_recovery,
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

    ensure_totp_schema(db)

    # Contas antigas ou cadastros incompletos passam pela ativação do Authenticator.
    if not user.active or not authenticator_enabled(db, int(user.id)):
        ensure_pending_credential(db, user)
        db.commit()
        request.session.clear()
        request.session["pending_totp_user_id"] = int(user.id)
        flash(request, "Configure o Google Authenticator para concluir a proteção da sua conta.", "info")
        return RedirectResponse("/setup-authenticator", status_code=303)

    request.session.clear()
    request.session["pending_2fa_user_id"] = int(user.id)
    return RedirectResponse("/login/authenticator", status_code=303)


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

    ok, method = verify_totp_or_recovery(db, int(user.id), code, allow_recovery=True)
    if not ok:
        db.rollback()
        flash(request, "Código inválido. Use o código atual do Authenticator ou um código de recuperação.", "error")
        return RedirectResponse("/login/authenticator", status_code=303)

    db.commit()
    _complete_login(request, user)
    if method == "recovery":
        flash(request, "Código de recuperação utilizado. Ele não poderá ser usado novamente.", "warning")
    else:
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

    user = db.scalar(select(WebUser).where(WebUser.email == email))
    if user is not None and user.active:
        flash(request, "Este e-mail já possui uma conta. Entre ou use 'Esqueci minha senha'.", "info")
        return RedirectResponse("/login", status_code=303)

    if user is None:
        user = WebUser(
            email=email,
            password_hash=hash_password(password),
            name=name,
            phone=phone or None,
            role="membro",
            active=False,
            is_owner=False,
        )
        db.add(user)
        db.flush()
    else:
        user.name = name
        user.phone = phone or None
        user.password_hash = hash_password(password)
        user.active = False
        db.flush()

    profile = user.profile
    if profile is None:
        profile = UserProfile(user_id=user.id, job_title=job_title or None)
        db.add(profile)
    else:
        profile.job_title = job_title or None

    ensure_totp_schema(db)
    ensure_pending_credential(db, user, reset_secret=True)
    db.commit()

    request.session.clear()
    request.session["pending_totp_user_id"] = int(user.id)
    flash(request, "Conta criada. Agora vincule o Google Authenticator.", "success")
    return RedirectResponse("/setup-authenticator", status_code=303)


@router.get("/setup-authenticator")
def setup_authenticator_page(request: Request, db: Session = Depends(get_db)):
    if request.session.get("user_id"):
        return RedirectResponse("/dashboard", status_code=303)

    user = _pending_user(request, db, "pending_totp_user_id")
    if user is None:
        return RedirectResponse("/login", status_code=303)

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
        flash(request, "Sessão expirada. Comece novamente.", "error")
        return RedirectResponse("/login", status_code=303)

    user = _pending_user(request, db, "pending_totp_user_id")
    if user is None:
        return RedirectResponse("/login", status_code=303)

    credential = get_credential(db, int(user.id))
    if credential is None:
        flash(request, "Configuração não encontrada. Comece novamente.", "error")
        return RedirectResponse("/login", status_code=303)

    secret = credential_secret(credential)
    if not verify_totp(secret, code):
        flash(request, "Código incorreto. Aguarde o Authenticator gerar o código atual e tente novamente.", "error")
        return RedirectResponse("/setup-authenticator", status_code=303)

    from datetime import datetime

    credential.enabled = True
    credential.confirmed_at = datetime.utcnow()
    credential.updated_at = datetime.utcnow()
    user.active = True
    ensure_user_defaults(db, user)
    recovery_codes = generate_recovery_codes(db, int(user.id), count=8)
    db.commit()

    _complete_login(request, user)

    return templates.TemplateResponse(
        request,
        "auth/recovery_codes.html",
        context(request, recovery_codes=recovery_codes),
    )


# Compatibilidade com links antigos da confirmação por e-mail.
@router.get("/verify-email")
def old_verify_email(request: Request):
    if request.session.get("pending_totp_user_id"):
        return RedirectResponse("/setup-authenticator", status_code=303)
    return RedirectResponse("/login", status_code=303)


@router.post("/verify-email")
def old_verify_email_post(request: Request):
    if request.session.get("pending_totp_user_id"):
        return RedirectResponse("/setup-authenticator", status_code=303)
    return RedirectResponse("/login", status_code=303)


@router.post("/verify-email/resend")
def old_verify_email_resend(request: Request):
    if request.session.get("pending_totp_user_id"):
        return RedirectResponse("/setup-authenticator", status_code=303)
    return RedirectResponse("/login", status_code=303)


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

    if user is None or not authenticator_enabled(db, int(user.id)):
        # Mensagem genérica para não confirmar publicamente quais e-mails existem.
        flash(
            request,
            "Não foi possível iniciar a recuperação. Se a conta existir, ela precisa ter o Authenticator configurado.",
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

    ok, method = verify_totp_or_recovery(db, int(user.id), code, allow_recovery=True)
    if not ok:
        db.rollback()
        flash(
            request,
            "Código inválido. Use o código atual do Google Authenticator ou um código de recuperação.",
            "error",
        )
        return RedirectResponse("/reset-password", status_code=303)

    user.password_hash = hash_password(password)
    user.auth_version = int(user.auth_version or 1) + 1
    db.commit()

    request.session.clear()
    if method == "recovery":
        flash(request, "Senha alterada. O código de recuperação utilizado foi invalidado.", "success")
    else:
        flash(request, "Senha alterada com sucesso. Entre com sua nova senha.", "success")
    return RedirectResponse("/login", status_code=303)


# Compatibilidade com o botão antigo de reenvio: não existe e-mail no novo fluxo.
@router.post("/reset-password/resend")
def old_reset_resend(request: Request):
    flash(request, "A recuperação agora usa Google Authenticator ou código de recuperação.", "info")
    return RedirectResponse("/reset-password", status_code=303)


@router.post("/security/recovery-codes/regenerate")
def regenerate_recovery_codes(
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    """Gera um novo conjunto de códigos de recuperação para usuário autenticado.

    Todos os códigos antigos são invalidados imediatamente.
    """
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada. Entre novamente.", "error")
        return RedirectResponse("/login", status_code=303)

    user_id = request.session.get("user_id")
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        flash(request, "Entre novamente para gerar novos códigos.", "error")
        return RedirectResponse("/login", status_code=303)

    user = db.get(WebUser, user_id)
    if user is None or not user.active:
        request.session.clear()
        flash(request, "Sua sessão não é mais válida. Entre novamente.", "error")
        return RedirectResponse("/login", status_code=303)

    if not authenticator_enabled(db, user_id):
        flash(request, "Configure o Google Authenticator antes de gerar códigos de recuperação.", "error")
        return RedirectResponse("/setup-authenticator", status_code=303)

    recovery_codes = generate_recovery_codes(db, user_id, count=8)
    db.commit()

    flash(
        request,
        "Novos códigos gerados. Todos os códigos de recuperação anteriores foram invalidados.",
        "success",
    )
    return templates.TemplateResponse(
        request,
        "auth/recovery_codes.html",
        context(
            request,
            recovery_codes=recovery_codes,
            regenerated=True,
        ),
    )


@router.post("/logout")
def logout(request: Request, csrf_token: str = Form(...)):
    if not validate_csrf_token(request.session, csrf_token):
        return RedirectResponse("/dashboard", status_code=303)
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
