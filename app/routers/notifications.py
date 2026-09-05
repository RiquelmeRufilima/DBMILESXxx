from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import current_user
from ..models import Notification
from ..security import validate_csrf_token
from ..web import context, flash, templates

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
def notifications_page(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    title_lower = func.lower(Notification.title)
    items = list(
        db.scalars(
            select(Notification)
            .where(
                Notification.user_id == user.id,
                func.lower(Notification.kind) != "quote",
                ~title_lower.like("atualização de cotação%"),
                ~title_lower.like("atualizacao de cotacao%"),
            )
            .order_by(desc(Notification.created_at))
            .limit(200)
        ).all()
    )
    return templates.TemplateResponse(request, "notifications/index.html", context(request, user=user, notifications=items))


@router.post("/{notification_id}/read")
async def mark_read(notification_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/notifications", status_code=303)
    item = db.scalar(select(Notification).where(Notification.id == notification_id, Notification.user_id == user.id))
    if item:
        item.read = True
        db.commit()
        if item.link:
            return RedirectResponse(item.link, status_code=303)
    return RedirectResponse("/notifications", status_code=303)


@router.post("/read-all")
async def mark_all_read(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/notifications", status_code=303)
    for item in db.scalars(select(Notification).where(Notification.user_id == user.id, Notification.read.is_(False))).all():
        item.read = True
    db.commit()
    flash(request, "Todas as notificações foram marcadas como lidas.", "success")
    return RedirectResponse("/notifications", status_code=303)
