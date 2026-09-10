from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import current_user
from ..security import validate_csrf_token
from ..web import THEME_PRESETS, context, flash, templates

router = APIRouter(tags=["settings"])


@router.get("/settings")
def settings_page(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(request, "settings/index.html", context(request, user=user))


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
