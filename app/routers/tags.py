"""Etiquetas: página de gerenciamento (estilo Iddas) e API usada pelas telas."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import delete
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import current_user
from ..models import QuoteTagLink
from ..security import validate_csrf_token
from ..services.tags import (
    TAG_KINDS,
    TARGET_KINDS,
    TARGET_TAG_KIND,
    clean_color,
    clean_kind,
    clean_tag_name,
    create_tag,
    find_tag_by_name,
    get_tag,
    list_tags,
    set_target_tags,
    tag_payload,
    target_allowed,
)
from ..web import context, templates

router = APIRouter(prefix="/tags", tags=["tags"])


async def _payload(request: Request) -> dict:
    try:
        data = await request.json()
        return data if isinstance(data, dict) else {}
    except Exception:
        form = await request.form()
        return dict(form)


def _deny(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"ok": False, "message": message}, status_code=status)


def _bool(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "on", "yes", "sim"}


@router.get("")
def tags_page(request: Request, tipo: str = "", situacao: str = "ativo", db: Session = Depends(get_db)):
    """Página "Etiquetas": lista, filtro por tipo e situação, criar/editar/apagar."""
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    kind = tipo if tipo in TAG_KINDS else None
    situacao = situacao if situacao in {"ativo", "inativo", "todos"} else "ativo"
    active = None if situacao == "todos" else situacao == "ativo"
    tags = list_tags(db, user, with_usage=True, kind=kind, active=active)
    return templates.TemplateResponse(
        request,
        "tags/index.html",
        context(request, user=user, tags=tags, tag_kinds=TAG_KINDS, filtro_tipo=kind or "", filtro_situacao=situacao),
    )


@router.get("/api")
def tags_api(request: Request, kind: str = "", db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return _deny("Faça login novamente.", 401)
    tags = list_tags(db, user, with_usage=True, kind=kind if kind in TAG_KINDS else None)
    return JSONResponse({"ok": True, "tags": tags}, headers={"Cache-Control": "no-store"})


@router.post("")
async def tags_create(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return _deny("Faça login novamente.", 401)
    data = await _payload(request)
    if not validate_csrf_token(request.session, str(data.get("csrf_token") or "")):
        return _deny("Sessão expirada. Recarregue a página.", 403)
    tag, error = create_tag(db, user, str(data.get("name") or ""), str(data.get("color") or ""), clean_kind(data.get("kind")))
    if tag is None:
        return _deny(error)
    db.commit()
    return {"ok": True, "tag": tag_payload(tag)}


@router.post("/{tag_id}/update")
async def tags_update(tag_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return _deny("Faça login novamente.", 401)
    data = await _payload(request)
    if not validate_csrf_token(request.session, str(data.get("csrf_token") or "")):
        return _deny("Sessão expirada. Recarregue a página.", 403)
    tag = get_tag(db, user, tag_id)
    if tag is None:
        return _deny("Etiqueta não encontrada.", 404)

    name = clean_tag_name(data.get("name") or tag.name)
    if not name:
        return _deny("Digite o nome da etiqueta.")
    new_kind = clean_kind(data.get("kind"), tag.kind or "cotacao")
    if new_kind != (tag.kind or "cotacao"):
        # Trocar o tipo remove a etiqueta dos itens do tipo antigo.
        db.execute(delete(QuoteTagLink).where(QuoteTagLink.tag_id == tag.id))
    duplicate = find_tag_by_name(db, user, name, new_kind)
    if duplicate is not None and duplicate.id != tag.id:
        return _deny("Já existe uma etiqueta com esse nome nesse tipo.")
    tag.name = name
    tag.kind = new_kind
    if data.get("color"):
        tag.color = clean_color(str(data.get("color")))
    if "active" in data:
        tag.active = _bool(data.get("active"))
    db.commit()
    return {"ok": True, "tag": tag_payload(tag)}


@router.post("/{tag_id}/delete")
async def tags_delete(tag_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return _deny("Faça login novamente.", 401)
    data = await _payload(request)
    if not validate_csrf_token(request.session, str(data.get("csrf_token") or "")):
        return _deny("Sessão expirada. Recarregue a página.", 403)
    tag = get_tag(db, user, tag_id)
    if tag is None:
        return _deny("Etiqueta não encontrada.", 404)
    db.execute(delete(QuoteTagLink).where(QuoteTagLink.tag_id == tag.id))
    db.delete(tag)
    db.commit()
    return {"ok": True}


@router.post("/assign")
async def tags_assign(request: Request, db: Session = Depends(get_db)):
    """Define as etiquetas de um item.

    Corpo: {kind: "group"|"quote"|"flight"|"person", id: 123, tag_ids: [1,2],
            new_tag: "opcional", new_color: "#hex", csrf_token}
    """
    user = current_user(request, db)
    if user is None:
        return _deny("Faça login novamente.", 401)
    data = await _payload(request)
    if not validate_csrf_token(request.session, str(data.get("csrf_token") or "")):
        return _deny("Sessão expirada. Recarregue a página.", 403)

    target_kind = str(data.get("kind") or "")
    try:
        target_id = int(data.get("id") or 0)
    except (TypeError, ValueError):
        target_id = 0
    if target_kind not in TARGET_KINDS or target_id <= 0 or not target_allowed(db, user, target_kind, target_id):
        return _deny("Item não encontrado.", 404)

    raw_ids = data.get("tag_ids") or []
    if not isinstance(raw_ids, list):
        raw_ids = [raw_ids]
    tag_ids: list[int] = []
    for value in raw_ids[:50]:
        try:
            tag_ids.append(int(value))
        except (TypeError, ValueError):
            continue

    tag_kind = TARGET_TAG_KIND[target_kind]
    new_tag_name = clean_tag_name(data.get("new_tag"))
    created = None
    if new_tag_name:
        created, error = create_tag(db, user, new_tag_name, str(data.get("new_color") or ""), tag_kind)
        if created is None:
            return _deny(error)
        tag_ids.append(created.id)

    tags = set_target_tags(db, user, target_kind, target_id, tag_ids)
    db.commit()
    return {
        "ok": True,
        "tags": tags,
        "created": tag_payload(created) if created is not None else None,
        "all_tags": list_tags(db, user, kind=tag_kind),
    }
