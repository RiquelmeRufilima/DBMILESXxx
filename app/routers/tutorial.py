"""Central de tutoriais DBMILESX e apresentação inicial por usuário.

Os vídeos não são públicos: a entrega é autenticada e limitada a blocos
menores que o limite de resposta das Vercel Functions.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterator

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import current_user
from ..security import validate_csrf_token
from ..web import context, flash, templates

router = APIRouter(tags=["tutorial"])

# Adicione novos materiais neste catálogo; outros tipos (PDF/guias) podem
# ganhar uma rota protegida própria no futuro.
TUTORIAL_ITEMS = (
    {
        "slug": "cotacao",
        "title": "Tutorial de cotação DBMILESX",
        "description": "Aprenda a criar uma cotação e a utilizar o fluxo principal do sistema.",
        "kind": "video",
        "duration": "4 min 50 s",
        "video_url": "/tutorial/video/cotacao",
    },
)

WELCOME_KEY = "tutorial_welcome_seen_v1"
MEDIA_FILE = Path(__file__).resolve().parents[1] / "media" / "tutorial-cotacao-dbmilesx.mp4"
MAX_VIDEO_BYTES = 2 * 1024 * 1024  # evita respostas superiores ao limite da Vercel
STREAM_BUFFER_BYTES = 128 * 1024


def _settings(preference) -> dict:
    if preference is None:
        return {}
    try:
        data = json.loads(preference.settings_json or "{}")
        return data if isinstance(data, dict) else {}
    except (TypeError, ValueError):
        return {}


def welcome_pending(user) -> bool:
    """Cada pessoa vê o aviso até aceitá-lo ou adiá-lo uma única vez."""
    if user is None:
        return False
    return not bool(_settings(getattr(user, "preference", None)).get(WELCOME_KEY))


def _acknowledge(db: Session, user) -> None:
    pref = user.preference
    if pref is None:  # segurança para dados legados ainda sem preferências
        from ..models import UserPreference
        pref = UserPreference(user_id=user.id)
        db.add(pref)
    data = _settings(pref)
    if not data.get(WELCOME_KEY):
        data[WELCOME_KEY] = True
        pref.settings_json = json.dumps(data, ensure_ascii=False)
        db.commit()


@router.get("/tutorial")
def tutorial_page(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        request, "tutorial/index.html",
        context(request, user=user, tutorial_items=TUTORIAL_ITEMS),
    )


@router.post("/tutorial/welcome")
def tutorial_welcome(
    request: Request,
    csrf_token: str = Form(...),
    destination: str = Form("tutorial"),
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sua sessão expirou. Tente novamente.", "error")
        return RedirectResponse("/dashboard", status_code=303)
    try:
        _acknowledge(db, user)
    except Exception:
        db.rollback()
        flash(request, "Não foi possível salvar a confirmação do tutorial.", "error")
        return RedirectResponse("/dashboard", status_code=303)
    return RedirectResponse("/dashboard" if destination == "later" else "/tutorial", status_code=303)


def _video_range(value: str | None, size: int) -> tuple[int, int] | None:
    """Valida byte-range simples; limita cada resposta a 2 MiB.

    Mesmo quando o cliente pede até o fim, retornamos um bloco parcial 206.
    O navegador solicita os blocos seguintes conforme o carregamento/seek.
    """
    if size <= 0:
        return None
    if not value:
        return 0, min(size - 1, MAX_VIDEO_BYTES - 1)
    m = re.fullmatch(r"bytes=(\d*)-(\d*)", value.strip(), re.IGNORECASE)
    if not m or not (m.group(1) or m.group(2)):
        return None
    a, b = m.groups()
    if not a:  # exemplo: bytes=-512
        length = int(b)
        if length <= 0:
            return None
        start = max(0, size - length)
        end = size - 1
    else:
        start = int(a)
        if start >= size:
            return None
        end = min(size - 1, int(b)) if b else size - 1
        if end < start:
            return None
    return start, min(end, start + MAX_VIDEO_BYTES - 1)


def _read_video(start: int, end: int) -> Iterator[bytes]:
    with MEDIA_FILE.open("rb") as stream:
        stream.seek(start)
        remaining = end - start + 1
        while remaining:
            data = stream.read(min(STREAM_BUFFER_BYTES, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data


@router.api_route("/tutorial/video/cotacao", methods=["GET", "HEAD"])
def tutorial_video(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return JSONResponse({"detail": "Faça login para assistir ao tutorial."}, status_code=401)
    if not MEDIA_FILE.is_file():
        return JSONResponse({"detail": "Vídeo indisponível."}, status_code=404)
    size = MEDIA_FILE.stat().st_size
    selected = _video_range(request.headers.get("range"), size)
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Encoding": "identity",  # o GZipMiddleware não pode alterar os byte-ranges MP4
        "Cache-Control": "private, max-age=3600",
        "Vary": "Cookie",
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": 'inline; filename="tutorial-cotacao-dbmilesx.mp4"',
    }
    if selected is None:
        headers["Content-Range"] = f"bytes */{size}"
        return JSONResponse({"detail": "Intervalo de vídeo inválido."}, status_code=416, headers=headers)
    start, end = selected
    headers.update({"Content-Range": f"bytes {start}-{end}/{size}", "Content-Length": str(end - start + 1)})
    if request.method == "HEAD":
        return StreamingResponse(iter(()), status_code=206, media_type="video/mp4", headers=headers)
    return StreamingResponse(_read_video(start, end), status_code=206, media_type="video/mp4", headers=headers)
