from __future__ import annotations

import json
from collections import defaultdict

from fastapi import APIRouter, Depends, Form, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, selectinload

from ..config import COMPANY_UPLOAD_DIR
from ..database import SessionLocal, get_db
from ..dependencies import current_user
from ..models import ChatMessage, WebCompany, WebQuote, WebUser
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


@router.get("")
def company_dashboard(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)

    if not user.company_id:
        return templates.TemplateResponse(request, "company/create.html", context(request, user=user))

    company = db.get(WebCompany, user.company_id)
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
def chat_page(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if not user.company_id:
        flash(request, "Crie ou entre em uma empresa para usar o chat.", "error")
        return RedirectResponse("/company", status_code=303)
    company = db.get(WebCompany, user.company_id)
    messages = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.company_id == user.company_id)
        .options(selectinload(ChatMessage.user))
        .order_by(desc(ChatMessage.created_at))
        .limit(100)
    ).all()
    messages = list(reversed(messages))
    return templates.TemplateResponse(request, "company/chat.html",
        context(request, user=user, company=company, messages=messages),
    )


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
                client_id = ""
                try:
                    payload = json.loads(raw)
                    message_text = str(payload.get("message") or "").strip()
                    client_id = str(payload.get("client_id") or "").strip()[:120]
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
                        "client_id": client_id,
                    },
                )
        except WebSocketDisconnect:
            manager.disconnect(company_id, websocket)
    finally:
        db.close()
