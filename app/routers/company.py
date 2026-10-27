from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from collections import defaultdict
from urllib.parse import quote as url_quote

from fastapi import APIRouter, Depends, Form, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy import desc, func, or_, select, update
from sqlalchemy.orm import Session, selectinload

from ..config import COMPANY_UPLOAD_DIR, MAX_TEAM_USERS, SECRET_KEY
from ..database import SessionLocal, get_db
from ..dependencies import current_user
from ..models import (
    AcceptedQuote,
    Airline,
    ChatAttachment,
    ChatMessage,
    CompanyTask,
    FlightRegistry,
    Person,
    PrivateChatMessage,
    PublicQuoteLink,
    QuoteActivity,
    QuoteBoardStatus,
    QuoteGroup,
    QuoteRequest,
    UserChatContact,
    WebCompany,
    WebQuote,
    WebUser,
)
from ..security import hash_password, validate_csrf_token, validate_password
from ..services.notifications import create_notification
from ..services.protection import register_attempt, seconds_until_allowed, set_blocked, wait_message
from ..services.team_accounts import remaining_team_slots, team_user_count
from ..services.uploads import delete_relative_upload, read_stored_attachment, save_chat_document, save_upload_image
from ..web import context, flash, iso_utc, templates

router = APIRouter(prefix="/company", tags=["company"])


# ---------------------------------------------------------------------------
# Empresa: código temporário de entrada, convites, membros e histórico
# ---------------------------------------------------------------------------

# Duração do código de entrada (padrão 5 minutos; pode ser alterado no Vercel
# pela variável de ambiente COMPANY_INVITE_MINUTES).
INVITE_CODE_MINUTES = max(1, int(os.getenv("COMPANY_INVITE_MINUTES", "5") or 5))
PENDING_INVITE_COOKIE = "dbm_company_invite"

ROLE_OPTIONS = [
    {"value": "membro", "label": "Consultor", "description": "Faz cotações e vê o histórico da empresa"},
    {"value": "gerente", "label": "Gerente", "description": "Acompanha a equipe e a operação"},
    {"value": "admin", "label": "Administrador", "description": "Gerencia membros, códigos e dados da empresa"},
]
VALID_ROLES = {item["value"] for item in ROLE_OPTIONS}


def _can_manage_company(user: WebUser) -> bool:
    """Somente administradores (incluindo o acesso principal) gerenciam a empresa."""
    return bool(user.company_id and (user.is_owner or user.role == "admin"))


def _normalize_company_name(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _to_base36(number: int) -> str:
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    if number <= 0:
        return "0"
    out = ""
    while number:
        number, rest = divmod(number, 36)
        out = alphabet[rest] + out
    return out


def _invite_signature(company_id: int, expires_at: int) -> str:
    raw = hmac.new(
        str(SECRET_KEY).encode("utf-8"),
        f"company-invite:{company_id}:{expires_at}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.b32encode(raw).decode("ascii")[:8]


def _make_invite_code(company_id: int) -> tuple[str, int]:
    """Gera um código assinado (não precisa de tabela nova no banco).

    Formato: <id da empresa>-<expiração em base36>-<assinatura>.
    Funciona em várias instâncias do Vercel porque é validado pela SECRET_KEY.
    """
    expires_at = int(time.time()) + INVITE_CODE_MINUTES * 60
    code = f"{company_id}-{_to_base36(expires_at)}-{_invite_signature(company_id, expires_at)}"
    return code, expires_at


def _parse_invite_code(code: str | None) -> tuple[int | None, str]:
    """Retorna (company_id, "") quando válido ou (None, mensagem de erro)."""
    value = re.sub(r"\s+", "", str(code or "")).upper()
    parts = value.split("-")
    if len(parts) != 3 or not parts[0].isdigit():
        return None, "Código inválido. Confira o código enviado pelo administrador."
    try:
        company_id = int(parts[0])
        expires_at = int(parts[1], 36)
    except ValueError:
        return None, "Código inválido. Confira o código enviado pelo administrador."
    if not hmac.compare_digest(parts[2], _invite_signature(company_id, expires_at)):
        return None, "Código inválido. Confira o código enviado pelo administrador."
    if expires_at < int(time.time()):
        return None, "Esse código expirou. Peça ao administrador para gerar um novo."
    return company_id, ""


def _invite_link(request: Request, company: WebCompany, code: str) -> str:
    base = str(request.base_url).rstrip("/")
    return f"{base}/company/join?empresa={url_quote(company.name)}&codigo={url_quote(code)}"


def _share_personal_history_with_company(db: Session, user: WebUser, company_id: int) -> None:
    """Leva o histórico pessoal (feito antes de entrar na empresa) para a empresa.

    Todo o histórico do sistema é filtrado por company_id quando o usuário tem
    empresa. Sem isso, as cotações antigas do usuário "sumiriam" ao entrar e não
    ficariam visíveis para os outros membros.
    """
    targets = [
        (WebQuote, WebQuote.user_id, WebQuote.company_id),
        (QuoteGroup, QuoteGroup.user_id, QuoteGroup.company_id),
        (AcceptedQuote, AcceptedQuote.user_id, AcceptedQuote.company_id),
        (FlightRegistry, FlightRegistry.user_id, FlightRegistry.company_id),
        (QuoteBoardStatus, QuoteBoardStatus.user_id, QuoteBoardStatus.company_id),
        (Person, Person.user_id, Person.company_id),
        (PublicQuoteLink, PublicQuoteLink.owner_user_id, PublicQuoteLink.company_id),
        (QuoteRequest, QuoteRequest.owner_user_id, QuoteRequest.company_id),
        (QuoteActivity, QuoteActivity.actor_user_id, QuoteActivity.company_id),
        (CompanyTask, CompanyTask.created_by_user_id, CompanyTask.company_id),
        (Airline, Airline.owner_user_id, Airline.owner_company_id),
    ]
    for model, owner_col, company_col in targets:
        try:
            with db.begin_nested():
                db.execute(
                    update(model)
                    .where(owner_col == user.id, company_col.is_(None))
                    .values({company_col.key: company_id})
                    .execution_options(synchronize_session=False)
                )
        except Exception:
            # Tabela/coluna opcional ainda não criada em uma base antiga:
            # não impede a entrada na empresa.
            continue


def _notify_company_admins(db: Session, company_id: int, title: str, body: str, exclude_user_id: int | None = None) -> None:
    admins = db.scalars(
        select(WebUser).where(
            WebUser.company_id == company_id,
            WebUser.active.is_(True),
            or_(WebUser.role == "admin", WebUser.is_owner.is_(True)),
        )
    ).all()
    for admin in admins:
        if exclude_user_id and admin.id == exclude_user_id:
            continue
        create_notification(db, admin.id, title, body, kind="company", link="/company#equipe", commit=False)


def _company_member_or_none(db: Session, user: WebUser, member_id: int) -> WebUser | None:
    member = db.get(WebUser, member_id)
    if member is None or member.company_id != user.company_id:
        return None
    return member


class ChatConnectionManager:
    def __init__(self) -> None:
        self.connections: dict[int, set[WebSocket]] = defaultdict(set)

    async def connect(self, company_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self.connections[company_id].add(websocket)

    def disconnect(self, company_id: int, websocket: WebSocket) -> None:
        self.connections[company_id].discard(websocket)

    async def broadcast(self, company_id: int, payload: dict) -> None:
        dead: list[WebSocket] = []
        for connection in list(self.connections.get(company_id, set())):
            try:
                await connection.send_json(payload)
            except Exception:
                dead.append(connection)
        for connection in dead:
            self.disconnect(company_id, connection)


manager = ChatConnectionManager()


def _new_contact_id(db: Session) -> str:
    """Gera um identificador público, separado do ID interno do banco."""
    for _ in range(40):
        value = f"DBM-{secrets.randbelow(1_000_000):06d}"
        exists = db.scalar(select(WebUser.id).where(WebUser.contact_id == value))
        if not exists:
            return value
    raise RuntimeError("Não foi possível gerar um ID de contato único.")


def _ensure_user_contact_id(db: Session, user: WebUser) -> None:
    if getattr(user, "contact_id", None):
        return
    user.contact_id = _new_contact_id(db)
    db.commit()
    db.refresh(user)


def _ensure_company_contact_ids(db: Session, company_id: int) -> None:
    members = db.scalars(select(WebUser).where(WebUser.company_id == company_id)).all()
    changed = False
    for member in members:
        if not getattr(member, "contact_id", None):
            member.contact_id = _new_contact_id(db)
            changed = True
    if changed:
        db.commit()


def _chat_member_payload(member: WebUser, current_user_id: int) -> dict:
    profile = getattr(member, "profile", None)
    return {
        "id": member.id,
        "name": member.name,
        "email": member.email,
        "contact_id": member.contact_id or "",
        "role": member.role,
        "active": bool(member.active),
        "is_me": member.id == current_user_id,
        "avatar_path": getattr(profile, "avatar_path", None) if profile else None,
    }


def _private_conversation_summaries(db: Session, user: WebUser) -> list[dict]:
    raw = db.scalars(
        select(PrivateChatMessage)
        .where(
            or_(
                PrivateChatMessage.sender_id == user.id,
                PrivateChatMessage.recipient_id == user.id,
            )
        )
        .order_by(desc(PrivateChatMessage.created_at))
        .limit(500)
    ).all()

    summaries: list[dict] = []
    seen: set[int] = set()
    for item in raw:
        partner_id = item.recipient_id if item.sender_id == user.id else item.sender_id
        if partner_id in seen:
            continue
        partner = db.get(WebUser, partner_id)
        if partner is None or not partner.active:
            continue
        _ensure_user_contact_id(db, partner)
        unread = db.scalar(
            select(func.count(PrivateChatMessage.id)).where(
                PrivateChatMessage.sender_id == partner_id,
                PrivateChatMessage.recipient_id == user.id,
                PrivateChatMessage.is_read.is_(False),
            )
        ) or 0
        summaries.append({
            "member": _chat_member_payload(partner, user.id),
            "last_message": item.message,
            "last_at": item.created_at,
            "unread": int(unread),
        })
        seen.add(partner_id)
    return summaries


def _saved_contacts(db: Session, user: WebUser) -> list[dict]:
    links = db.scalars(
        select(UserChatContact)
        .where(UserChatContact.owner_user_id == user.id)
        .order_by(UserChatContact.created_at)
    ).all()
    result: list[dict] = []
    for link in links:
        member = db.get(WebUser, link.contact_user_id)
        if member is None or not member.active:
            continue
        _ensure_user_contact_id(db, member)
        result.append(_chat_member_payload(member, user.id))
    return result


def _resolve_private_contact(db: Session, user: WebUser, contact_id: str | None) -> WebUser | None:
    contact_id = str(contact_id or "").strip().upper()
    if not contact_id:
        return None
    partner = db.scalar(
        select(WebUser).where(
            WebUser.contact_id == contact_id,
            WebUser.active.is_(True),
        )
    )
    if partner is None or partner.id == user.id:
        return None
    return partner


def _private_messages(db: Session, user: WebUser, partner: WebUser, limit: int = 120) -> list[PrivateChatMessage]:
    messages = db.scalars(
        select(PrivateChatMessage)
        .where(
            or_(
                (PrivateChatMessage.sender_id == user.id) & (PrivateChatMessage.recipient_id == partner.id),
                (PrivateChatMessage.sender_id == partner.id) & (PrivateChatMessage.recipient_id == user.id),
            )
        )
        .order_by(desc(PrivateChatMessage.created_at))
        .limit(limit)
    ).all()
    messages = list(reversed(messages))

    changed = False
    for item in messages:
        if item.recipient_id == user.id and not item.is_read:
            item.is_read = True
            changed = True
    if changed:
        db.commit()
    return messages


_CHAT_SCHEMA_READY = False


def _ensure_chat_schema(db: Session) -> None:
    """Cria a tabela de anexos do chat na primeira vez (Vercel/Neon sem migração)."""
    global _CHAT_SCHEMA_READY
    if _CHAT_SCHEMA_READY:
        return
    try:
        ChatAttachment.__table__.create(bind=db.get_bind(), checkfirst=True)
    except Exception:  # pragma: no cover - corrida entre instâncias
        pass
    _CHAT_SCHEMA_READY = True


def _attachment_payload(att: ChatAttachment | None) -> dict | None:
    if att is None:
        return None
    return {
        "id": att.id,
        "name": att.file_name,
        "type": att.file_type,
        "size": int(att.file_size or 0),
        "url": f"/company/chat/arquivos/{att.id}",
        "is_image": str(att.file_type or "").startswith("image/"),
    }


def _attachments_for(db: Session, kind: str, message_ids: list[int]) -> dict[int, dict]:
    if not message_ids:
        return {}
    _ensure_chat_schema(db)
    try:
        rows = db.scalars(
            select(ChatAttachment).where(ChatAttachment.kind == kind, ChatAttachment.message_id.in_(message_ids))
        ).all()
    except Exception:
        db.rollback()
        return {}
    return {row.message_id: _attachment_payload(row) for row in rows}


def _private_message_payload(item: PrivateChatMessage, user: WebUser, attachment: dict | None = None) -> dict:
    sender = item.sender if getattr(item, "sender", None) else None
    return {
        "id": item.id,
        "sender_id": item.sender_id,
        "recipient_id": item.recipient_id,
        "user_id": item.sender_id,
        "user_name": sender.name if sender else ("Você" if item.sender_id == user.id else "Usuário"),
        "message": item.message,
        "is_read": bool(item.is_read),
        "created_at": iso_utc(item.created_at),
        "attachment": attachment,
    }


def _group_message_payload(item: ChatMessage, attachment: dict | None = None) -> dict:
    return {
        "id": item.id,
        "user_id": item.user_id,
        "user_name": item.user.name if item.user else "Usuário",
        "message": item.message,
        "created_at": iso_utc(item.created_at),
        "attachment": attachment,
    }


@router.get("")
def company_dashboard(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)

    if not user.company_id:
        # Usuário sem empresa: se abriu um link de convite antes de entrar,
        # leva direto para a tela de entrada com os dados preenchidos.
        pending = request.cookies.get(PENDING_INVITE_COOKIE)
        if pending:
            response = RedirectResponse(f"/company/join?{pending}", status_code=303)
            response.delete_cookie(PENDING_INVITE_COOKIE)
            return response
        return templates.TemplateResponse(request, "company/index.html", context(request, user=user))

    company = db.get(WebCompany, user.company_id)
    if company is None:
        user.company_id = None
        db.commit()
        return RedirectResponse("/company", status_code=303)

    _ensure_company_contact_ids(db, user.company_id)
    members = db.scalars(
        select(WebUser)
        .where(WebUser.company_id == user.company_id)
        .order_by(WebUser.is_owner.desc(), WebUser.name)
    ).all()
    total_quotes = db.scalar(select(func.count(WebQuote.id)).where(WebQuote.company_id == user.company_id)) or 0
    total_value = db.scalar(
        select(func.coalesce(func.sum(WebQuote.total), 0)).where(WebQuote.company_id == user.company_id)
    ) or 0
    last_messages = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.company_id == user.company_id)
        .options(selectinload(ChatMessage.user))
        .order_by(desc(ChatMessage.created_at))
        .limit(6)
    ).all()
    last_messages = list(reversed(last_messages))

    return templates.TemplateResponse(request, "company/dashboard.html",
        context(
            request,
            user=user,
            company=company,
            members=members,
            total_quotes=total_quotes,
            total_value=total_value,
            last_messages=last_messages,
            active_count=sum(1 for member in members if member.active),
            team_count=team_user_count(db, user.company_id),
            max_team_users=MAX_TEAM_USERS,
            remaining_slots=remaining_team_slots(db, user.company_id),
            can_manage_members=_can_manage_company(user),
            role_options=ROLE_OPTIONS,
            invite_minutes=INVITE_CODE_MINUTES,
        ),
    )


@router.get("/create")
def create_company_page(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if user.company_id:
        return RedirectResponse("/company", status_code=303)
    return templates.TemplateResponse(request, "company/create.html", context(request, user=user))


@router.post("/create")
def create_company(
    request: Request,
    name: str = Form(...),
    cnpj: str = Form(""),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if user.company_id:
        return RedirectResponse("/company", status_code=303)
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/company/create", status_code=303)

    name = re.sub(r"\s+", " ", name).strip()[:180]
    if len(name) < 2:
        flash(request, "Informe o nome da empresa.", "error")
        return RedirectResponse("/company/create", status_code=303)

    normalized = _normalize_company_name(name)
    existing_names = db.scalars(select(WebCompany.name)).all()
    if any(_normalize_company_name(item) == normalized for item in existing_names):
        flash(request, "Já existe uma empresa com esse nome. Para entrar nela, peça o código ao administrador.", "error")
        return RedirectResponse("/company/create", status_code=303)

    company = WebCompany(name=name, cnpj=cnpj.strip()[:30] or None)
    db.add(company)
    db.flush()
    user.company_id = company.id
    user.role = "admin"
    user.is_owner = True
    _share_personal_history_with_company(db, user, company.id)
    db.commit()
    flash(request, f"Empresa '{name}' criada. Gere um código para convidar sua equipe.", "success")
    return RedirectResponse("/company", status_code=303)


@router.get("/join")
def join_company_page(request: Request, empresa: str = "", codigo: str = "", db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        # Guarda o convite e, depois do login, /company abre esta tela preenchida.
        response = RedirectResponse("/login", status_code=303)
        if empresa or codigo:
            query = f"empresa={url_quote(empresa[:180])}&codigo={url_quote(codigo[:60])}"
            response.set_cookie(PENDING_INVITE_COOKIE, query, max_age=60 * 60, httponly=True, samesite="lax")
            flash(request, "Entre na sua conta DBMILESX para aceitar o convite da empresa.", "info")
        return response
    if user.company_id:
        company = db.get(WebCompany, user.company_id)
        flash(request, f"Você já faz parte de {company.name if company else 'uma empresa'}. Saia dela antes de entrar em outra.", "info")
        return RedirectResponse("/company", status_code=303)
    response = templates.TemplateResponse(
        request,
        "company/join.html",
        context(request, user=user, prefill_company=empresa[:180], prefill_code=codigo[:60]),
    )
    response.delete_cookie(PENDING_INVITE_COOKIE)
    return response


@router.post("/join")
def join_company(
    request: Request,
    company_name: str = Form(""),
    code: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if user.company_id:
        return RedirectResponse("/company", status_code=303)

    back = f"/company/join?empresa={url_quote(company_name[:180])}&codigo={url_quote(code[:60])}"
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada. Tente novamente.", "error")
        return RedirectResponse(back, status_code=303)

    wait = seconds_until_allowed(db, "company_join", str(user.id))
    if wait:
        flash(request, wait_message(wait), "error")
        return RedirectResponse(back, status_code=303)

    company_id, error = _parse_invite_code(code)
    if company_id is None:
        register_attempt(db, "company_join", str(user.id))
        flash(request, error, "error")
        return RedirectResponse(back, status_code=303)

    company = db.get(WebCompany, company_id)
    if company is None:
        flash(request, "Empresa não encontrada. Peça um novo código ao administrador.", "error")
        return RedirectResponse(back, status_code=303)

    if company_name.strip() and _normalize_company_name(company_name) != _normalize_company_name(company.name):
        register_attempt(db, "company_join", str(user.id))
        flash(request, "O nome da empresa não confere com o código. Confira com o administrador.", "error")
        return RedirectResponse(back, status_code=303)

    if remaining_team_slots(db, company.id) <= 0:
        flash(request, "Essa empresa não tem vagas disponíveis. Fale com o administrador.", "error")
        return RedirectResponse(back, status_code=303)

    user.company_id = company.id
    user.role = "membro"
    user.is_owner = False
    _share_personal_history_with_company(db, user, company.id)
    _notify_company_admins(
        db,
        company.id,
        "Novo membro na empresa",
        f"{user.name} ({user.email}) entrou em {company.name} usando o código de entrada.",
        exclude_user_id=user.id,
    )
    db.commit()
    flash(request, f"Você entrou em {company.name}! O histórico agora é compartilhado com a equipe.", "success")
    return RedirectResponse("/company", status_code=303)


@router.get("/invite-code")
def generate_invite_code(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return JSONResponse({"ok": False, "error": "Faça login novamente."}, status_code=401)
    if not _can_manage_company(user):
        return JSONResponse({"ok": False, "error": "Somente administradores da empresa podem gerar códigos."}, status_code=403)
    company = db.get(WebCompany, user.company_id)
    if company is None:
        return JSONResponse({"ok": False, "error": "Empresa não encontrada."}, status_code=404)
    if remaining_team_slots(db, company.id) <= 0:
        return JSONResponse({"ok": False, "error": "Sem vagas disponíveis na equipe."}, status_code=400)

    code, expires_at = _make_invite_code(company.id)
    invite_url = _invite_link(request, company, code)
    share_text = (
        f"Você foi convidado(a) para entrar na empresa {company.name} no DBMILESX.\n\n"
        f"Empresa: {company.name}\nCódigo: {code}\n"
        f"(válido por {INVITE_CODE_MINUTES} minutos)\n\n"
        f"Entre pelo link: {invite_url}"
    )
    return JSONResponse(
        {
            "ok": True,
            "code": code,
            "expires_at": expires_at,
            "minutes": INVITE_CODE_MINUTES,
            "company_name": company.name,
            "invite_url": invite_url,
            "share_text": share_text,
            "whatsapp_url": "https://wa.me/?text=" + url_quote(share_text),
        },
        headers={"Cache-Control": "no-store"},
    )


@router.post("/leave")
def leave_company(request: Request, csrf_token: str = Form(...), db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if not user.company_id:
        return RedirectResponse("/company", status_code=303)
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/company", status_code=303)
    if user.is_owner:
        flash(request, "O acesso principal não pode sair da empresa.", "error")
        return RedirectResponse("/company", status_code=303)

    company = db.get(WebCompany, user.company_id)
    company_id = user.company_id
    user.company_id = None
    user.role = "membro"
    user.is_owner = False
    if company:
        _notify_company_admins(db, company_id, "Membro saiu da empresa", f"{user.name} saiu de {company.name}.")
    db.commit()
    flash(request, "Você saiu da empresa. As cotações feitas continuam no histórico da empresa.", "success")
    return RedirectResponse("/company", status_code=303)


@router.post("/members/create")
def create_member(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form("membro"),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if not _can_manage_company(user):
        flash(request, "Somente administradores podem criar usuários da empresa.", "error")
        return RedirectResponse("/company", status_code=303)
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/company", status_code=303)
    if remaining_team_slots(db, user.company_id) <= 0:
        flash(request, "Limite de usuários atingido.", "error")
        return RedirectResponse("/company", status_code=303)

    name = name.strip()[:180]
    email = email.strip().lower()[:180]
    if len(name) < 2 or "@" not in email:
        flash(request, "Informe nome e e-mail válidos.", "error")
        return RedirectResponse("/company#adicionar-membro", status_code=303)
    ok, message = validate_password(password)
    if not ok:
        flash(request, message, "error")
        return RedirectResponse("/company#adicionar-membro", status_code=303)

    existing = db.scalar(select(WebUser).where(func.lower(WebUser.email) == email))
    if existing is not None:
        if existing.company_id == user.company_id:
            flash(request, "Esse usuário já faz parte da empresa.", "info")
        elif existing.company_id:
            flash(request, "Esse e-mail já pertence a outra empresa.", "error")
        else:
            flash(request, "Esse e-mail já tem conta no DBMILESX. Gere um código de entrada e envie para a pessoa.", "error")
        return RedirectResponse("/company#codigo-entrada", status_code=303)

    member = WebUser(
        name=name,
        email=email,
        password_hash=hash_password(password),
        role=role if role in VALID_ROLES else "membro",
        active=True,
        is_owner=False,
        company_id=user.company_id,
    )
    db.add(member)
    db.flush()
    member.contact_id = _new_contact_id(db)
    db.commit()
    flash(request, f"{member.name} foi criado e adicionado à empresa.", "success")
    return RedirectResponse("/company#equipe", status_code=303)


@router.post("/members/add")
def add_member(
    request: Request,
    email: str = Form(...),
    role: str = Form("membro"),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if not _can_manage_company(user):
        flash(request, "Você não tem permissão para gerenciar membros.", "error")
        return RedirectResponse("/company", status_code=303)
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/company", status_code=303)
    if remaining_team_slots(db, user.company_id) <= 0:
        flash(request, "Limite de usuários atingido.", "error")
        return RedirectResponse("/company", status_code=303)

    member = db.scalar(select(WebUser).where(func.lower(WebUser.email) == email.strip().lower()))
    if member is None:
        flash(request, "Esse e-mail ainda não possui conta. Peça para a pessoa se cadastrar primeiro.", "error")
        return RedirectResponse("/company", status_code=303)
    if member.company_id and member.company_id != user.company_id:
        flash(request, "Esse usuário já pertence a outra empresa.", "error")
        return RedirectResponse("/company", status_code=303)

    member.company_id = user.company_id
    member.role = role if role in VALID_ROLES else "membro"
    _share_personal_history_with_company(db, member, user.company_id)
    db.commit()
    flash(request, f"{member.name} foi adicionado à equipe.", "success")
    return RedirectResponse("/company", status_code=303)


@router.post("/members/{member_id}/update")
def update_member(
    member_id: int,
    request: Request,
    role: str = Form("membro"),
    active: str = Form(""),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if not _can_manage_company(user) or not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sem permissão ou sessão expirada.", "error")
        return RedirectResponse("/company", status_code=303)
    member = _company_member_or_none(db, user, member_id)
    if member is None or member.is_owner or member.id == user.id:
        flash(request, "Esse acesso não pode ser alterado.", "error")
        return RedirectResponse("/company#equipe", status_code=303)

    member.role = role if role in VALID_ROLES else "membro"
    new_active = active == "1"
    if member.active and not new_active:
        member.auth_version = int(member.auth_version or 1) + 1  # encerra sessões abertas
    member.active = new_active
    # Marca o bloqueio como feito pelo administrador: impede que a pessoa
    # reative a conta sozinha pelo fluxo de cadastro/confirmação de e-mail.
    set_blocked(db, member.id, not new_active, by_user_id=user.id)
    db.commit()
    flash(request, f"Acesso de {member.name} atualizado.", "success")
    return RedirectResponse("/company#equipe", status_code=303)


@router.post("/members/{member_id}/reset-password")
def reset_member_password(
    member_id: int,
    request: Request,
    password: str = Form(...),
    password_confirm: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if not _can_manage_company(user) or not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sem permissão ou sessão expirada.", "error")
        return RedirectResponse("/company", status_code=303)
    member = _company_member_or_none(db, user, member_id)
    if member is None or member.is_owner or member.id == user.id:
        flash(request, "Essa senha não pode ser alterada por aqui.", "error")
        return RedirectResponse("/company#equipe", status_code=303)
    if password != password_confirm:
        flash(request, "As senhas não conferem.", "error")
        return RedirectResponse("/company#equipe", status_code=303)
    ok, message = validate_password(password)
    if not ok:
        flash(request, message, "error")
        return RedirectResponse("/company#equipe", status_code=303)

    member.password_hash = hash_password(password)
    member.auth_version = int(member.auth_version or 1) + 1
    db.commit()
    flash(request, f"Senha de {member.name} alterada. Os acessos antigos foram encerrados.", "success")
    return RedirectResponse("/company#equipe", status_code=303)


@router.post("/members/{member_id}/remove")
def remove_member(member_id: int, request: Request, csrf_token: str = Form(...), db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if not _can_manage_company(user) or not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sem permissão ou sessão expirada.", "error")
        return RedirectResponse("/company", status_code=303)
    member = _company_member_or_none(db, user, member_id)
    if member is None or member.is_owner or member.id == user.id:
        flash(request, "Esse acesso não pode ser removido.", "error")
        return RedirectResponse("/company#equipe", status_code=303)

    member.company_id = None
    member.role = "membro"
    member.is_owner = False
    db.commit()
    flash(request, f"{member.name} foi removido da empresa. As cotações dele continuam no histórico.", "success")
    return RedirectResponse("/company#equipe", status_code=303)


@router.get("/chat")
def chat_page(request: Request, contact: str = "", view: str = "conversations", db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)

    _ensure_user_contact_id(db, user)

    company = db.get(WebCompany, user.company_id) if user.company_id else None
    if user.company_id:
        _ensure_company_contact_ids(db, user.company_id)

    group_messages: list[ChatMessage] = []
    if user.company_id:
        group_messages = db.scalars(
            select(ChatMessage)
            .where(ChatMessage.company_id == user.company_id)
            .options(selectinload(ChatMessage.user))
            .order_by(desc(ChatMessage.created_at))
            .limit(100)
        ).all()
        group_messages = list(reversed(group_messages))

    selected_contact = _resolve_private_contact(db, user, contact)
    private_messages = _private_messages(db, user, selected_contact) if selected_contact else []

    return templates.TemplateResponse(
        request,
        "company/chat.html",
        context(
            request,
            user=user,
            company=company,
            has_company=bool(user.company_id and company),
            messages=group_messages,
            conversations=_private_conversation_summaries(db, user),
            contacts=_saved_contacts(db, user),
            selected_contact=_chat_member_payload(selected_contact, user.id) if selected_contact else None,
            private_messages=private_messages,
            chat_view="team" if view == "team" else "conversations",
        ),
    )


@router.get("/chat/sidebar")
def chat_sidebar_api(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return JSONResponse({"ok": False}, status_code=401)

    _ensure_user_contact_id(db, user)
    company = db.get(WebCompany, user.company_id) if user.company_id else None
    group_last = None
    if user.company_id:
        group_last = db.scalar(
            select(ChatMessage)
            .where(ChatMessage.company_id == user.company_id)
            .order_by(desc(ChatMessage.created_at))
            .limit(1)
        )

    conversations = _private_conversation_summaries(db, user)
    return {
        "ok": True,
        "has_company": bool(company),
        "group": {
            "name": company.name if company else "Chat da equipe",
            "last_message": group_last.message if group_last else "",
            "last_at": iso_utc(group_last.created_at) if group_last else None,
        },
        "conversations": [
            {
                **item["member"],
                "last_message": item["last_message"],
                "last_at": iso_utc(item["last_at"]),
                "unread": item["unread"],
            }
            for item in conversations
        ],
        "contacts": _saved_contacts(db, user),
    }


@router.post("/chat/contacts")
async def add_chat_contact(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return JSONResponse({"ok": False}, status_code=401)

    _ensure_user_contact_id(db, user)
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    if not validate_csrf_token(request.session, str(payload.get("csrf_token") or "")):
        return JSONResponse({"ok": False, "message": "Sessão expirada."}, status_code=403)

    wait = seconds_until_allowed(db, "contact_lookup", str(user.id))
    if wait:
        return JSONResponse({"ok": False, "message": wait_message(wait)}, status_code=429)

    contact_id = str(payload.get("contact_id") or "").strip().upper()
    partner = _resolve_private_contact(db, user, contact_id)
    if partner is None:
        register_attempt(db, "contact_lookup", str(user.id))
        return JSONResponse({"ok": False, "message": "ID de contato não encontrado."}, status_code=404)

    exists = db.scalar(
        select(UserChatContact.id).where(
            UserChatContact.owner_user_id == user.id,
            UserChatContact.contact_user_id == partner.id,
        )
    )
    if not exists:
        db.add(UserChatContact(owner_user_id=user.id, contact_user_id=partner.id))
        db.commit()

    return {"ok": True, "contact": _chat_member_payload(partner, user.id)}


@router.delete("/chat/contacts/{contact_id}")
async def remove_chat_contact(contact_id: str, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return JSONResponse({"ok": False}, status_code=401)

    try:
        payload = await request.json()
    except Exception:
        payload = {}

    if not validate_csrf_token(request.session, str(payload.get("csrf_token") or "")):
        return JSONResponse({"ok": False, "message": "Sessão expirada."}, status_code=403)

    if seconds_until_allowed(db, "contact_lookup", str(user.id)):
        return JSONResponse({"ok": False, "message": "Muitas tentativas. Aguarde alguns minutos."}, status_code=429)
    partner = _resolve_private_contact(db, user, contact_id)
    if partner is None:
        register_attempt(db, "contact_lookup", str(user.id))
        return JSONResponse({"ok": False, "message": "Contato não encontrado."}, status_code=404)

    link = db.scalar(
        select(UserChatContact).where(
            UserChatContact.owner_user_id == user.id,
            UserChatContact.contact_user_id == partner.id,
        )
    )
    if link:
        db.delete(link)
        db.commit()
    return {"ok": True}


@router.get("/chat/private/{contact_id}")
def private_messages_api(contact_id: str, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return JSONResponse({"ok": False, "messages": []}, status_code=401)

    _ensure_user_contact_id(db, user)
    if seconds_until_allowed(db, "contact_lookup", str(user.id)):
        return JSONResponse({"ok": False, "message": "Muitas tentativas. Aguarde alguns minutos."}, status_code=429)
    partner = _resolve_private_contact(db, user, contact_id)
    if partner is None:
        register_attempt(db, "contact_lookup", str(user.id))
        return JSONResponse({"ok": False, "message": "Contato não encontrado."}, status_code=404)

    messages = _private_messages(db, user, partner)
    attachments = _attachments_for(db, "private", [item.id for item in messages])
    return {
        "ok": True,
        "contact": _chat_member_payload(partner, user.id),
        "messages": [_private_message_payload(item, user, attachments.get(item.id)) for item in messages],
    }


@router.post("/chat/private/{contact_id}")
async def private_send_api(contact_id: str, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return JSONResponse({"ok": False}, status_code=401)

    _ensure_user_contact_id(db, user)
    if seconds_until_allowed(db, "contact_lookup", str(user.id)):
        return JSONResponse({"ok": False, "message": "Muitas tentativas. Aguarde alguns minutos."}, status_code=429)
    partner = _resolve_private_contact(db, user, contact_id)
    if partner is None:
        register_attempt(db, "contact_lookup", str(user.id))
        return JSONResponse({"ok": False, "message": "Contato não encontrado."}, status_code=404)

    try:
        payload = await request.json()
    except Exception:
        payload = {}

    if not validate_csrf_token(request.session, str(payload.get("csrf_token") or "")):
        return JSONResponse({"ok": False, "message": "Sessão expirada."}, status_code=403)

    message_text = str(payload.get("message") or "").strip()[:2000]
    if not message_text:
        return JSONResponse({"ok": False, "message": "Digite uma mensagem."}, status_code=400)

    # Se o destinatário ainda não estiver salvo na agenda do remetente,
    # a primeira mensagem o adiciona automaticamente.
    exists = db.scalar(
        select(UserChatContact.id).where(
            UserChatContact.owner_user_id == user.id,
            UserChatContact.contact_user_id == partner.id,
        )
    )
    if not exists:
        db.add(UserChatContact(owner_user_id=user.id, contact_user_id=partner.id))

    message = PrivateChatMessage(
        company_id=user.company_id if user.company_id else None,
        sender_id=user.id,
        recipient_id=partner.id,
        message=message_text,
        is_read=False,
    )
    db.add(message)
    db.flush()

    create_notification(
        db,
        partner.id,
        f"Mensagem privada de {user.name}",
        message_text[:300],
        kind="chat",
        link=f"/company/chat?contact={user.contact_id}",
        commit=False,
    )
    db.commit()
    db.refresh(message)

    return {"ok": True, "message": _private_message_payload(message, user)}


@router.get("/messages")
def messages_api(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None or not user.company_id:
        return JSONResponse({"messages": []}, status_code=401)
    messages = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.company_id == user.company_id)
        .options(selectinload(ChatMessage.user))
        .order_by(desc(ChatMessage.created_at))
        .limit(100)
    ).all()
    attachments = _attachments_for(db, "group", [item.id for item in messages])
    return {"messages": [_group_message_payload(item, attachments.get(item.id)) for item in reversed(messages)]}


# ---------------------------------------------------------------------------
# Envio por HTTP (o Vercel não mantém WebSocket) + anexos
# ---------------------------------------------------------------------------
def _notify_group(db: Session, user: WebUser, text: str) -> None:
    recipients = db.scalars(select(WebUser).where(WebUser.company_id == user.company_id, WebUser.id != user.id)).all()
    for recipient in recipients:
        create_notification(db, recipient.id, f"Nova mensagem de {user.name}", text[:300], kind="chat", link="/company/chat?view=team", commit=False)


@router.post("/messages")
async def group_send_api(request: Request, db: Session = Depends(get_db)):
    """Envia mensagem para o chat da equipe."""
    user = current_user(request, db)
    if user is None or not user.company_id:
        return JSONResponse({"ok": False, "message": "Entre em uma empresa para usar o chat da equipe."}, status_code=403)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not validate_csrf_token(request.session, str(payload.get("csrf_token") or "")):
        return JSONResponse({"ok": False, "message": "Sessão expirada. Recarregue a página."}, status_code=403)
    text = str(payload.get("message") or "").strip()[:2000]
    if not text:
        return JSONResponse({"ok": False, "message": "Digite uma mensagem."}, status_code=400)
    message = ChatMessage(company_id=user.company_id, user_id=user.id, message=text)
    db.add(message)
    db.flush()
    _notify_group(db, user, text)
    db.commit()
    db.refresh(message)
    return {"ok": True, "message": _group_message_payload(message)}


async def _read_upload_form(request: Request):
    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        return None, None, "Sessão expirada. Recarregue a página."
    upload = form.get("file")
    if not getattr(upload, "filename", None):
        return None, None, "Escolha um arquivo."
    caption = str(form.get("message") or "").strip()[:2000]
    return upload, caption, ""


@router.post("/chat/private/{contact_id}/arquivo")
async def private_upload_api(contact_id: str, request: Request, db: Session = Depends(get_db)):
    """Envia PDF, Word, JPG ou PNG numa conversa privada."""
    user = current_user(request, db)
    if user is None:
        return JSONResponse({"ok": False}, status_code=401)
    _ensure_user_contact_id(db, user)
    partner = _resolve_private_contact(db, user, contact_id)
    if partner is None:
        return JSONResponse({"ok": False, "message": "Contato não encontrado."}, status_code=404)
    upload, caption, error = await _read_upload_form(request)
    if error:
        return JSONResponse({"ok": False, "message": error}, status_code=403 if "Sessão" in error else 400)
    try:
        stored = await save_chat_document(upload, prefix=f"p{user.id}")
    except ValueError as exc:
        return JSONResponse({"ok": False, "message": str(exc)}, status_code=400)
    except Exception:
        return JSONResponse({"ok": False, "message": "Não foi possível salvar o arquivo agora. Tente novamente."}, status_code=500)

    _ensure_chat_schema(db)
    exists = db.scalar(select(UserChatContact.id).where(UserChatContact.owner_user_id == user.id, UserChatContact.contact_user_id == partner.id))
    if not exists:
        db.add(UserChatContact(owner_user_id=user.id, contact_user_id=partner.id))
    message = PrivateChatMessage(
        company_id=user.company_id or None, sender_id=user.id, recipient_id=partner.id,
        message=caption or f"📎 {stored['name']}", is_read=False,
    )
    db.add(message)
    db.flush()
    attachment = ChatAttachment(
        kind="private", message_id=message.id, company_id=user.company_id, uploader_id=user.id, recipient_id=partner.id,
        file_name=str(stored["name"]), file_type=str(stored["type"]), file_size=int(stored["size"]),
        storage_json=json.dumps(stored),
    )
    db.add(attachment)
    create_notification(db, partner.id, f"Arquivo de {user.name}", f"📎 {stored['name']}", kind="chat",
                        link=f"/company/chat?contact={user.contact_id}", commit=False)
    db.commit()
    db.refresh(message)
    return {"ok": True, "message": _private_message_payload(message, user, _attachment_payload(attachment))}


@router.post("/messages/arquivo")
async def group_upload_api(request: Request, db: Session = Depends(get_db)):
    """Envia PDF, Word, JPG ou PNG no chat da equipe."""
    user = current_user(request, db)
    if user is None or not user.company_id:
        return JSONResponse({"ok": False, "message": "Entre em uma empresa para usar o chat da equipe."}, status_code=403)
    upload, caption, error = await _read_upload_form(request)
    if error:
        return JSONResponse({"ok": False, "message": error}, status_code=403 if "Sessão" in error else 400)
    try:
        stored = await save_chat_document(upload, prefix=f"g{user.company_id}")
    except ValueError as exc:
        return JSONResponse({"ok": False, "message": str(exc)}, status_code=400)
    except Exception:
        return JSONResponse({"ok": False, "message": "Não foi possível salvar o arquivo agora. Tente novamente."}, status_code=500)
    _ensure_chat_schema(db)
    message = ChatMessage(company_id=user.company_id, user_id=user.id, message=caption or f"📎 {stored['name']}")
    db.add(message)
    db.flush()
    attachment = ChatAttachment(
        kind="group", message_id=message.id, company_id=user.company_id, uploader_id=user.id,
        file_name=str(stored["name"]), file_type=str(stored["type"]), file_size=int(stored["size"]),
        storage_json=json.dumps(stored),
    )
    db.add(attachment)
    _notify_group(db, user, f"📎 {stored['name']}")
    db.commit()
    db.refresh(message)
    return {"ok": True, "message": _group_message_payload(message, _attachment_payload(attachment))}


@router.get("/chat/arquivos/{attachment_id}")
def chat_file(attachment_id: int, request: Request, download: int = 0, db: Session = Depends(get_db)):
    """Entrega o anexo só para quem participa da conversa."""
    user = current_user(request, db)
    if user is None:
        return Response("Faça login.", status_code=401)
    _ensure_chat_schema(db)
    att = db.get(ChatAttachment, attachment_id)
    allowed = att is not None and (
        (att.kind == "group" and user.company_id and att.company_id == user.company_id)
        or (att.kind == "private" and user.id in {att.uploader_id, att.recipient_id})
    )
    if not allowed:
        return Response("Arquivo não encontrado.", status_code=404)
    try:
        body, _ = read_stored_attachment(json.loads(att.storage_json or "{}"))
    except Exception:
        return Response("Arquivo indisponível.", status_code=404)
    inline = att.file_type in {"application/pdf", "image/png", "image/jpeg"} and not download
    name = "".join(ch for ch in att.file_name if ch not in '"\\\r\n;')[:180] or "arquivo"
    ascii_name = name.encode("ascii", "ignore").decode("ascii") or "arquivo"
    headers = {
        "Content-Disposition": f'{"inline" if inline else "attachment"}; filename="{ascii_name}"; filename*=UTF-8\'\'{url_quote(name)}',
        "Cache-Control": "private, max-age=600",
        "X-Content-Type-Options": "nosniff",
    }
    if att.file_type != "application/pdf":
        headers["Content-Security-Policy"] = "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; sandbox"
    return Response(content=body, media_type=att.file_type, headers=headers)


@router.websocket("/ws/chat")
async def chat_websocket(websocket: WebSocket):
    session = websocket.scope.get("session") or {}
    user_id = session.get("user_id")
    if not user_id:
        await websocket.close(code=4401)
        return

    db = SessionLocal()
    try:
        user = db.get(WebUser, int(user_id))
        if user is None or not user.company_id:
            await websocket.close(code=4403)
            return
        company_id = user.company_id
        await manager.connect(company_id, websocket)
        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    payload = json.loads(raw)
                    message_text = str(payload.get("message") or "").strip()
                except json.JSONDecodeError:
                    message_text = raw.strip()
                message_text = message_text[:2000]
                if not message_text:
                    continue

                message = ChatMessage(company_id=company_id, user_id=user.id, message=message_text)
                db.add(message)
                db.flush()
                recipients = db.scalars(select(WebUser).where(WebUser.company_id == company_id, WebUser.id != user.id)).all()
                for recipient in recipients:
                    create_notification(
                        db,
                        recipient.id,
                        f"Nova mensagem de {user.name}",
                        message_text[:300],
                        kind="chat",
                        link="/company/chat",
                        commit=False,
                    )
                db.commit()
                db.refresh(message)
                await manager.broadcast(
                    company_id,
                    {
                        "id": message.id,
                        "user_id": user.id,
                        "user_name": user.name,
                        "message": message.message,
                        "created_at": iso_utc(message.created_at),
                    },
                )
        except WebSocketDisconnect:
            manager.disconnect(company_id, websocket)
    finally:
        db.close()
