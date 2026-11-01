"""Controla acesso a arquivos legados armazenados em /uploads.

NUNCA exponha o diretório inteiro via StaticFiles: caminho conhecido não
substitui autenticação nem verificação da empresa proprietária do arquivo.
"""
from __future__ import annotations

import json
from pathlib import PurePosixPath

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from ..models import (
    AcceptedQuote, Airline, ChatMessage, CompanyTask, Person,
    PersonAttachment, QuoteGroup, UserProfile, WebCompany, WebUser,
)


def clean_upload_path(raw: str) -> str | None:
    """Aceita apenas um caminho relativo canônico; rejeita tentativas de traversal."""
    if not isinstance(raw, str) or not raw or len(raw) > 450:
        return None
    if any(char in raw for char in ("\\", "\x00", "%", ":")):
        return None
    if raw.startswith("/") or "//" in raw:
        return None
    parts = PurePosixPath(raw).parts
    if len(parts) < 2 or any(part in {".", ".."} or part.startswith(".") for part in parts):
        return None
    if raw != "/".join(parts):
        return None
    return raw


def _visible(user, company_col, user_col):
    if user.company_id is not None:
        return company_col == user.company_id
    return user_col == user.id


def may_read_upload(db: Session, user: WebUser, relative: str, session: dict | None = None) -> bool:
    """Autorização positiva por registro associado ao arquivo; falha fechada.

    Não se pode conceder acesso pela extensão, pelo nome aleatório, pela
    existência do arquivo ou simplesmente porque o usuário fez login.
    """
    path = clean_upload_path(relative)
    if path is None:
        return False
    stored = f"uploads/{path}"
    category = path.split("/", 1)[0]

    if category == "airlines":
        scope = (
            or_(Airline.builtin.is_(True), Airline.owner_company_id == user.company_id)
            if user.company_id is not None else
            or_(Airline.builtin.is_(True), Airline.owner_user_id == user.id)
        )
        return db.scalar(select(Airline.id).where(Airline.logo_path == stored, scope).limit(1)) is not None

    if category == "companies":
        return (user.company_id is not None and db.scalar(
            select(WebCompany.id).where(WebCompany.id == user.company_id, WebCompany.logo_path == stored)
        ) is not None)

    if category == "profiles":
        query = select(UserProfile.user_id).join(WebUser, WebUser.id == UserProfile.user_id).where(
            UserProfile.avatar_path == stored, WebUser.active.is_(True),
            _visible(user, WebUser.company_id, WebUser.id),
        ).limit(1)
        return db.scalar(query) is not None

    if category == "persons":
        query = select(PersonAttachment.id).join(Person, Person.id == PersonAttachment.person_id).where(
            PersonAttachment.file_path == stored,
            _visible(user, Person.company_id, Person.user_id),
        ).limit(1)
        return db.scalar(query) is not None

    if category == "tasks":
        return db.scalar(select(CompanyTask.id).where(
            CompanyTask.photo_path == stored,
            _visible(user, CompanyTask.company_id, CompanyTask.created_by_user_id),
        ).limit(1)) is not None

    if category == "chat":
        # Compatibilidade com mensagens antigas. O chat novo já usa uma rota
        # própria que valida participantes: /company/chat/arquivos/{id}.
        if user.company_id is None:
            return False
        return db.scalar(select(ChatMessage.id).where(
            ChatMessage.attachment_path == stored,
            ChatMessage.company_id == user.company_id,
        ).limit(1)) is not None

    if category == "quotes":
        # Quotes usam /uploads/quotes/{group_id}/... . O arquivo só pode ser
        # lido se constar explicitamente nos metadados da cotação aceita.
        chunks = path.split("/")
        if len(chunks) < 3 or not chunks[1].isdigit():
            return False
        group_id = int(chunks[1])
        accepted = db.scalar(select(AcceptedQuote).join(
            QuoteGroup, QuoteGroup.id == AcceptedQuote.group_id
        ).where(
            AcceptedQuote.group_id == group_id,
            _visible(user, QuoteGroup.company_id, QuoteGroup.user_id),
            _visible(user, AcceptedQuote.company_id, AcceptedQuote.user_id),
        ).limit(1))
        if accepted is None:
            return False
        try:
            details = json.loads(accepted.extra_json or "{}")
        except (TypeError, ValueError):
            return False
        if not isinstance(details, dict):
            return False
        attachments = details.get("attachments")
        if isinstance(attachments, list) and any(
            isinstance(entry, dict) and entry.get("path") == stored for entry in attachments
        ):
            return True
        preview = details.get("preview")
        return isinstance(preview, dict) and preview.get("club_image_path") == stored

    if category == "group_documents":
        # Os PDFs em grupo mantêm a imagem somente na sessão do próprio editor.
        draft = (session or {}).get("group_pdf_draft")
        return isinstance(draft, dict) and draft.get("group_image_path") == stored

    # Diretórios antigos ou desconhecidos não são públicos por omissão.
    return False
