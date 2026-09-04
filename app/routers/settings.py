from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import current_user
from ..security import validate_csrf_token, verify_password
from ..services.auth_totp import (
    authenticator_configured,
    credential_secret,
    ensure_pending_credential,
    ensure_totp_schema,
    get_credential,
    login_2fa_enabled,
    verify_totp,
)
from ..web import THEME_PRESETS, context, flash, templates

router = APIRouter(tags=["settings"])


@router.get("/settings")
def settings_page(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    ensure_totp_schema(db)
    return templates.TemplateResponse(
        request,
        "settings/index.html",
        context(
            request,
            user=user,
            authenticator_configured=authenticator_configured(db, int(user.id)),
            two_factor_enabled=login_2fa_enabled(db, int(user.id)),
        ),
    )


@router.get("/settings/appearance")
@router.get("/settings/notifications")
@router.get("/configuracoes")
@router.get("/configuracoes/estilos-formatacao")
@router.get("/configuracoes/estilos-de-formatacao")
def settings_alias_page(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/appearance")
def update_appearance(
    request: Request,
    theme_mode: str = Form("dark"),
    theme_preset: str = Form("ocean"),
    accent_color: str = Form("#26c5e6"),
    background_style: str = Form("gradient"),
    compact_mode: str | None = Form(None),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/settings", status_code=303)

    pref = user.preference
    pref.theme_mode = theme_mode if theme_mode in {"dark", "light", "system"} else "dark"
    pref.theme_preset = theme_preset if theme_preset in THEME_PRESETS else "ocean"
    pref.accent_color = accent_color if re.match(r"^#[0-9A-Fa-f]{6}$", accent_color) else THEME_PRESETS[pref.theme_preset]["primary"]
    pref.background_style = background_style if background_style in {"gradient", "plain", "soft"} else "gradient"
    pref.compact_mode = compact_mode == "on"
    db.commit()
    flash(request, "Aparência atualizada.", "success")
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/notifications")
def update_notification_preferences(
    request: Request,
    email_notifications: str | None = Form(None),
    in_app_notifications: str | None = Form(None),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/settings", status_code=303)
    user.preference.email_notifications = email_notifications == "on"
    user.preference.in_app_notifications = in_app_notifications == "on"
    db.commit()
    flash(request, "Preferências de notificação atualizadas.", "success")
    return RedirectResponse("/settings", status_code=303)



@router.post("/settings/security/authenticator/start")
def start_authenticator_setup(
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/settings", status_code=303)

    ensure_totp_schema(db)
    ensure_pending_credential(db, user, reset_secret=not authenticator_configured(db, int(user.id)))
    db.commit()
    return RedirectResponse("/setup-authenticator", status_code=303)


@router.post("/settings/security/2fa/enable")
def enable_login_2fa(
    request: Request,
    code: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/settings", status_code=303)

    credential = get_credential(db, int(user.id))
    if credential is None or not credential.enabled:
        return RedirectResponse("/setup-authenticator", status_code=303)

    if not verify_totp(credential_secret(credential), code):
        flash(request, "Código do Google Authenticator incorreto.", "error")
        return RedirectResponse("/settings", status_code=303)

    credential.login_2fa_enabled = True
    db.commit()
    flash(request, "Verificação em duas etapas ativada no login.", "success")
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/security/2fa/disable")
def disable_login_2fa(
    request: Request,
    code: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/settings", status_code=303)

    credential = get_credential(db, int(user.id))
    if credential is None or not credential.enabled:
        flash(request, "Google Authenticator não está configurado.", "info")
        return RedirectResponse("/settings", status_code=303)

    if not verify_totp(credential_secret(credential), code):
        flash(request, "Código do Google Authenticator incorreto.", "error")
        return RedirectResponse("/settings", status_code=303)

    # Mantém o Authenticator vinculado para recuperação de senha.
    credential.login_2fa_enabled = False
    db.commit()
    flash(
        request,
        "Código no login desativado. O Authenticator continua disponível para recuperar sua senha.",
        "success",
    )
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/security/authenticator/reset")
def reset_authenticator_from_settings(
    request: Request,
    password: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/settings", status_code=303)

    if not verify_password(password, user.password_hash):
        flash(request, "Senha atual incorreta.", "error")
        return RedirectResponse("/settings", status_code=303)

    ensure_pending_credential(db, user, reset_secret=True)
    db.commit()
    flash(request, "Novo QR Code preparado. Escaneie para concluir.", "success")
    return RedirectResponse("/setup-authenticator", status_code=303)
