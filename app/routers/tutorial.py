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
from ..services.tutorial_guides import TABS as GUIDE_TABS, guide_count

router = APIRouter(tags=["tutorial"])

# Adicione novos materiais neste catálogo; outros tipos (PDF/guias) podem
# ganhar uma rota protegida própria no futuro.
MEDIA_VERSION = "20261110-voz"
TUTORIAL_ITEMS = (
    {
        "slug": "cotacao",
        "tab": "inicio",
        "title": "Cotação e cálculo do início ao fim",
        "description": "O fluxo completo: base da viagem, calculadora, lucro com cartão sem juros, mensagem, arte e resumo interno.",
        "kind": "video",
        "duration": "2 min 50 s",
    },
    {"slug": "criar-cotacao", "tab": "inicio", "kind": "video", "duration": "1 min 15 s",
     "title": "1. Criar uma cotação do zero", "description": "Nome, origem e destino, datas, passageiros e o cliente escolhido em Pessoas."},
    {"slug": "calcular-e-comparar", "tab": "cotacao", "kind": "video", "duration": "1 min 20 s",
     "title": "2. Calcular em milhas e comparar companhias", "description": "Milhas na LATAM, Deságio na GOL e as opções lado a lado."},
    {"slug": "consolidadoras", "tab": "cotacao", "kind": "video", "duration": "1 min 15 s",
     "title": "3. Consolidadoras e o \"Operado por\"", "description": "Cotar pelo fornecedor e mostrar ao cliente só a companhia que opera o voo (vale também para milhas)."},
    {"slug": "lucro-e-whatsapp", "tab": "venda", "kind": "video", "duration": "1 min 5 s",
     "title": "4. Lucro, parcelamento e WhatsApp", "description": "Valor de venda, parcelas no cartão, arte e mensagem para o cliente."},
    {"slug": "aceitar-e-quadro", "tab": "venda", "kind": "video", "duration": "55 s",
     "title": "5. Aceitar o voo e acompanhar no quadro", "description": "Cotação nova ou existente, etapas da venda e responsável."},
    {"slug": "acompanhamentos", "tab": "posvenda", "kind": "video", "duration": "1 min 5 s",
     "title": "6. Acompanhamentos: hospedagem e mais", "description": "Cadastrar um serviço numa cotação e onde mover ou editar."},
    {"slug": "criar-programa", "tab": "cadastros", "kind": "video", "duration": "1 min 15 s",
     "title": "7. Criar um programa de milhas", "description": "Categoria, nome e o teste do cálculo na hora."},
)
for _item in TUTORIAL_ITEMS:
    # MEDIA_VERSION muda a URL quando os vídeos são regravados (evita cache antigo).
    _item.setdefault("video_url", f"/tutorial/video/{_item['slug']}?v={MEDIA_VERSION}")
    _item.setdefault("poster", f"/static/tutorial/videos/{_item['slug']}.webp?v={MEDIA_VERSION}")

WELCOME_KEY = "tutorial_welcome_seen_v1"
# Aviso de novidades: aparece uma única vez para cada usuário. Para anunciar
# novidades de novo no futuro, basta trocar a data desta chave.
NEWS_KEY = "novidades_seen_20261110"
MEDIA_DIR = Path(__file__).resolve().parents[1] / "media"
MEDIA_FILE = MEDIA_DIR / "tutorial-cotacao-dbmilesx.mp4"
# Só os vídeos do catálogo podem ser servidos (nada de caminho vindo da URL).
VIDEO_FILES = {item["slug"]: (MEDIA_FILE if item["slug"] == "cotacao" else MEDIA_DIR / "tutoriais" / f"{item['slug']}.mp4")
               for item in TUTORIAL_ITEMS if item.get("kind") == "video"}
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


def news_pending(user) -> bool:
    """Novidades: só para quem já passou pelas boas-vindas e ainda não viu o aviso."""
    if user is None or welcome_pending(user):
        return False
    return not bool(_settings(getattr(user, "preference", None)).get(NEWS_KEY))


def _acknowledge(db: Session, user, keys: tuple[str, ...] = (WELCOME_KEY, NEWS_KEY)) -> None:
    # Quem está chegando agora já encontra tudo novo: as boas-vindas também
    # marcam as novidades como vistas, para não mostrar dois avisos seguidos.
    pref = user.preference
    if pref is None:  # segurança para dados legados ainda sem preferências
        from ..models import UserPreference
        pref = UserPreference(user_id=user.id)
        db.add(pref)
    data = _settings(pref)
    if not all(data.get(key) for key in keys):
        for key in keys:
            data[key] = True
        pref.settings_json = json.dumps(data, ensure_ascii=False)
        db.commit()


GUIDE_IMAGE_DIR = Path(__file__).resolve().parents[1] / "static" / "tutorial"


def _available_images() -> set[str]:
    """Prints existentes; um guia sem print aparece só com os passos."""
    try:
        return {p.stem for p in GUIDE_IMAGE_DIR.glob("*.webp")}
    except OSError:
        return set()


@router.get("/tutorial")
def tutorial_page(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        request, "tutorial/index.html",
        context(request, user=user, tutorial_items=TUTORIAL_ITEMS, guide_tabs=GUIDE_TABS, guide_total=guide_count(), guide_images=_available_images()),
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


@router.post("/tutorial/novidades")
def tutorial_news(
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
        _acknowledge(db, user, (NEWS_KEY,))
    except Exception:
        db.rollback()
        flash(request, "Não foi possível salvar a confirmação das novidades.", "error")
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


def _read_video(start: int, end: int, path: Path = MEDIA_FILE) -> Iterator[bytes]:
    with path.open("rb") as stream:
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
    """Vídeo principal (endereço original, mantido)."""
    return tutorial_video_by_slug("cotacao", request, db)


@router.api_route("/tutorial/video/{slug}", methods=["GET", "HEAD"])
def tutorial_video_by_slug(slug: str, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return JSONResponse({"detail": "Faça login para assistir ao tutorial."}, status_code=401)
    video = VIDEO_FILES.get(slug)
    if video is None or not video.is_file():
        return JSONResponse({"detail": "Vídeo indisponível."}, status_code=404)
    size = video.stat().st_size
    selected = _video_range(request.headers.get("range"), size)
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Encoding": "identity",  # o GZipMiddleware não pode alterar os byte-ranges MP4
        "Cache-Control": "private, max-age=3600",
        "Vary": "Cookie",
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": f'inline; filename="tutorial-{slug}.mp4"',
    }
    if selected is None:
        headers["Content-Range"] = f"bytes */{size}"
        return JSONResponse({"detail": "Intervalo de vídeo inválido."}, status_code=416, headers=headers)
    start, end = selected
    headers.update({"Content-Range": f"bytes {start}-{end}/{size}", "Content-Length": str(end - start + 1)})
    if request.method == "HEAD":
        return StreamingResponse(iter(()), status_code=206, media_type="video/mp4", headers=headers)
    return StreamingResponse(_read_video(start, end, video), status_code=206, media_type="video/mp4", headers=headers)
