from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..config import PROFILE_UPLOAD_DIR
from ..database import get_db
from ..dependencies import current_user
from ..security import validate_csrf_token
from ..services.realtime import manager, profile_event
from ..services.uploads import delete_relative_upload, save_upload_image
from ..web import context, flash, templates

router = APIRouter(tags=["profile"])


@router.get("/profile")
def profile_page(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(request, "profile/index.html", context(request, user=user))


@router.post("/profile")
async def update_profile(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)

    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada. Tente novamente.", "error")
        return RedirectResponse("/profile", status_code=303)

    name = str(form.get("name") or "").strip()
    phone = str(form.get("phone") or "").strip()
    job_title = str(form.get("job_title") or "").strip()
    bio = str(form.get("bio") or "").strip()

    if len(name) < 2:
        flash(request, "Informe seu nome.", "error")
        return RedirectResponse("/profile", status_code=303)
    if len(phone) > 40 or len(job_title) > 120 or len(bio) > 1500:
        flash(request, "Um dos campos ultrapassou o limite permitido.", "error")
        return RedirectResponse("/profile", status_code=303)

    user.name = name
    user.phone = phone or None
    user.profile.job_title = job_title or None
    user.profile.bio = bio or None
    user.profile.updated_at = datetime.utcnow()

    upload = form.get("avatar")
    try:
        avatar_path = await save_upload_image(
            upload if getattr(upload, "filename", None) else None,
            PROFILE_UPLOAD_DIR,
            max_bytes=4 * 1024 * 1024,
            filename_prefix=f"user-{user.id}",
        )
    except ValueError as exc:
        flash(request, str(exc), "error")
        return RedirectResponse("/profile", status_code=303)

    old_path = None
    if avatar_path:
        old_path = user.profile.avatar_path
        user.profile.avatar_path = avatar_path

    db.commit()
    db.refresh(user)
    db.refresh(user.profile)
    if old_path:
        delete_relative_upload(old_path)

    if user.company_id:
        await manager.broadcast(user.company_id, profile_event(user))

    flash(request, "Perfil atualizado em tempo real para toda a equipe.", "success")
    return RedirectResponse("/profile", status_code=303)


@router.post("/profile/remove-avatar")
async def remove_avatar(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)

    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/profile", status_code=303)

    old_path = user.profile.avatar_path
    user.profile.avatar_path = None
    user.profile.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(user)
    db.refresh(user.profile)
    delete_relative_upload(old_path)

    if user.company_id:
        await manager.broadcast(user.company_id, profile_event(user))

    flash(request, "Foto removida e atualizada em tempo real.", "success")
    return RedirectResponse("/profile", status_code=303)
