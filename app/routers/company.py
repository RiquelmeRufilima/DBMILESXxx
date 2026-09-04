from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Form, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..config import CHAT_UPLOAD_DIR, COMPANY_UPLOAD_DIR, MAX_TEAM_USERS
from ..database import SessionLocal, get_db
from ..dependencies import current_user
from ..models import ChatMessage, CompanyInvite, WebCompany, WebQuote, WebUser
from ..security import hash_password, validate_csrf_token, validate_password, verify_password
from ..services.company_access import ensure_company_access_schema
from ..services.notifications import create_notification
from ..services.realtime import avatar_url, manager
from ..services.team_accounts import can_create_team_user, remaining_team_slots, team_user_count
from ..services.uploads import delete_relative_upload, save_chat_attachment, save_upload_image
from ..services.user_defaults import ensure_user_defaults
from ..web import context, flash, templates

router = APIRouter(prefix="/company", tags=["company"])

ROLE_OPTIONS = (
    {
        "value": "membro",
        "label": "Consultor",
        "description": "Cotações, histórico, clientes, voos e chat da equipe.",
    },
    {
        "value": "gerente",
        "label": "Gerente",
        "description": "Tudo do consultor, além do financeiro e gestão operacional.",
    },
    {
        "value": "admin",
        "label": "Administrador",
        "description": "Acesso completo, inclusive empresa, usuários, níveis e senhas.",
    },
)
ROLE_VALUES = {item["value"] for item in ROLE_OPTIONS}


def _normalize_role(value: str | None) -> str:
    role = str(value or "membro").strip().lower()
    return role if role in ROLE_VALUES else "membro"


def _is_company_admin(user: WebUser | None) -> bool:
    return bool(user and user.company_id and user.role == "admin")


def _member_for_company(db: Session, user: WebUser, member_id: int) -> WebUser | None:
    return db.scalar(
        select(WebUser)
        .where(WebUser.id == member_id, WebUser.company_id == user.company_id)
        .options(selectinload(WebUser.profile))
    )


def _legacy_activity_event(message: ChatMessage) -> str:
    """Reconhece avisos automáticos salvos por versões antigas."""
    attachment_type = str(getattr(message, "attachment_type", None) or "")
    if attachment_type.startswith("system/"):
        return attachment_type.split("/", 1)[1]
    text = " ".join(str(getattr(message, "message", "") or "").split()).lower()
    if text.startswith("cálculo de ") or text.startswith("calculo de "):
        return "hidden"
    if "cliente da cotação" in text or "cliente da cotacao" in text:
        return "hidden"
    if " movida de " in text or " atualizada por " in text:
        return "hidden"
    if text.startswith("responsável da cotação") or text.startswith("responsavel da cotacao"):
        return "quote_assigned"
    if text.startswith("cotação ") or text.startswith("cotacao "):
        if " criada por " in text:
            return "quote_created"
        if "transferida para cotações aceitas" in text or "transferida para cotacoes aceitas" in text:
            return "quote_transferred_accepted"
        if "transferida para voos" in text:
            return "quote_transferred_flight"
        if "transferida para " in text:
            return "quote_assigned"
    return ""


def _visible_chat_messages(messages: list[ChatMessage], limit: int = 100) -> list[ChatMessage]:
    visible: list[ChatMessage] = []
    for message in messages:
        event = _legacy_activity_event(message)
        if event == "hidden":
            continue
        if event and not str(getattr(message, "attachment_type", None) or "").startswith("system/"):
            # Marca apenas em memória para a interface antiga ganhar o mesmo
            # visual centralizado dos avisos atuais.
            message.attachment_type = f"system/{event}"
        visible.append(message)
    return visible[-limit:]


def _chat_payload(message: ChatMessage, user: WebUser) -> dict[str, Any]:
    attachment_type = getattr(message, "attachment_type", None) or ""
    legacy_event = _legacy_activity_event(message)
    if not attachment_type and legacy_event and legacy_event != "hidden":
        attachment_type = f"system/{legacy_event}"
    is_system = attachment_type.startswith("system/")
    return {
        "type": "chat_message",
        "id": message.id,
        "user_id": user.id,
        "user_name": user.name,
        "avatar_url": avatar_url(user),
        "message": message.message,
        "attachment_url": f"/{message.attachment_path}" if getattr(message, "attachment_path", None) else "",
        "attachment_name": getattr(message, "attachment_name", None) or "",
        "attachment_type": attachment_type,
        "attachment_size": int(getattr(message, "attachment_size", 0) or 0),
        "created_at": message.created_at.isoformat(),
        "is_system_activity": is_system,
        "activity_event": attachment_type.split("/", 1)[1] if is_system and "/" in attachment_type else "",
    }


def _save_chat_message(
    db: Session,
    user: WebUser,
    message_text: str,
    attachment: dict[str, object] | None = None,
) -> tuple[ChatMessage, dict[str, Any]]:
    text = str(message_text or "").strip()[:2000]
    if not text and not attachment:
        raise ValueError("Escreva uma mensagem ou selecione uma foto/PDF.")
    if not user.company_id:
        raise ValueError("O usuário não pertence a uma empresa.")

    message = ChatMessage(
        company_id=user.company_id,
        user_id=user.id,
        message=text,
        attachment_path=str((attachment or {}).get("path") or "") or None,
        attachment_name=str((attachment or {}).get("name") or "") or None,
        attachment_type=str((attachment or {}).get("type") or "") or None,
        attachment_size=int((attachment or {}).get("size") or 0) or None,
    )
    db.add(message)
    db.flush()

    recipients = db.scalars(
        select(WebUser).where(
            WebUser.company_id == user.company_id,
            WebUser.id != user.id,
            WebUser.active.is_(True),
        )
    ).all()
    for recipient in recipients:
        create_notification(
            db,
            recipient.id,
            f"Nova mensagem de {user.name}",
            (text or f"Arquivo enviado: {message.attachment_name or 'anexo'}")[:300],
            kind="chat",
            link="/company/chat",
            commit=False,
        )

    db.commit()
    db.refresh(message)
    return message, _chat_payload(message, user)


@router.get("")
def company_dashboard(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)

    ensure_company_access_schema(db)

    if not user.company_id:
        return templates.TemplateResponse(request, "company/create.html", context(request, user=user))

    company = db.get(WebCompany, user.company_id)
    if company is None:
        # Repara referência antiga/quebrada sem derrubar a tela Empresa.
        user.company_id = None
        user.is_owner = False
        if user.role == "admin":
            user.role = "membro"
        db.commit()
        flash(request, "A empresa vinculada a este acesso não existe mais. Crie uma nova empresa.", "warning")
        return RedirectResponse("/company", status_code=303)

    members = db.scalars(
        select(WebUser)
        .where(WebUser.company_id == user.company_id)
        .options(selectinload(WebUser.profile))
        .order_by(WebUser.is_owner.desc(), WebUser.active.desc(), WebUser.name)
    ).all()
    total_quotes = db.scalar(select(func.count(WebQuote.id)).where(WebQuote.company_id == user.company_id)) or 0
    total_value = db.scalar(
        select(func.coalesce(func.sum(WebQuote.total), 0)).where(WebQuote.company_id == user.company_id)
    ) or 0
    last_messages = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.company_id == user.company_id)
        .options(selectinload(ChatMessage.user).selectinload(WebUser.profile))
        .order_by(desc(ChatMessage.created_at))
        .limit(6)
    ).all()
    last_messages = list(reversed(last_messages))
    additional_count = team_user_count(db, user.company_id)
    active_count = sum(1 for item in members if item.active)
    pending_invites = []
    if _is_company_admin(user):
        pending_invites = list(
            db.scalars(
                select(CompanyInvite)
                .where(
                    CompanyInvite.company_id == user.company_id,
                    CompanyInvite.status == "pending",
                )
                .order_by(CompanyInvite.created_at.desc())
            ).all()
        )

    return templates.TemplateResponse(
        request,
        "company/dashboard.html",
        context(
            request,
            user=user,
            company=company,
            members=members,
            total_quotes=total_quotes,
            total_value=total_value,
            last_messages=last_messages,
            team_count=additional_count,
            active_count=active_count,
            max_team_users=MAX_TEAM_USERS,
            remaining_slots=remaining_team_slots(db, user.company_id),
            role_options=ROLE_OPTIONS,
            can_manage_members=_is_company_admin(user),
            pending_invites=pending_invites,
        ),
    )


@router.post("/create")
def create_company(
    request: Request,
    name: str = Form(...),
    cnpj: str = Form(""),
    join_code: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    ensure_company_access_schema(db)
    if user.company_id:
        return RedirectResponse("/company", status_code=303)
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/company", status_code=303)

    name = " ".join(str(name or "").split())[:180]
    cnpj = str(cnpj or "").strip()[:30]
    join_code = str(join_code or "").strip()

    if len(name) < 2:
        flash(request, "Informe o nome da empresa.", "error")
        return RedirectResponse("/company", status_code=303)
    if len(join_code) < 6 or len(join_code) > 64:
        flash(request, "O código de entrada precisa ter entre 6 e 64 caracteres.", "error")
        return RedirectResponse("/company", status_code=303)

    company = WebCompany(
        name=name,
        cnpj=cnpj or None,
        join_code_hash=hash_password(join_code),
    )
    db.add(company)
    db.flush()

    user.company_id = company.id
    user.role = "admin"
    user.is_owner = True
    user.active = True
    user.auth_version = int(user.auth_version or 1) + 1
    db.commit()

    request.session["auth_version"] = int(user.auth_version or 1)
    flash(
        request,
        f"Empresa '{name}' criada. Compartilhe o código de entrada apenas com quem deve fazer parte da equipe.",
        "success",
    )
    return RedirectResponse("/company", status_code=303)


@router.post("/join")
def join_company(
    request: Request,
    company_name: str = Form(...),
    join_code: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    ensure_company_access_schema(db)
    if user.company_id:
        flash(request, "Sua conta já pertence a uma empresa.", "info")
        return RedirectResponse("/company", status_code=303)
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/company", status_code=303)

    company_name = " ".join(str(company_name or "").split())[:180]
    join_code = str(join_code or "").strip()

    if len(company_name) < 2 or not join_code:
        flash(request, "Informe o nome da empresa e o código de entrada.", "error")
        return RedirectResponse("/company", status_code=303)

    companies = db.scalars(
        select(WebCompany).where(func.lower(WebCompany.name) == company_name.lower())
    ).all()

    matched_company = None
    for company in companies:
        if company.join_code_hash and verify_password(join_code, company.join_code_hash):
            matched_company = company
            break

    if matched_company is None:
        flash(request, "Nome da empresa ou código de entrada incorreto.", "error")
        return RedirectResponse("/company", status_code=303)

    if not can_create_team_user(db, matched_company.id):
        flash(request, f"Esta empresa atingiu o limite de {MAX_TEAM_USERS} usuários adicionais.", "error")
        return RedirectResponse("/company", status_code=303)

    user.company_id = matched_company.id
    user.role = "membro"
    user.is_owner = False
    user.active = True
    user.auth_version = int(user.auth_version or 1) + 1

    # Avisa administradores da empresa sobre o novo acesso.
    admins = db.scalars(
        select(WebUser).where(
            WebUser.company_id == matched_company.id,
            WebUser.role == "admin",
            WebUser.active.is_(True),
            WebUser.id != user.id,
        )
    ).all()
    for admin in admins:
        create_notification(
            db,
            admin.id,
            "Novo membro entrou na empresa",
            f"{user.name} entrou em {matched_company.name} usando o código da empresa.",
            kind="company",
            link="/company#equipe",
            commit=False,
        )

    db.commit()
    request.session["auth_version"] = int(user.auth_version or 1)

    flash(
        request,
        f"Você entrou em '{matched_company.name}' como Consultor.",
        "success",
    )
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
    user.is_owner = True
    user.active = True
    user.auth_version = int(user.auth_version or 1) + 1
    db.commit()
    request.session["auth_version"] = int(user.auth_version or 1)
    flash(request, f"Empresa '{name}' criada. Agora você pode adicionar até {MAX_TEAM_USERS} usuários.", "success")
    return RedirectResponse("/company", status_code=303)


@router.post("/access-code")
def change_company_access_code(
    request: Request,
    join_code: str = Form(...),
    join_code_confirm: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    ensure_company_access_schema(db)
    if not _is_company_admin(user):
        flash(request, "Somente o administrador pode alterar o código de entrada.", "error")
        return RedirectResponse("/company", status_code=303)
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/company", status_code=303)

    join_code = str(join_code or "").strip()
    join_code_confirm = str(join_code_confirm or "").strip()

    if len(join_code) < 6 or len(join_code) > 64:
        flash(request, "O código de entrada precisa ter entre 6 e 64 caracteres.", "error")
        return RedirectResponse("/company", status_code=303)
    if join_code != join_code_confirm:
        flash(request, "Os códigos informados não coincidem.", "error")
        return RedirectResponse("/company", status_code=303)

    company = db.get(WebCompany, user.company_id)
    if company is None:
        flash(request, "Empresa não encontrada.", "error")
        return RedirectResponse("/company", status_code=303)

    company.join_code_hash = hash_password(join_code)
    db.commit()
    flash(
        request,
        "Código de entrada atualizado. Compartilhe o novo código somente com sua equipe.",
        "success",
    )
    return RedirectResponse("/company", status_code=303)


@router.post("/invite")
def invite_user_by_email(
    request: Request,
    email: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    ensure_company_access_schema(db)

    if not _is_company_admin(user):
        flash(request, "Somente administradores podem enviar convites.", "error")
        return RedirectResponse("/company", status_code=303)
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/company#convites", status_code=303)
    if not can_create_team_user(db, user.company_id):
        flash(request, f"O limite de {MAX_TEAM_USERS} usuários adicionais foi atingido.", "error")
        return RedirectResponse("/company#convites", status_code=303)

    email = str(email or "").strip().lower()[:180]
    if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
        flash(request, "Informe um e-mail válido.", "error")
        return RedirectResponse("/company#convites", status_code=303)

    invited = db.scalar(select(WebUser).where(func.lower(WebUser.email) == email.lower()))
    if invited is None:
        flash(
            request,
            "Esse e-mail ainda não possui uma conta no DBMILESX. "
            "Peça para o usuário criar a conta primeiro; depois envie o convite.",
            "warning",
        )
        return RedirectResponse("/company#convites", status_code=303)

    if invited.id == user.id:
        flash(request, "Você já pertence a esta empresa.", "info")
        return RedirectResponse("/company#convites", status_code=303)
    if invited.company_id == user.company_id:
        flash(request, "Esse usuário já pertence a esta empresa.", "info")
        return RedirectResponse("/company#convites", status_code=303)
    if invited.company_id and invited.company_id != user.company_id:
        flash(request, "Esse usuário já pertence a outra empresa.", "error")
        return RedirectResponse("/company#convites", status_code=303)

    existing = db.scalar(
        select(CompanyInvite).where(
            CompanyInvite.company_id == user.company_id,
            CompanyInvite.invited_user_id == invited.id,
            CompanyInvite.status == "pending",
        )
    )
    if existing:
        flash(request, "Já existe um convite pendente para esse usuário.", "info")
        return RedirectResponse("/company#convites", status_code=303)

    company_obj = db.get(WebCompany, user.company_id)
    invite = CompanyInvite(
        company_id=user.company_id,
        invited_user_id=invited.id,
        invited_email=invited.email,
        invited_by_user_id=user.id,
        status="pending",
    )
    db.add(invite)
    db.flush()

    create_notification(
        db,
        invited.id,
        f"Convite para entrar em {company_obj.name}",
        f"{user.name} convidou você para fazer parte de {company_obj.name}.",
        kind="info",
        link=f"/company/invitations/{invite.id}",
        commit=False,
    )
    db.commit()

    flash(request, f"Convite enviado para {invited.email}. Ele aparecerá no sininho do usuário.", "success")
    return RedirectResponse("/company#convites", status_code=303)


@router.get("/invitations/{invite_id}")
def invitation_page(
    invite_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    ensure_company_access_schema(db)

    invite = db.get(CompanyInvite, invite_id)
    if invite is None or invite.invited_user_id != user.id:
        flash(request, "Convite não encontrado.", "error")
        return RedirectResponse("/notifications", status_code=303)

    company_obj = db.get(WebCompany, invite.company_id)
    inviter = db.get(WebUser, invite.invited_by_user_id)
    return templates.TemplateResponse(
        request,
        "company/invitation.html",
        context(
            request,
            user=user,
            invite=invite,
            company=company_obj,
            inviter=inviter,
        ),
    )


@router.post("/invitations/{invite_id}/accept")
def accept_invitation(
    invite_id: int,
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    ensure_company_access_schema(db)

    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse(f"/company/invitations/{invite_id}", status_code=303)

    invite = db.get(CompanyInvite, invite_id)
    if invite is None or invite.invited_user_id != user.id or invite.status != "pending":
        flash(request, "Este convite não está mais disponível.", "error")
        return RedirectResponse("/notifications", status_code=303)

    if user.company_id:
        flash(request, "Sua conta já pertence a uma empresa.", "error")
        return RedirectResponse(f"/company/invitations/{invite_id}", status_code=303)

    if not can_create_team_user(db, invite.company_id):
        flash(request, f"A empresa atingiu o limite de {MAX_TEAM_USERS} usuários adicionais.", "error")
        return RedirectResponse(f"/company/invitations/{invite_id}", status_code=303)

    company_obj = db.get(WebCompany, invite.company_id)
    user.company_id = invite.company_id
    user.role = "membro"
    user.is_owner = False
    user.active = True
    user.auth_version = int(user.auth_version or 1) + 1

    invite.status = "accepted"
    invite.responded_at = datetime.utcnow()

    inviter = db.get(WebUser, invite.invited_by_user_id)
    if inviter:
        create_notification(
            db,
            inviter.id,
            "Convite aceito",
            f"{user.name} aceitou o convite para entrar em {company_obj.name}.",
            kind="success",
            link="/company#equipe",
            commit=False,
        )

    db.commit()
    request.session["auth_version"] = int(user.auth_version or 1)
    flash(request, f"Você entrou em '{company_obj.name}' como Consultor.", "success")
    return RedirectResponse("/company", status_code=303)


@router.post("/invitations/{invite_id}/decline")
def decline_invitation(
    invite_id: int,
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    ensure_company_access_schema(db)

    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse(f"/company/invitations/{invite_id}", status_code=303)

    invite = db.get(CompanyInvite, invite_id)
    if invite is None or invite.invited_user_id != user.id or invite.status != "pending":
        flash(request, "Este convite não está mais disponível.", "error")
        return RedirectResponse("/notifications", status_code=303)

    invite.status = "declined"
    invite.responded_at = datetime.utcnow()

    inviter = db.get(WebUser, invite.invited_by_user_id)
    company_obj = db.get(WebCompany, invite.company_id)
    if inviter and company_obj:
        create_notification(
            db,
            inviter.id,
            "Convite recusado",
            f"{user.name} recusou o convite para entrar em {company_obj.name}.",
            kind="info",
            link="/company#convites",
            commit=False,
        )

    db.commit()
    flash(request, "Convite recusado.", "info")
    return RedirectResponse("/notifications", status_code=303)


@router.post("/invitations/{invite_id}/cancel")
def cancel_invitation(
    invite_id: int,
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    ensure_company_access_schema(db)

    if not _is_company_admin(user):
        flash(request, "Somente administradores podem cancelar convites.", "error")
        return RedirectResponse("/company", status_code=303)
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/company#convites", status_code=303)

    invite = db.get(CompanyInvite, invite_id)
    if (
        invite is None
        or invite.company_id != user.company_id
        or invite.status != "pending"
    ):
        flash(request, "Convite pendente não encontrado.", "error")
        return RedirectResponse("/company#convites", status_code=303)

    invite.status = "cancelled"
    invite.responded_at = datetime.utcnow()
    db.commit()
    flash(request, "Convite cancelado.", "success")
    return RedirectResponse("/company#convites", status_code=303)


@router.post("/branding")
async def update_company_branding(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if not _is_company_admin(user):
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
    flash(request, "Dados e logo da empresa salvos.", "success")
    return RedirectResponse("/company", status_code=303)


@router.post("/branding/remove-logo")
async def remove_company_logo(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if not _is_company_admin(user):
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
    if not _is_company_admin(user):
        flash(request, "Somente o administrador pode adicionar membros.", "error")
        return RedirectResponse("/company", status_code=303)
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/company#equipe", status_code=303)
    if not can_create_team_user(db, user.company_id):
        flash(request, f"O limite de {MAX_TEAM_USERS} usuários adicionais foi atingido.", "error")
        return RedirectResponse("/company#equipe", status_code=303)

    name = name.strip()[:180]
    email = email.strip().lower()[:180]
    role = _normalize_role(role)
    if len(name) < 2:
        flash(request, "Informe o nome do usuário.", "error")
        return RedirectResponse("/company#equipe", status_code=303)
    if "@" not in email or "." not in email:
        flash(request, "Informe um e-mail válido.", "error")
        return RedirectResponse("/company#equipe", status_code=303)
    valid, message = validate_password(password)
    if not valid:
        flash(request, message, "error")
        return RedirectResponse("/company#equipe", status_code=303)

    existing = db.scalar(select(WebUser).where(WebUser.email == email))
    if existing and existing.company_id == user.company_id:
        flash(request, "Esse e-mail já pertence a um membro desta empresa.", "error")
        return RedirectResponse("/company#equipe", status_code=303)
    if existing and existing.company_id and existing.company_id != user.company_id:
        flash(request, "Esse e-mail já pertence a outra empresa.", "error")
        return RedirectResponse("/company#equipe", status_code=303)

    try:
        if existing:
            member = existing
            member.company_id = user.company_id
            member.name = name
            member.password_hash = hash_password(password)
            member.role = role
            member.active = True
            member.is_owner = False
            member.auth_version = int(member.auth_version or 1) + 1
        else:
            member = WebUser(
                company_id=user.company_id,
                email=email,
                password_hash=hash_password(password),
                name=name,
                role=role,
                active=True,
                is_owner=False,
                auth_version=1,
            )
            db.add(member)
        db.commit()
        db.refresh(member)
        ensure_user_defaults(db, member)
    except IntegrityError:
        db.rollback()
        flash(request, "Não foi possível criar o acesso porque o e-mail já está em uso.", "error")
        return RedirectResponse("/company#equipe", status_code=303)

    flash(
        request,
        f"Acesso de {member.name} criado como {next(item['label'] for item in ROLE_OPTIONS if item['value'] == role)}. Restam {remaining_team_slots(db, user.company_id)} vaga(s).",
        "success",
    )
    return RedirectResponse("/company#equipe", status_code=303)


@router.post("/members/{member_id}/update")
async def update_member(
    member_id: int,
    request: Request,
    role: str = Form("membro"),
    active: str | None = Form(None),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if not _is_company_admin(user):
        flash(request, "Somente o administrador pode alterar membros.", "error")
        return RedirectResponse("/company#equipe", status_code=303)
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/company#equipe", status_code=303)

    member = _member_for_company(db, user, member_id)
    if member is None:
        flash(request, "Membro não encontrado.", "error")
        return RedirectResponse("/company#equipe", status_code=303)
    if member.is_owner:
        flash(request, "O acesso principal não pode ser alterado por esta tela.", "error")
        return RedirectResponse("/company#equipe", status_code=303)
    if member.id == user.id:
        flash(request, "Você não pode alterar o próprio nível por esta tela.", "error")
        return RedirectResponse("/company#equipe", status_code=303)

    member.role = _normalize_role(role)
    member.active = active == "1"
    member.auth_version = int(member.auth_version or 1) + 1
    db.commit()
    await manager.disconnect_user(member.id)
    flash(request, f"Permissões de {member.name} atualizadas.", "success")
    return RedirectResponse("/company#equipe", status_code=303)


@router.post("/members/{member_id}/reset-password")
async def reset_member_password(
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
    if not _is_company_admin(user):
        flash(request, "Somente o administrador pode redefinir senhas.", "error")
        return RedirectResponse("/company#equipe", status_code=303)
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/company#equipe", status_code=303)

    member = _member_for_company(db, user, member_id)
    if member is None or member.is_owner:
        flash(request, "Membro não encontrado ou protegido.", "error")
        return RedirectResponse("/company#equipe", status_code=303)
    if password != password_confirm:
        flash(request, "As novas senhas não coincidem.", "error")
        return RedirectResponse("/company#equipe", status_code=303)
    valid, message = validate_password(password)
    if not valid:
        flash(request, message, "error")
        return RedirectResponse("/company#equipe", status_code=303)

    member.password_hash = hash_password(password)
    member.auth_version = int(member.auth_version or 1) + 1
    member.active = True
    db.commit()
    await manager.disconnect_user(member.id)
    flash(request, f"Senha de {member.name} redefinida. As sessões antigas foram encerradas.", "success")
    return RedirectResponse("/company#equipe", status_code=303)


@router.post("/members/{member_id}/remove")
async def remove_member(
    member_id: int,
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if not _is_company_admin(user):
        flash(request, "Somente o administrador pode remover membros.", "error")
        return RedirectResponse("/company#equipe", status_code=303)
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/company#equipe", status_code=303)

    member = _member_for_company(db, user, member_id)
    if member is None:
        flash(request, "Membro não encontrado.", "error")
        return RedirectResponse("/company#equipe", status_code=303)
    if member.is_owner or member.id == user.id:
        flash(request, "O acesso principal não pode ser removido.", "error")
        return RedirectResponse("/company#equipe", status_code=303)

    member.company_id = None
    member.active = False
    member.is_owner = False
    member.role = "membro"
    member.auth_version = int(member.auth_version or 1) + 1
    db.commit()
    await manager.disconnect_user(member.id)
    flash(request, f"{member.name} foi removido da equipe. As cotações antigas continuam identificadas com o nome dele.", "success")
    return RedirectResponse("/company#equipe", status_code=303)


# Compatibilidade com o formulário antigo de vincular uma conta já existente.
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
    if not _is_company_admin(user):
        flash(request, "Você não tem permissão para gerenciar membros.", "error")
        return RedirectResponse("/company#equipe", status_code=303)
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/company#equipe", status_code=303)
    if not can_create_team_user(db, user.company_id):
        flash(request, f"O limite de {MAX_TEAM_USERS} usuários adicionais foi atingido.", "error")
        return RedirectResponse("/company#equipe", status_code=303)

    member = db.scalar(select(WebUser).where(WebUser.email == email.strip().lower()))
    if member is None:
        flash(request, "Esse e-mail ainda não possui conta. Use 'Adicionar membro' para criar o acesso.", "error")
        return RedirectResponse("/company#equipe", status_code=303)
    if member.company_id and member.company_id != user.company_id:
        flash(request, "Esse usuário já pertence a outra empresa.", "error")
        return RedirectResponse("/company#equipe", status_code=303)

    member.company_id = user.company_id
    member.is_owner = False
    member.role = _normalize_role(role)
    member.active = True
    member.auth_version = int(member.auth_version or 1) + 1
    db.commit()
    ensure_user_defaults(db, member)
    flash(request, f"{member.name} foi adicionado à equipe.", "success")
    return RedirectResponse("/company#equipe", status_code=303)


@router.get("/chat")
def chat_page(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if not user.company_id:
        flash(request, "Crie ou entre em uma empresa para usar o chat.", "error")
        return RedirectResponse("/company", status_code=303)
    company = db.get(WebCompany, user.company_id)
    if company is None:
        flash(request, "Empresa não encontrada.", "error")
        return RedirectResponse("/company", status_code=303)
    messages = list(reversed(db.scalars(
        select(ChatMessage)
        .where(ChatMessage.company_id == user.company_id)
        .options(selectinload(ChatMessage.user).selectinload(WebUser.profile))
        .order_by(desc(ChatMessage.created_at))
        .limit(300)
    ).all()))
    messages = _visible_chat_messages(messages, 100)
    return templates.TemplateResponse(
        request,
        "company/chat.html",
        context(request, user=user, company=company, messages=messages, avatar_url=avatar_url),
    )


@router.get("/messages")
def messages_api(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None or not user.company_id:
        return JSONResponse({"messages": []}, status_code=401)
    messages = list(reversed(db.scalars(
        select(ChatMessage)
        .where(ChatMessage.company_id == user.company_id)
        .options(selectinload(ChatMessage.user).selectinload(WebUser.profile))
        .order_by(desc(ChatMessage.created_at))
        .limit(300)
    ).all()))
    messages = _visible_chat_messages(messages, 100)
    return {"messages": [_chat_payload(item, item.user) for item in messages]}


@router.post("/messages/send")
async def send_message_http(request: Request, db: Session = Depends(get_db)):
    """Fallback seguro do chat quando o WebSocket estiver reconectando.

    Isso mantém o chat funcional em rede local e em hospedagens onde a conexão
    em tempo real oscilar por alguns segundos.
    """
    user = current_user(request, db)
    if user is None or not user.company_id:
        return JSONResponse({"ok": False, "message": "Login ou empresa necessários."}, status_code=401)

    try:
        data = await request.json()
    except Exception:
        form = await request.form()
        data = dict(form)

    received_csrf = request.headers.get("x-csrf-token") or str(data.get("csrf_token") or "")
    if not validate_csrf_token(request.session, received_csrf):
        return JSONResponse({"ok": False, "message": "Sessão expirada."}, status_code=403)

    try:
        _message, payload = _save_chat_message(db, user, str(data.get("message") or ""))
    except ValueError as exc:
        return JSONResponse({"ok": False, "message": str(exc)}, status_code=400)

    await manager.broadcast(user.company_id, payload)
    return {"ok": True, "message": payload}


@router.post("/messages/upload")
async def upload_chat_message(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None or not user.company_id:
        return JSONResponse({"ok": False, "message": "Login ou empresa necessários."}, status_code=401)
    form = await request.form()
    received_csrf = request.headers.get("x-csrf-token") or str(form.get("csrf_token") or "")
    if not validate_csrf_token(request.session, received_csrf):
        return JSONResponse({"ok": False, "message": "Sessão expirada."}, status_code=403)
    upload = form.get("attachment")
    try:
        attachment = await save_chat_attachment(
            upload if isinstance(upload, UploadFile) or getattr(upload, "filename", None) else None,
            CHAT_UPLOAD_DIR / str(user.company_id),
        )
        _message, payload = _save_chat_message(db, user, str(form.get("message") or ""), attachment)
    except ValueError as exc:
        return JSONResponse({"ok": False, "message": str(exc)}, status_code=400)
    await manager.broadcast(user.company_id, payload)
    return {"ok": True, "message": payload}


@router.websocket("/ws/chat")
@router.websocket("/ws/realtime")
async def realtime_websocket(websocket: WebSocket):
    session = websocket.scope.get("session") or {}
    user_id = session.get("user_id")
    if not user_id:
        await websocket.close(code=4401)
        return

    db = SessionLocal()
    company_id: int | None = None
    connected = False
    try:
        user = db.scalar(
            select(WebUser)
            .where(WebUser.id == int(user_id))
            .options(selectinload(WebUser.profile))
        )
        session_version = session.get("auth_version")
        if (
            user is None
            or not user.active
            or not user.company_id
            or (session_version is not None and int(session_version) != int(user.auth_version or 1))
        ):
            await websocket.close(code=4403)
            return
        company_id = user.company_id
        await manager.connect(company_id, user.id, websocket)
        connected = True
        await websocket.send_json({"type": "connection_ready", "user_id": user.id})

        while True:
            raw = await websocket.receive_text()
            db.refresh(user)
            if (
                not user.active
                or user.company_id != company_id
                or (session_version is not None and int(session_version) != int(user.auth_version or 1))
            ):
                await websocket.close(code=4403)
                break
            try:
                payload = json.loads(raw)
                event_type = str(payload.get("type") or "chat_message")
            except json.JSONDecodeError:
                payload = {"message": raw}
                event_type = "chat_message"

            if event_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue
            if event_type != "chat_message":
                continue

            try:
                _message, event = _save_chat_message(db, user, str(payload.get("message") or ""))
            except ValueError:
                continue
            await manager.broadcast(company_id, event)
    except WebSocketDisconnect:
        pass
    finally:
        if connected and company_id is not None:
            manager.disconnect(company_id, websocket)
        db.close()
