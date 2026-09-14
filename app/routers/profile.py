from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from ..config import PROFILE_UPLOAD_DIR, SECRET_KEY
from ..database import get_db
from ..dependencies import current_user
from ..models import WebUser
from ..security import validate_csrf_token
from ..services.realtime import manager, profile_event
from ..services.storage import blob_delete, blob_ready
from ..services.uploads import delete_relative_upload, save_upload_image
from ..web import context, flash, templates

router = APIRouter(tags=["profile"])

_ALLOWED_AVATAR_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
_MAX_AVATAR_BYTES = 10 * 1024 * 1024
_AVATAR_INTENT_TTL = 5 * 60


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    value = str(value or "")
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _sign_avatar_intent(payload: dict) -> str:
    packed = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    body = _b64url_encode(packed)
    signature = hmac.new(str(SECRET_KEY).encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    return f"{body}.{_b64url_encode(signature)}"


def _blob_avatar_route(user_id: int, blob_url: str) -> str:
    return f"profile/avatar-file/{int(user_id)}/{_b64url_encode(blob_url.encode('utf-8'))}"


def _blob_url_from_avatar_path(path: str | None) -> str | None:
    value = str(path or "").strip()
    marker = "profile/avatar-file/"
    if not value.startswith(marker):
        return None
    parts = value[len(marker):].split("/", 1)
    if len(parts) != 2:
        return None
    try:
        return _b64url_decode(parts[1]).decode("utf-8")
    except Exception:
        return None


def _valid_blob_avatar_url(blob_url: str, user_id: int) -> bool:
    try:
        parsed = urlparse(str(blob_url or "").strip())
    except Exception:
        return False
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    if not (
        host.endswith(".private.blob.vercel-storage.com")
        or host.endswith(".blob.vercel-storage.com")
    ):
        return False
    pathname = unquote(parsed.path or "")
    return pathname.startswith(f"/users/{int(user_id)}/avatars/")


@router.get("/profile")
def profile_page(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(request, "profile/index.html", context(request, user=user))


@router.post("/profile/avatar-upload-intent")
async def avatar_upload_intent(request: Request, db: Session = Depends(get_db)):
    """Autoriza um upload direto navegador -> Vercel Blob sem enviar a imagem pela Function."""
    user = current_user(request, db)
    if user is None:
        return JSONResponse({"error": "Sessão expirada."}, status_code=401)
    if not blob_ready():
        return JSONResponse({"error": "Vercel Blob não está disponível neste ambiente."}, status_code=503)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Requisição inválida."}, status_code=400)

    csrf_token = str(body.get("csrf_token") or "")
    if not validate_csrf_token(request.session, csrf_token):
        return JSONResponse({"error": "Sessão expirada. Atualize a página e tente novamente."}, status_code=403)

    content_type = str(body.get("content_type") or "").lower().strip()
    try:
        size = int(body.get("size") or 0)
    except (TypeError, ValueError):
        size = 0

    if content_type not in _ALLOWED_AVATAR_TYPES:
        return JSONResponse({"error": "Use uma imagem JPG, PNG ou WEBP."}, status_code=400)
    if size <= 0 or size > _MAX_AVATAR_BYTES:
        return JSONResponse({"error": "A foto deve ter no máximo 10 MB."}, status_code=400)

    ext = _ALLOWED_AVATAR_TYPES[content_type]
    pathname = f"users/{user.id}/avatars/{int(time.time())}-{uuid.uuid4().hex[:12]}{ext}"
    payload = {
        "v": 1,
        "op": "put",
        "uid": int(user.id),
        "pathname": pathname,
        "ct": content_type,
        "max": _MAX_AVATAR_BYTES,
        "exp": int(time.time()) + _AVATAR_INTENT_TTL,
    }
    return JSONResponse({"intent": _sign_avatar_intent(payload)})


@router.get("/profile/avatar-file/{avatar_user_id}/{blob_ref}")
async def serve_private_avatar(
    avatar_user_id: int,
    blob_ref: str,
    request: Request,
    db: Session = Depends(get_db),
):
    viewer = current_user(request, db)
    if viewer is None:
        return Response(status_code=401)

    target = db.get(WebUser, int(avatar_user_id))
    if target is None:
        return Response(status_code=404)
    if viewer.id != target.id and viewer.company_id != target.company_id:
        return Response(status_code=403)

    try:
        blob_url = _b64url_decode(blob_ref).decode("utf-8")
    except Exception:
        return Response(status_code=404)
    if not _valid_blob_avatar_url(blob_url, target.id):
        return Response(status_code=404)

    # Não faz proxy dos bytes pelo FastAPI. Depois de validar sessão/empresa,
    # cria uma autorização curta para a Function Node gerar um GET assinado.
    parsed = urlparse(blob_url)
    pathname = unquote(parsed.path or "").lstrip("/")
    payload = {
        "v": 1,
        "op": "get",
        "uid": int(target.id),
        "pathname": pathname,
        "exp": int(time.time()) + 5 * 60,
    }
    intent = _sign_avatar_intent(payload)
    return RedirectResponse(
        url=f"/api/avatar-presign?intent={intent}",
        status_code=307,
        headers={"Cache-Control": "private, no-store"},
    )



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

    old_path = None
    avatar_path = None

    # Novo fluxo Vercel: o arquivo já foi enviado direto do navegador para o Blob.
    avatar_blob_url = str(form.get("avatar_blob_url") or "").strip()
    if avatar_blob_url:
        if not _valid_blob_avatar_url(avatar_blob_url, user.id):
            flash(request, "A foto enviada não pertence a este usuário.", "error")
            return RedirectResponse("/profile", status_code=303)
        avatar_path = _blob_avatar_route(user.id, avatar_blob_url)
    else:
        # Mantém compatibilidade com localhost e instalações antigas.
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

    if avatar_path:
        old_path = user.profile.avatar_path
        user.profile.avatar_path = avatar_path

    db.commit()
    db.refresh(user)
    db.refresh(user.profile)

    if old_path and old_path != avatar_path:
        old_blob_url = _blob_url_from_avatar_path(old_path)
        if old_blob_url:
            try:
                blob_delete(old_blob_url)
            except Exception:
                pass
        else:
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

    old_blob_url = _blob_url_from_avatar_path(old_path)
    if old_blob_url:
        try:
            blob_delete(old_blob_url)
        except Exception:
            pass
    else:
        delete_relative_upload(old_path)

    if user.company_id:
        await manager.broadcast(user.company_id, profile_event(user))

    flash(request, "Foto removida e atualizada em tempo real.", "success")
    return RedirectResponse("/profile", status_code=303)
