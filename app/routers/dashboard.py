from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..dependencies import current_user
from ..models import Airline, CompanyTask, Person, WebQuote
from ..web import context, templates

router = APIRouter(tags=["dashboard"])


@router.get("/")
def root(request: Request):
    return RedirectResponse("/dashboard" if request.session.get("user_id") else "/login", status_code=303)


@router.get("/dashboard")
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)

    quote_filter = WebQuote.company_id == user.company_id if user.company_id else WebQuote.user_id == user.id
    airline_filter = (
        Airline.owner_company_id == user.company_id
        if user.company_id
        else Airline.owner_user_id == user.id
    )
    custom_airlines_sq = (
        select(func.count(Airline.id))
        .where(Airline.builtin.is_(False), airline_filter)
        .scalar_subquery()
    )
    stats = db.execute(
        select(
            func.count(WebQuote.id),
            func.coalesce(func.sum(WebQuote.total), 0),
            custom_airlines_sq,
        ).where(quote_filter)
    ).one()
    total_quotes = int(stats[0] or 0)
    total_value = float(stats[1] or 0)
    custom_airlines = int(stats[2] or 0)
    recent_quotes = db.scalars(
        select(WebQuote).where(quote_filter).options(selectinload(WebQuote.airline)).order_by(desc(WebQuote.created_at)).limit(6)
    ).all()
    person_filter = Person.company_id == user.company_id if user.company_id else Person.user_id == user.id
    pending_persons = db.scalars(
        select(Person).where(person_filter, Person.is_complete.is_(False), Person.active.is_(True)).order_by(desc(Person.created_at)).limit(8)
    ).all()
    task_filter = CompanyTask.company_id == user.company_id if user.company_id else CompanyTask.created_by_user_id == user.id
    pending_tasks = db.scalars(
        select(CompanyTask)
        .where(task_filter, CompanyTask.status == "pendente")
        .order_by(
            CompanyTask.due_at.is_(None),
            CompanyTask.due_at.asc(),
            desc(CompanyTask.created_at),
        )
        .limit(6)
    ).all()

    return templates.TemplateResponse(request, "dashboard.html",
        context(
            request,
            user=user,
            total_quotes=total_quotes,
            total_value=total_value,
            custom_airlines=custom_airlines,
            recent_quotes=recent_quotes,
            pending_persons=pending_persons,
            pending_tasks=pending_tasks,
        ),
    )
