from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..dependencies import current_user
from ..models import Airline, QuoteRequest, WebQuote, WebUser
from ..web import context, flash, templates

router = APIRouter(tags=["panels"])


@router.get("/admin")
def admin_panel(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if user.role not in {"admin", "gerente"}:
        flash(request, "O painel administrativo é restrito.", "error")
        return RedirectResponse("/member", status_code=303)

    company_filter = WebQuote.company_id == user.company_id if user.company_id else WebQuote.user_id == user.id
    request_filter = QuoteRequest.company_id == user.company_id if user.company_id else QuoteRequest.owner_user_id == user.id
    airline_filter = Airline.owner_company_id == user.company_id if user.company_id else Airline.owner_user_id == user.id

    stats = {
        "members": db.scalar(select(func.count(WebUser.id)).where(WebUser.company_id == user.company_id)) if user.company_id else 1,
        "quotes": db.scalar(select(func.count(WebQuote.id)).where(company_filter)) or 0,
        "total": db.scalar(select(func.coalesce(func.sum(WebQuote.total), 0)).where(company_filter)) or 0,
        "pending_requests": db.scalar(select(func.count(QuoteRequest.id)).where(request_filter, QuoteRequest.status.in_(["recebida", "em_analise"]))) or 0,
        "custom_airlines": db.scalar(select(func.count(Airline.id)).where(Airline.builtin.is_(False), airline_filter)) or 0,
    }
    recent_quotes = db.scalars(select(WebQuote).where(company_filter).options(selectinload(WebQuote.airline), selectinload(WebQuote.user)).order_by(desc(WebQuote.created_at)).limit(8)).all()
    recent_requests = db.scalars(select(QuoteRequest).where(request_filter).order_by(desc(QuoteRequest.created_at)).limit(6)).all()
    return templates.TemplateResponse(request, "panels/admin.html", context(request, user=user, stats=stats, recent_quotes=recent_quotes, recent_requests=recent_requests))


@router.get("/member")
def member_panel(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    personal_quotes = db.scalar(select(func.count(WebQuote.id)).where(WebQuote.user_id == user.id)) or 0
    personal_total = db.scalar(select(func.coalesce(func.sum(WebQuote.total), 0)).where(WebQuote.user_id == user.id)) or 0
    team_quotes = db.scalar(select(func.count(WebQuote.id)).where(WebQuote.company_id == user.company_id)) if user.company_id else personal_quotes
    recent_quotes = db.scalars(select(WebQuote).where(WebQuote.user_id == user.id).options(selectinload(WebQuote.airline)).order_by(desc(WebQuote.created_at)).limit(8)).all()
    return templates.TemplateResponse(request, "panels/member.html", context(request, user=user, personal_quotes=personal_quotes, personal_total=personal_total, team_quotes=team_quotes, recent_quotes=recent_quotes))
