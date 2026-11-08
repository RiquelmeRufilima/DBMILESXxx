from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime
import logging
from pathlib import Path
from urllib.parse import unquote, urlparse

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..config import PROFILE_UPLOAD_DIR, SECRET_KEY, IS_VERCEL
from ..database import get_db
from ..dependencies import current_user
from ..models import WebUser, UserChatContact, PrivateChatMessage
from ..security import validate_csrf_token
from ..services.realtime import manager, profile_event
from ..services.storage import blob_delete, blob_get, blob_put, blob_ready
from ..services.uploads import delete_relative_upload, save_upload_image
from ..web import context, flash, templates

router = APIRouter(tags=["profile"])
logger = logging.getLogger(__name__)

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


def _is_valid_avatar_image(content: bytes, content_type: str) -> bool:
    # Confere cabeçalhos reais, sem confiar somente no Content-Type enviado.
    return (
        (content_type == "image/jpeg" and content.startswith(b"\xff\xd8\xff"))
        or (content_type == "image/png" and content.startswith(b"\x89PNG\r\n\x1a\n"))
        or (content_type == "image/webp" and content.startswith(b"RIFF") and content[8:12] == b"WEBP")
    )


def _replace_old_avatar(old_path: str | None, new_path: str | None) -> None:
    """Apaga o objeto anterior somente depois do commit da nova foto."""
    if not old_path or old_path == new_path:
        return
    try:
        old_blob_url = _blob_url_from_avatar_path(old_path)
        if old_blob_url:
            blob_delete(old_blob_url)
        else:
            delete_relative_upload(old_path)
    except Exception:
        # O avatar novo já é válido; uma falha de limpeza não deve desfazer o perfil.
        logger.exception("Falha ao excluir avatar antigo do armazenamento")


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


@router.post("/profile/avatar-upload-direct")
async def avatar_upload_direct(request: Request, db: Session = Depends(get_db)):
    """Recebe somente a imagem já otimizada (< 1 MB) e grava no Blob privado.

    O navegador reduz a foto antes do envio, então esta requisição fica bem abaixo
    do limite de payload da Vercel Function e não precisa de uma Function Node extra.
    """
    user = current_user(request, db)
    if user is None:
        return JSONResponse({"error": "Sessão expirada."}, status_code=401)
    if not blob_ready():
        return JSONResponse({"error": "Vercel Blob não está conectado a este deployment."}, status_code=503)

    csrf_token = str(request.headers.get("x-csrf-token") or "")
    if not validate_csrf_token(request.session, csrf_token):
        return JSONResponse({"error": "Sessão expirada. Atualize a página e tente novamente."}, status_code=403)

    content_type = str(request.headers.get("content-type") or "").split(";", 1)[0].lower().strip()
    if content_type not in _ALLOWED_AVATAR_TYPES:
        return JSONResponse({"error": "Use uma imagem JPG, PNG ou WEBP."}, status_code=400)

    content = await request.body()
    if not content:
        return JSONResponse({"error": "A imagem enviada está vazia."}, status_code=400)
    # O front limita a ~850 KB; deixamos uma pequena margem aqui.
    if len(content) > 1200 * 1024:
        return JSONResponse({"error": "A foto otimizada ficou muito grande. Escolha outra imagem."}, status_code=413)

    if not _is_valid_avatar_image(content, content_type):
        return JSONResponse({"error": "O arquivo não é uma imagem válida."}, status_code=400)

    ext = _ALLOWED_AVATAR_TYPES[content_type]
    pathname = f"users/{user.id}/avatars/{int(time.time())}-{uuid.uuid4().hex[:12]}{ext}"
    try:
        result = blob_put(pathname, content, content_type)
    except Exception as exc:
        return JSONResponse({"error": f"Falha ao gravar no Vercel Blob: {exc}"}, status_code=502)

    blob_url = str(result.get("url") or result.get("downloadUrl") or "").strip()
    if not blob_url:
        return JSONResponse({"error": "O Vercel Blob não devolveu a URL da foto."}, status_code=502)
    if not _valid_blob_avatar_url(blob_url, user.id):
        return JSONResponse({"error": "O Vercel Blob devolveu uma URL inesperada."}, status_code=502)

    return JSONResponse({"url": blob_url, "pathname": pathname})


def _can_view_avatar(db: Session, viewer: WebUser, target: WebUser) -> bool:
    """Privacidade: dono, equipe ou contatos com vínculo/conversa privada."""
    if viewer.id == target.id:
        return True
    if viewer.company_id and viewer.company_id == target.company_id:
        return True
    if db.scalar(select(UserChatContact.id).where(or_(
        (UserChatContact.owner_user_id == viewer.id) & (UserChatContact.contact_user_id == target.id),
        (UserChatContact.owner_user_id == target.id) & (UserChatContact.contact_user_id == viewer.id),
    )).limit(1)) is not None:
        return True
    # Quem recebeu a primeira mensagem pode ver a foto mesmo sem ter
    # cadastrado manualmente o remetente na agenda.
    return db.scalar(select(PrivateChatMessage.id).where(or_(
        (PrivateChatMessage.sender_id == viewer.id) & (PrivateChatMessage.recipient_id == target.id),
        (PrivateChatMessage.sender_id == target.id) & (PrivateChatMessage.recipient_id == viewer.id),
    )).limit(1)) is not None


def _blob_avatar_response(blob_url: str) -> Response:
    try:
        content, content_type = blob_get(blob_url)
    except Exception:
        logger.exception("Não foi possível ler avatar do armazenamento persistente")
        return Response(status_code=503, headers={"Cache-Control": "no-store"})
    return Response(
        content=content,
        media_type=content_type if content_type in _ALLOWED_AVATAR_TYPES else "image/jpeg",
        headers={
            "Cache-Control": "private, max-age=15, must-revalidate",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/profile/avatar/{avatar_user_id}")
def serve_current_avatar(avatar_user_id: int, request: Request, db: Session = Depends(get_db)):
    """Endereço estável: a mesma URL sempre consulta a foto atual no banco."""
    viewer = current_user(request, db)
    if viewer is None:
        return Response(status_code=401)
    target = db.get(WebUser, int(avatar_user_id))
    if target is None or not _can_view_avatar(db, viewer, target):
        return Response(status_code=403 if target else 404)
    stored = str(getattr(target.profile, "avatar_path", None) or "")
    if not stored:
        return Response(status_code=404, headers={"Cache-Control": "no-store"})
    blob_url = _blob_url_from_avatar_path(stored)
    if blob_url:
        if not _valid_blob_avatar_url(blob_url, target.id):
            return Response(status_code=404)
        return _blob_avatar_response(blob_url)
    # Fotos locais antigas seguem pela rota histórica. Uploads novos na
    # Vercel são sempre gravados em armazenamento permanente.
    if stored.startswith("uploads/profiles/") and ".." not in stored and "\\" not in stored:
        return RedirectResponse(f"/{stored}", status_code=307)
    return Response(status_code=404)


@router.get("/profile/avatar-file/{avatar_user_id}/{blob_ref}")
async def serve_private_avatar(
    avatar_user_id: int,
    blob_ref: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Compatibilidade para URLs de avatares emitidas antes desta correção."""
    viewer = current_user(request, db)
    if viewer is None:
        return Response(status_code=401)
    target = db.get(WebUser, int(avatar_user_id))
    if target is None or not _can_view_avatar(db, viewer, target):
        return Response(status_code=403 if target else 404)
    try:
        blob_url = _b64url_decode(blob_ref).decode("utf-8")
    except Exception:
        return Response(status_code=404)
    if not _valid_blob_avatar_url(blob_url, target.id):
        return Response(status_code=404)
    # Links antigos não podem ler Blobs já substituídos.
    if not target.profile or target.profile.avatar_path != _blob_avatar_route(target.id, blob_url):
        return Response(status_code=404)
    return _blob_avatar_response(blob_url)


@router.post("/profile")
async def update_profile(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
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
        # Compatibilidade sem JavaScript: upload persistente no Blob, quando
        # disponível, e armazenamento local apenas fora da Vercel.
        upload = form.get("avatar")
        if getattr(upload, "filename", None):
            if blob_ready():
                content = await upload.read()
                content_type = str(getattr(upload, "content_type", "") or "").lower().strip()
                if (content_type not in _ALLOWED_AVATAR_TYPES
                        or not content or len(content) > 1200 * 1024
                        or not _is_valid_avatar_image(content, content_type)):
                    flash(request, "Imagem inválida ou acima de 1,2 MB. Reduza a foto e tente novamente.", "error")
                    return RedirectResponse("/profile", status_code=303)
                ext = _ALLOWED_AVATAR_TYPES[content_type]
                pathname = f"users/{user.id}/avatars/{int(time.time())}-{uuid.uuid4().hex[:12]}{ext}"
                try:
                    result = blob_put(pathname, content, content_type)
                    blob_url = str(result.get("url") or result.get("downloadUrl") or "")
                    if not _valid_blob_avatar_url(blob_url, user.id):
                        raise ValueError("URL inesperada do armazenamento.")
                    avatar_path = _blob_avatar_route(user.id, blob_url)
                except Exception:
                    logger.exception("Falha ao guardar avatar no Blob")
                    flash(request, "Não foi possível salvar a foto. A anterior foi mantida.", "error")
                    return RedirectResponse("/profile", status_code=303)
            elif IS_VERCEL:
                flash(request, "Configure o Vercel Blob para salvar fotos de perfil permanentemente.", "error")
                return RedirectResponse("/profile", status_code=303)
            else:
                try:
                    avatar_path = await save_upload_image(
                        upload, PROFILE_UPLOAD_DIR,
                        max_bytes=4 * 1024 * 1024, filename_prefix=f"user-{user.id}",
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

    # Limpeza confirmada antes do redirect: BackgroundTasks em serverless
    # podem não executar depois da resposta HTTP.
    _replace_old_avatar(old_path, avatar_path)

    if user.company_id:
        await manager.broadcast(user.company_id, profile_event(user))

    flash(request, "Perfil atualizado em tempo real para toda a equipe.", "success")
    return RedirectResponse("/profile", status_code=303)


@router.post("/profile/remove-avatar")
async def remove_avatar(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
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

    _replace_old_avatar(old_path, None)

    if user.company_id:
        await manager.broadcast(user.company_id, profile_event(user))

    flash(request, "Foto removida e atualizada em tempo real.", "success")
    return RedirectResponse("/profile", status_code=303)
