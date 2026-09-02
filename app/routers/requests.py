from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, selectinload

from ..config import APP_URL
from ..database import get_db
from ..dependencies import current_user
from ..models import PublicQuoteLink, QuoteRequest, WebCompany
from ..security import validate_csrf_token
from ..services.notifications import create_notification
from ..web import context, flash, templates

router = APIRouter(tags=["requests"])


def _owner_filter(user):
    return PublicQuoteLink.company_id == user.company_id if user.company_id else PublicQuoteLink.owner_user_id == user.id


def _request_filter(user):
    return QuoteRequest.company_id == user.company_id if user.company_id else QuoteRequest.owner_user_id == user.id


@router.get("/requests/links")
def links_page(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    links = db.scalars(
        select(PublicQuoteLink)
        .where(_owner_filter(user))
        .options(selectinload(PublicQuoteLink.requests))
        .order_by(desc(PublicQuoteLink.created_at))
    ).all()
    base_url = str(request.base_url).rstrip("/")
    return templates.TemplateResponse(request, "requests/links.html", context(request, user=user, links=links, base_url=base_url))


@router.post("/requests/links/new")
def create_link(
    request: Request,
    title: str = Form("Solicite sua cotação"),
    description: str = Form(""),
    valid_days: int = Form(30),
    max_uses: int = Form(100),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/requests/links", status_code=303)
    link = PublicQuoteLink(
        owner_user_id=user.id,
        company_id=user.company_id,
        token=secrets.token_urlsafe(18),
        title=title.strip()[:180] or "Solicite sua cotação",
        description=description.strip()[:2000] or None,
        expires_at=datetime.utcnow() + timedelta(days=max(1, min(valid_days, 3650))),
        max_uses=max(1, min(max_uses, 100000)),
    )
    db.add(link)
    db.commit()
    flash(request, "Link público criado com sucesso.", "success")
    return RedirectResponse("/requests/links", status_code=303)


@router.post("/requests/links/{link_id}/toggle")
async def toggle_link(link_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/requests/links", status_code=303)
    item = db.scalar(select(PublicQuoteLink).where(PublicQuoteLink.id == link_id, _owner_filter(user)))
    if item:
        item.active = not item.active
        db.commit()
    return RedirectResponse("/requests/links", status_code=303)


@router.get("/requests/inbox")
def request_inbox(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    items = db.scalars(
        select(QuoteRequest)
        .where(_request_filter(user))
        .options(selectinload(QuoteRequest.public_link))
        .order_by(desc(QuoteRequest.created_at))
        .limit(500)
    ).all()
    unread = sum(1 for item in items if not item.read)
    return templates.TemplateResponse(request, "requests/inbox.html", context(request, user=user, requests_received=items, unread_requests=unread))


@router.get("/requests/{request_id}")
def request_detail(request_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    item = db.scalar(select(QuoteRequest).where(QuoteRequest.id == request_id, _request_filter(user)))
    if item is None:
        flash(request, "Solicitação não encontrada.", "error")
        return RedirectResponse("/requests/inbox", status_code=303)
    if not item.read:
        item.read = True
        db.commit()
    segments = json.loads(item.segments_json or "[]")
    return templates.TemplateResponse(request, "requests/detail.html", context(request, user=user, quote_request=item, segments=segments))


@router.post("/requests/{request_id}/status")
async def request_status(request_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse(f"/requests/{request_id}", status_code=303)
    item = db.scalar(select(QuoteRequest).where(QuoteRequest.id == request_id, _request_filter(user)))
    if item:
        status = str(form.get("status") or "recebida")
        item.status = status if status in {"recebida", "em_analise", "cotada", "concluida", "cancelada"} else "recebida"
        item.read = True
        db.commit()
        flash(request, "Status atualizado.", "success")
    return RedirectResponse(f"/requests/{request_id}", status_code=303)


@router.get("/requests/{request_id}/quote")
def quote_from_request(request_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    item = db.scalar(select(QuoteRequest).where(QuoteRequest.id == request_id, _request_filter(user)))
    if item is None:
        flash(request, "Solicitação não encontrada.", "error")
        return RedirectResponse("/requests/inbox", status_code=303)
    item.status = "em_analise"
    item.read = True
    db.commit()
    return RedirectResponse(f"/calculations/new?request_id={item.id}", status_code=303)


@router.get("/request/{token}")
def public_request_form(token: str, request: Request, db: Session = Depends(get_db)):
    link = db.scalar(select(PublicQuoteLink).where(PublicQuoteLink.token == token).options(selectinload(PublicQuoteLink.owner)))
    now = datetime.utcnow()
    valid = bool(link and link.active and (link.expires_at is None or link.expires_at >= now) and link.total_uses < link.max_uses)
    company = db.get(WebCompany, link.company_id) if link and link.company_id else None
    return templates.TemplateResponse(request, "requests/public.html", context(request, public_link=link, link_valid=valid, company=company))


@router.post("/request/{token}")
async def public_request_submit(token: str, request: Request, db: Session = Depends(get_db)):
    link = db.scalar(select(PublicQuoteLink).where(PublicQuoteLink.token == token).options(selectinload(PublicQuoteLink.owner)))
    now = datetime.utcnow()
    if not link or not link.active or (link.expires_at and link.expires_at < now) or link.total_uses >= link.max_uses:
        return templates.TemplateResponse(request, "requests/public.html", context(request, public_link=link, link_valid=False, company=None), status_code=410)

    form = await request.form()
    name = str(form.get("client_name") or "").strip()
    phone = str(form.get("phone") or "").strip()
    origin = str(form.get("origin") or "").strip()
    destination = str(form.get("destination") or "").strip()
    if not all([name, phone, origin, destination]):
        return templates.TemplateResponse(
            request,
            "requests/public.html",
            context(request, public_link=link, link_valid=True, company=db.get(WebCompany, link.company_id) if link.company_id else None, public_error="Preencha nome, telefone, origem e destino."),
            status_code=400,
        )

    try:
        segments = json.loads(str(form.get("segments_json") or "[]"))
        if not isinstance(segments, list):
            segments = []
    except json.JSONDecodeError:
        segments = []

    item = QuoteRequest(
        link_id=link.id,
        owner_user_id=link.owner_user_id,
        company_id=link.company_id,
        client_name=name[:180],
        phone=phone[:60],
        email=str(form.get("email") or "").strip()[:180] or None,
        travel_type=str(form.get("travel_type") or "round_trip"),
        origin=origin[:80],
        destination=destination[:80],
        departure_date=str(form.get("departure_date") or "")[:20] or None,
        return_date=str(form.get("return_date") or "")[:20] or None,
        adults=max(1, int(form.get("adults") or 1)),
        children=max(0, int(form.get("children") or 0)),
        babies=max(0, int(form.get("babies") or 0)),
        bags=max(0, int(form.get("bags") or 0)),
        segments_json=json.dumps(segments, ensure_ascii=False),
        notes=str(form.get("notes") or "").strip()[:4000] or None,
    )
    db.add(item)
    link.total_uses += 1
    db.flush()
    create_notification(
        db,
        link.owner_user_id,
        "Nova solicitação de cotação",
        f"{item.client_name} solicitou {item.origin} → {item.destination}.",
        kind="request",
        link=f"/requests/{item.id}",
        commit=False,
    )
    db.commit()
    return templates.TemplateResponse(request, "requests/success.html", context(request, public_link=link, request_id=item.id))
