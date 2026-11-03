from __future__ import annotations

from fastapi import APIRouter, Depends, Request
import os
from urllib.parse import urlsplit
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import desc, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import current_user
from ..models import Notification, PushSubscription
from ..security import validate_csrf_token
from ..web import context, flash, templates

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("/push/config")
def push_config(request: Request, db: Session = Depends(get_db)):
    if current_user(request, db) is None:
        return JSONResponse({"ok": False}, status_code=401)
    key = os.getenv("VAPID_PUBLIC_KEY", "").strip()
    configured = bool(key and os.getenv("VAPID_PRIVATE_KEY", "").strip() and os.getenv("VAPID_SUBJECT", "").strip())
    return {"ok": configured, "public_key": key if configured else ""}


@router.post("/push/subscribe")
async def push_subscribe(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return JSONResponse({"ok": False}, status_code=401)
    data = await request.json()
    if not validate_csrf_token(request.session, str(data.get("csrf_token") or "")):
        return JSONResponse({"ok": False, "message": "Sessão expirada."}, status_code=403)
    endpoint = str(data.get("endpoint") or "")
    keys = data.get("keys") or {}
    p256dh, auth = str(keys.get("p256dh") or ""), str(keys.get("auth") or "")
    host = (urlsplit(endpoint).hostname or "").lower()
    push_host = (host in {"fcm.googleapis.com", "updates.push.services.mozilla.com", "push.services.mozilla.com", "web.push.apple.com"}
                 or host.endswith(".notify.windows.com") or host.endswith(".push.apple.com"))
    if not endpoint.startswith("https://") or not push_host or len(endpoint) > 2048 or not (20 <= len(p256dh) <= 256) or not (10 <= len(auth) <= 256):
        return JSONResponse({"ok": False, "message": "Inscrição de dispositivo inválida."}, status_code=400)
    try:
        sub = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == endpoint))
        if sub is None:
            sub = PushSubscription(user_id=user.id, endpoint=endpoint, p256dh=p256dh, auth=auth)
            db.add(sub)
        else:
            sub.user_id, sub.p256dh, sub.auth = user.id, p256dh, auth
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        return JSONResponse({"ok": False, "message": "Serviço de notificações ainda não configurado no banco."}, status_code=503)
    return {"ok": True}


@router.post("/push/unsubscribe")
async def push_unsubscribe(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return JSONResponse({"ok": False}, status_code=401)
    data = await request.json()
    if not validate_csrf_token(request.session, str(data.get("csrf_token") or "")):
        return JSONResponse({"ok": False}, status_code=403)
    subscription = db.scalar(select(PushSubscription).where(
        PushSubscription.endpoint == str(data.get("endpoint") or ""), PushSubscription.user_id == user.id))
    if subscription:
        db.delete(subscription)
        db.commit()
    return {"ok": True}


@router.get("")
def notifications_page(request: Request, offset: int = 0, partial: bool = False, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    offset = min(max(offset, 0), 100000)
    rows = db.scalars(select(Notification).where(
        Notification.user_id == user.id,
        Notification.kind != "quote",
        ~func.lower(Notification.title).like("atualização de cotação%"),
        ~func.lower(Notification.title).like("atualizacao de cotacao%"),
    ).order_by(desc(Notification.created_at), desc(Notification.id)).offset(offset).limit(21)).all()
    return templates.TemplateResponse(request, "notifications/_items.html" if partial else "notifications/index.html",
                                      context(request, user=user, notifications=rows[:20],
                                              has_more=len(rows)>20, next_offset=offset+min(len(rows),20)))


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
