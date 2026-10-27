"""Etiquetas do histórico: criação, aplicação e filtro.

Cada etiqueta pertence à empresa (compartilhada com todos os membros) ou, se o
usuário não tem empresa, somente a ele. Uma etiqueta pode ser aplicada em:
  - "group": cotação principal (QuoteGroup)
  - "quote": cotação antiga/avulsa (WebQuote)
"""
from __future__ import annotations

import re
from collections import defaultdict

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from ..models import QuoteGroup, QuoteTag, QuoteTagLink, WebQuote, WebUser
from .protection import ensure_protection_schema

TARGET_KINDS = {"group", "quote"}
MAX_TAGS_PER_SCOPE = 200
DEFAULT_COLORS = [
    "#26c5e6", "#34d399", "#f59e0b", "#f472b6", "#a78bfa",
    "#60a5fa", "#f87171", "#facc15", "#2dd4bf", "#fb923c",
]
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def tag_scope_filter(user: WebUser):
    if user.company_id:
        return QuoteTag.company_id == user.company_id
    return and_(QuoteTag.company_id.is_(None), QuoteTag.user_id == user.id)


def clean_tag_name(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:40]


def clean_color(value: str | None, fallback_index: int = 0) -> str:
    value = str(value or "").strip()
    if _COLOR_RE.match(value):
        return value.lower()
    return DEFAULT_COLORS[fallback_index % len(DEFAULT_COLORS)]


def tag_payload(tag: QuoteTag, usage: int | None = None) -> dict:
    data = {"id": tag.id, "name": tag.name, "color": tag.color}
    if usage is not None:
        data["usage"] = int(usage)
    return data


def list_tags(db: Session, user: WebUser, *, with_usage: bool = False) -> list[dict]:
    ensure_protection_schema(db)
    tags = db.scalars(select(QuoteTag).where(tag_scope_filter(user)).order_by(func.lower(QuoteTag.name))).all()
    if not with_usage or not tags:
        return [tag_payload(tag) for tag in tags]
    counts = dict(
        db.execute(
            select(QuoteTagLink.tag_id, func.count(QuoteTagLink.id))
            .where(QuoteTagLink.tag_id.in_([tag.id for tag in tags]))
            .group_by(QuoteTagLink.tag_id)
        ).all()
    )
    return [tag_payload(tag, counts.get(tag.id, 0)) for tag in tags]


def get_tag(db: Session, user: WebUser, tag_id: int) -> QuoteTag | None:
    ensure_protection_schema(db)
    return db.scalar(select(QuoteTag).where(QuoteTag.id == int(tag_id), tag_scope_filter(user)))


def find_tag_by_name(db: Session, user: WebUser, name: str) -> QuoteTag | None:
    name = clean_tag_name(name)
    if not name:
        return None
    return db.scalar(
        select(QuoteTag).where(tag_scope_filter(user), func.lower(QuoteTag.name) == name.lower()).limit(1)
    )


def create_tag(db: Session, user: WebUser, name: str, color: str | None = None) -> tuple[QuoteTag | None, str]:
    """Cria (ou devolve a existente com o mesmo nome). Não faz commit."""
    ensure_protection_schema(db)
    name = clean_tag_name(name)
    if len(name) < 1:
        return None, "Digite o nome da etiqueta."
    existing = find_tag_by_name(db, user, name)
    if existing:
        return existing, ""
    total = db.scalar(select(func.count(QuoteTag.id)).where(tag_scope_filter(user))) or 0
    if total >= MAX_TAGS_PER_SCOPE:
        return None, f"Limite de {MAX_TAGS_PER_SCOPE} etiquetas atingido. Apague alguma antiga."
    tag = QuoteTag(
        company_id=user.company_id or None,
        user_id=user.id,
        name=name,
        color=clean_color(color, int(total)),
    )
    db.add(tag)
    db.flush()
    return tag, ""


def target_allowed(db: Session, user: WebUser, kind: str, target_id: int) -> bool:
    """Confere se o item do histórico pertence à empresa/usuário."""
    if kind == "group":
        access = QuoteGroup.company_id == user.company_id if user.company_id else QuoteGroup.user_id == user.id
        return db.scalar(select(QuoteGroup.id).where(QuoteGroup.id == int(target_id), access)) is not None
    if kind == "quote":
        access = WebQuote.company_id == user.company_id if user.company_id else WebQuote.user_id == user.id
        return db.scalar(select(WebQuote.id).where(WebQuote.id == int(target_id), access)) is not None
    return False


def set_target_tags(db: Session, user: WebUser, kind: str, target_id: int, tag_ids: list[int]) -> list[dict]:
    """Substitui as etiquetas do item pelas informadas. Não faz commit."""
    ensure_protection_schema(db)
    allowed = {
        tag.id: tag
        for tag in db.scalars(
            select(QuoteTag).where(tag_scope_filter(user), QuoteTag.id.in_([int(x) for x in tag_ids] or [0]))
        ).all()
    }
    scope_ids = select(QuoteTag.id).where(tag_scope_filter(user))
    current = db.scalars(
        select(QuoteTagLink).where(
            QuoteTagLink.target_kind == kind,
            QuoteTagLink.target_id == int(target_id),
            QuoteTagLink.tag_id.in_(scope_ids),
        )
    ).all()
    current_ids = {link.tag_id for link in current}
    for link in current:
        if link.tag_id not in allowed:
            db.delete(link)
    for tag_id in allowed:
        if tag_id not in current_ids:
            db.add(QuoteTagLink(tag_id=tag_id, target_kind=kind, target_id=int(target_id), created_by_user_id=user.id))
    db.flush()
    return [tag_payload(allowed[tag_id]) for tag_id in sorted(allowed, key=lambda i: allowed[i].name.lower())]


def tags_for_targets(db: Session, user: WebUser, kind: str, target_ids: list[int]) -> dict[int, list[dict]]:
    """Etiquetas de vários itens de uma vez (uma consulta só)."""
    result: dict[int, list[dict]] = defaultdict(list)
    if not target_ids:
        return result
    ensure_protection_schema(db)
    rows = db.execute(
        select(QuoteTagLink.target_id, QuoteTag)
        .join(QuoteTag, QuoteTag.id == QuoteTagLink.tag_id)
        .where(
            QuoteTagLink.target_kind == kind,
            QuoteTagLink.target_id.in_([int(x) for x in target_ids]),
            tag_scope_filter(user),
        )
        .order_by(func.lower(QuoteTag.name))
    ).all()
    for target_id, tag in rows:
        result[int(target_id)].append(tag_payload(tag))
    return result


def targets_with_all_tags(kind: str, tag_ids: list[int]):
    """Subconsulta: IDs de itens que têm TODAS as etiquetas selecionadas."""
    ids = sorted({int(x) for x in tag_ids})
    return (
        select(QuoteTagLink.target_id)
        .where(QuoteTagLink.target_kind == kind, QuoteTagLink.tag_id.in_(ids))
        .group_by(QuoteTagLink.target_id)
        .having(func.count(func.distinct(QuoteTagLink.tag_id)) == len(ids))
    )


def targets_matching_tag_text(user: WebUser, kind: str, text: str):
    """Subconsulta: itens com alguma etiqueta cujo nome contém o texto buscado."""
    pattern = f"%{text}%"
    return (
        select(QuoteTagLink.target_id)
        .join(QuoteTag, QuoteTag.id == QuoteTagLink.tag_id)
        .where(QuoteTagLink.target_kind == kind, tag_scope_filter(user), QuoteTag.name.ilike(pattern))
    )


def delete_links_for_targets(db: Session, kind: str, target_ids: list[int]) -> None:
    """Limpa etiquetas de itens excluídos (chamar antes do commit da exclusão)."""
    if not target_ids:
        return
    ensure_protection_schema(db)
    # Savepoint: se algo falhar aqui, a exclusão da cotação continua valendo.
    with db.begin_nested():
        db.execute(
            QuoteTagLink.__table__.delete().where(
                QuoteTagLink.target_kind == kind,
                QuoteTagLink.target_id.in_([int(x) for x in target_ids]),
            )
        )
