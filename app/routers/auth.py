from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import UserProfile, WebUser
from ..security import hash_password, validate_csrf_token, validate_password, verify_password
from ..services.auth_email import EmailDeliveryError, issue_email_code, send_auth_code, verify_email_code, validate_email_delivery_config
from ..services.user_defaults import ensure_user_defaults
from ..web import context, flash, templates

router = APIRouter(tags=["auth"])


def _email(value: str) -> str:
    return str(value or "").strip().lower()[:180]


def _valid_email(value: str) -> bool:
    value = _email(value)
    return bool("@" in value and "." in value.rsplit("@", 1)[-1])


def _verify_url(email: str) -> str:
    return f"/verify-email?email={quote(_email(email))}"


def _reset_url(email: str) -> str:
    return f"/reset-password?email={quote(_email(email))}"


@router.get("/login")
def login_page(request: Request, db: Session = Depends(get_db)):
    if request.session.get("user_id"):
        return RedirectResponse("/dashboard", status_code=303)
    return templates.TemplateResponse(request, "auth/login.html", context(request, registration_enabled=True))


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
        request.session["pending_verify_email"] = email
        flash(request, "Sua conta ainda precisa confirmar o e-mail. Digite o código recebido ou solicite um novo.", "info")
        return RedirectResponse(_verify_url(email), status_code=303)

    request.session.clear()
    request.session["user_id"] = user.id
    request.session["auth_version"] = int(user.auth_version or 1)
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

    # A conta pendente é persistida primeiro. O código só entra no banco se o
    # provedor de e-mail aceitar a mensagem.
    db.commit()

    try:
        validate_email_delivery_config()
        code = issue_email_code(db, email=email, purpose="register")
        db.flush()
        send_auth_code(to_email=email, code=code, purpose="register", recipient_name=name)
        db.commit()
    except ValueError as exc:
        db.rollback()
        flash(request, str(exc), "info")
        return RedirectResponse(_verify_url(email), status_code=303)
    except EmailDeliveryError as exc:
        db.rollback()
        request.session["pending_verify_email"] = email
        flash(request, f"Conta criada, mas o e-mail não foi enviado: {exc}", "error")
        return RedirectResponse(_verify_url(email), status_code=303)

    request.session["pending_verify_email"] = email
    flash(request, "Enviamos um código de 6 dígitos para seu e-mail.", "success")
    return RedirectResponse(_verify_url(email), status_code=303)


@router.get("/verify-email")
def verify_email_page(request: Request, email: str = ""):
    if request.session.get("user_id"):
        return RedirectResponse("/dashboard", status_code=303)
    email = _email(email or request.session.get("pending_verify_email", ""))
    if not email:
        return RedirectResponse("/register", status_code=303)
    return templates.TemplateResponse(request, "auth/verify_email.html", context(request, email=email))


@router.post("/verify-email")
def verify_email(
    request: Request,
    email: str = Form(...),
    code: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    email = _email(email)
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada. Tente novamente.", "error")
        return RedirectResponse(_verify_url(email), status_code=303)

    ok, message = verify_email_code(db, email=email, purpose="register", code=code)
    if not ok:
        db.commit()
        flash(request, message, "error")
        return RedirectResponse(_verify_url(email), status_code=303)

    user = db.scalar(select(WebUser).where(WebUser.email == email))
    if user is None:
        db.commit()
        flash(request, "Cadastro não encontrado. Crie a conta novamente.", "error")
        return RedirectResponse("/register", status_code=303)

    user.active = True
    ensure_user_defaults(db, user)
    db.commit()

    request.session.clear()
    request.session["user_id"] = user.id
    request.session["auth_version"] = int(user.auth_version or 1)
    flash(request, "E-mail confirmado. Sua conta está pronta!", "success")
    return RedirectResponse("/dashboard", status_code=303)


@router.post("/verify-email/resend")
def resend_verify_email(
    request: Request,
    email: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    email = _email(email)
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse(_verify_url(email), status_code=303)

    user = db.scalar(select(WebUser).where(WebUser.email == email))
    if user is None or user.active:
        flash(request, "Esta conta já está confirmada ou não existe.", "info")
        return RedirectResponse("/login", status_code=303)
    try:
        validate_email_delivery_config()
        code = issue_email_code(db, email=email, purpose="register")
        db.flush()
        send_auth_code(to_email=email, code=code, purpose="register", recipient_name=user.name)
        db.commit()
        flash(request, "Novo código enviado para seu e-mail.", "success")
    except (ValueError, EmailDeliveryError) as exc:
        db.rollback()
        flash(request, f"Não foi possível enviar o código: {exc}", "error")
    return RedirectResponse(_verify_url(email), status_code=303)


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
    if user is not None:
        try:
            validate_email_delivery_config()
            code = issue_email_code(db, email=email, purpose="reset")
            db.flush()
            send_auth_code(to_email=email, code=code, purpose="reset", recipient_name=user.name)
            db.commit()
        except ValueError as exc:
            db.rollback()
            flash(request, str(exc), "info")
            return RedirectResponse(_reset_url(email), status_code=303)
        except EmailDeliveryError as exc:
            db.rollback()
            flash(request, f"Não foi possível enviar o código: {exc}", "error")
            return RedirectResponse("/forgot-password", status_code=303)

    request.session["pending_reset_email"] = email
    flash(request, "Se este e-mail estiver cadastrado, um código de recuperação foi enviado.", "success")
    return RedirectResponse(_reset_url(email), status_code=303)


@router.get("/reset-password")
def reset_password_page(request: Request, email: str = ""):
    if request.session.get("user_id"):
        return RedirectResponse("/dashboard", status_code=303)
    email = _email(email or request.session.get("pending_reset_email", ""))
    if not email:
        return RedirectResponse("/forgot-password", status_code=303)
    return templates.TemplateResponse(request, "auth/reset_password.html", context(request, email=email))


@router.post("/reset-password")
def reset_password(
    request: Request,
    email: str = Form(...),
    code: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    email = _email(email)
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada. Tente novamente.", "error")
        return RedirectResponse(_reset_url(email), status_code=303)
    if password != password_confirm:
        flash(request, "As senhas não coincidem.", "error")
        return RedirectResponse(_reset_url(email), status_code=303)
    valid, message = validate_password(password)
    if not valid:
        flash(request, message, "error")
        return RedirectResponse(_reset_url(email), status_code=303)

    ok, message = verify_email_code(db, email=email, purpose="reset", code=code)
    if not ok:
        db.commit()
        flash(request, message, "error")
        return RedirectResponse(_reset_url(email), status_code=303)

    user = db.scalar(select(WebUser).where(WebUser.email == email, WebUser.active.is_(True)))
    if user is None:
        db.commit()
        flash(request, "Não foi possível redefinir esta conta.", "error")
        return RedirectResponse("/forgot-password", status_code=303)

    user.password_hash = hash_password(password)
    user.auth_version = int(user.auth_version or 1) + 1
    db.commit()
    request.session.clear()
    flash(request, "Senha alterada com sucesso. Entre com a nova senha.", "success")
    return RedirectResponse("/login", status_code=303)


@router.post("/reset-password/resend")
def resend_reset_code(
    request: Request,
    email: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    email = _email(email)
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse(_reset_url(email), status_code=303)

    user = db.scalar(select(WebUser).where(WebUser.email == email, WebUser.active.is_(True)))
    if user is not None:
        try:
            validate_email_delivery_config()
            code = issue_email_code(db, email=email, purpose="reset")
            db.flush()
            send_auth_code(to_email=email, code=code, purpose="reset", recipient_name=user.name)
            db.commit()
            flash(request, "Novo código enviado para seu e-mail.", "success")
        except (ValueError, EmailDeliveryError) as exc:
            db.rollback()
            flash(request, f"Não foi possível enviar o código: {exc}", "error")
    else:
        flash(request, "Se este e-mail estiver cadastrado, um novo código foi enviado.", "info")
    return RedirectResponse(_reset_url(email), status_code=303)


@router.post("/logout")
def logout(request: Request, csrf_token: str = Form(...)):
    if not validate_csrf_token(request.session, csrf_token):
        return RedirectResponse("/dashboard", status_code=303)
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
