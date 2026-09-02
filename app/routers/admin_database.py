from __future__ import annotations

import secrets
import string
from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select, func
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..dependencies import current_user
from ..models import WebUser, WebQuote, QuoteGroup, QuoteOptionIndex, WebCompany
from ..security import hash_password, validate_csrf_token
from ..web import context, flash, templates

router = APIRouter(prefix="/admin/database", tags=["admin-database"])


def _admin_allowed(user: WebUser | None) -> bool:
    return bool(user and user.active and user.role in {"admin", "gerente"})


def _temporary_password(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%"
    return "".join(secrets.choice(alphabet) for _ in range(length))


@router.get("")
def admin_database(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not _admin_allowed(user):
        flash(request, "Acesso restrito ao administrador.", "error")
        return RedirectResponse("/dashboard", status_code=303)

    company_filter = WebUser.company_id == user.company_id if user.company_id else True
    users = db.scalars(
        select(WebUser)
        .where(company_filter)
        .options(selectinload(WebUser.company))
        .order_by(WebUser.active.desc(), WebUser.name)
    ).all()

    stats = {
        "users": len(users),
        "active_users": sum(1 for item in users if item.active),
        "quotes": db.scalar(select(func.count(QuoteGroup.id)).where(QuoteGroup.company_id == user.company_id)) if user.company_id else db.scalar(select(func.count(QuoteGroup.id)).where(QuoteGroup.user_id == user.id)),
        "options": db.scalar(select(func.count(QuoteOptionIndex.quote_id))),
    }

    return templates.TemplateResponse(
        request,
        "admin/database.html",
        context(request, user=user, users=users, stats=stats, generated_password=request.session.pop("generated_password", None)),
    )


@router.post("/users/{user_id}/reset-password")
def reset_user_password(user_id: int, request: Request, csrf_token: str = Form(...), db: Session = Depends(get_db)):
    admin = current_user(request, db)
    if not _admin_allowed(admin):
        flash(request, "Acesso restrito ao administrador.", "error")
        return RedirectResponse("/dashboard", status_code=303)
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada. Tente novamente.", "error")
        return RedirectResponse("/admin/database", status_code=303)

    target = db.get(WebUser, user_id)
    if target is None or (admin.company_id and target.company_id != admin.company_id):
        flash(request, "Usuário não encontrado nessa empresa.", "error")
        return RedirectResponse("/admin/database", status_code=303)

    new_password = _temporary_password()
    target.password_hash = hash_password(new_password)
    db.commit()
    request.session["generated_password"] = {"name": target.name, "email": target.email, "password": new_password, "when": datetime.now().strftime("%d/%m/%Y - %H:%M")}
    flash(request, "Senha temporária gerada. Copie agora; por segurança ela não será exibida novamente.", "success")
    return RedirectResponse("/admin/database", status_code=303)


@router.post("/users/{user_id}/toggle")
def toggle_user(user_id: int, request: Request, csrf_token: str = Form(...), db: Session = Depends(get_db)):
    admin = current_user(request, db)
    if not _admin_allowed(admin):
        flash(request, "Acesso restrito ao administrador.", "error")
        return RedirectResponse("/dashboard", status_code=303)
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada. Tente novamente.", "error")
        return RedirectResponse("/admin/database", status_code=303)
    target = db.get(WebUser, user_id)
    if target is None or target.id == admin.id or (admin.company_id and target.company_id != admin.company_id):
        flash(request, "Usuário não pode ser alterado.", "error")
        return RedirectResponse("/admin/database", status_code=303)
    target.active = not target.active
    db.commit()
    flash(request, "Status do usuário atualizado.", "success")
    return RedirectResponse("/admin/database", status_code=303)
