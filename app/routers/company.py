from __future__ import annotations

import json
import secrets
from collections import defaultdict

from fastapi import APIRouter, Depends, Form, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session, selectinload

from ..config import COMPANY_UPLOAD_DIR
from ..database import SessionLocal, get_db
from ..dependencies import current_user
from ..models import ChatMessage, PrivateChatMessage, UserChatContact, WebCompany, WebQuote, WebUser
from ..security import validate_csrf_token
from ..services.notifications import create_notification
from ..services.uploads import delete_relative_upload, save_upload_image
from ..web import context, flash, templates

router = APIRouter(prefix="/company", tags=["company"])


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


def _private_message_payload(item: PrivateChatMessage, user: WebUser) -> dict:
    sender = item.sender if getattr(item, "sender", None) else None
    return {
        "id": item.id,
        "sender_id": item.sender_id,
        "recipient_id": item.recipient_id,
        "user_id": item.sender_id,
        "user_name": sender.name if sender else ("Você" if item.sender_id == user.id else "Usuário"),
        "message": item.message,
        "is_read": bool(item.is_read),
        "created_at": item.created_at.isoformat(),
    }


@router.get("")
def company_dashboard(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)

    if not user.company_id:
        return templates.TemplateResponse(request, "company/create.html", context(request, user=user))

    company = db.get(WebCompany, user.company_id)
    _ensure_company_contact_ids(db, user.company_id)
    members = db.scalars(select(WebUser).where(WebUser.company_id == user.company_id).order_by(WebUser.name)).all()
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
        ),
    )


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
        return RedirectResponse("/company", status_code=303)

    name = name.strip()
    if len(name) < 2:
        flash(request, "Informe o nome da empresa.", "error")
        return RedirectResponse("/company", status_code=303)

    company = WebCompany(name=name, cnpj=cnpj.strip() or None)
    db.add(company)
    db.flush()
    user.company_id = company.id
    user.role = "admin"
    db.commit()
    flash(request, f"Empresa '{name}' criada.", "success")
    return RedirectResponse("/company", status_code=303)


@router.post("/branding")
async def update_company_branding(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if not user.company_id or user.role != "admin":
        flash(request, "Somente o administrador da empresa pode alterar a identidade visual.", "error")
        return RedirectResponse("/company", status_code=303)

    company = db.get(WebCompany, user.company_id)
    if company is None:
        flash(request, "Empresa não encontrada.", "error")
        return RedirectResponse("/company", status_code=303)

    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/company", status_code=303)

    company.name = str(form.get("name") or company.name).strip()[:180] or company.name
    company.cnpj = str(form.get("cnpj") or "").strip()[:30] or None
    company.phone = str(form.get("phone") or "").strip()[:40] or None
    company.email = str(form.get("email") or "").strip()[:180] or None

    upload = form.get("logo")
    try:
        logo_path = await save_upload_image(
            upload if getattr(upload, "filename", None) else None,
            COMPANY_UPLOAD_DIR,
            max_bytes=6 * 1024 * 1024,
            filename_prefix=f"company-{company.id}",
        )
    except ValueError as exc:
        flash(request, str(exc), "error")
        return RedirectResponse("/company", status_code=303)

    old_path = None
    if logo_path:
        old_path = company.logo_path
        company.logo_path = logo_path

    db.commit()
    if old_path:
        delete_relative_upload(old_path)
    flash(request, "Dados e logo da empresa salvos. A logo será usada nos PDFs por padrão.", "success")
    return RedirectResponse("/company", status_code=303)


@router.post("/branding/remove-logo")
async def remove_company_logo(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if not user.company_id or user.role != "admin":
        flash(request, "Somente o administrador da empresa pode remover a logo.", "error")
        return RedirectResponse("/company", status_code=303)

    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/company", status_code=303)

    company = db.get(WebCompany, user.company_id)
    old_path = company.logo_path if company else None
    if company:
        company.logo_path = None
        db.commit()
    delete_relative_upload(old_path)
    flash(request, "Logo da empresa removida.", "success")
    return RedirectResponse("/company", status_code=303)


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
    if not user.company_id or user.role not in {"admin", "gerente"}:
        flash(request, "Você não tem permissão para gerenciar membros.", "error")
        return RedirectResponse("/company", status_code=303)
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/company", status_code=303)

    member = db.scalar(select(WebUser).where(WebUser.email == email.strip().lower()))
    if member is None:
        flash(request, "Esse e-mail ainda não possui conta. Peça para a pessoa se cadastrar primeiro.", "error")
        return RedirectResponse("/company", status_code=303)
    if member.company_id and member.company_id != user.company_id:
        flash(request, "Esse usuário já pertence a outra empresa.", "error")
        return RedirectResponse("/company", status_code=303)

    member.company_id = user.company_id
    member.role = role if role in {"membro", "gerente", "admin"} else "membro"
    db.commit()
    flash(request, f"{member.name} foi adicionado à equipe.", "success")
    return RedirectResponse("/company", status_code=303)


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
            "last_at": group_last.created_at.isoformat() if group_last else None,
        },
        "conversations": [
            {
                **item["member"],
                "last_message": item["last_message"],
                "last_at": item["last_at"].isoformat(),
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

    contact_id = str(payload.get("contact_id") or "").strip().upper()
    partner = _resolve_private_contact(db, user, contact_id)
    if partner is None:
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

    partner = _resolve_private_contact(db, user, contact_id)
    if partner is None:
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
    partner = _resolve_private_contact(db, user, contact_id)
    if partner is None:
        return JSONResponse({"ok": False, "message": "Contato não encontrado."}, status_code=404)

    messages = _private_messages(db, user, partner)
    return {
        "ok": True,
        "contact": _chat_member_payload(partner, user.id),
        "messages": [_private_message_payload(item, user) for item in messages],
    }


@router.post("/chat/private/{contact_id}")
async def private_send_api(contact_id: str, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return JSONResponse({"ok": False}, status_code=401)

    _ensure_user_contact_id(db, user)
    partner = _resolve_private_contact(db, user, contact_id)
    if partner is None:
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
    return {
        "messages": [
            {
                "id": item.id,
                "user_id": item.user_id,
                "user_name": item.user.name,
                "message": item.message,
                "created_at": item.created_at.isoformat(),
            }
            for item in reversed(messages)
        ]
    }


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
                        "created_at": message.created_at.isoformat(),
                    },
                )
        except WebSocketDisconnect:
            manager.disconnect(company_id, websocket)
    finally:
        db.close()
