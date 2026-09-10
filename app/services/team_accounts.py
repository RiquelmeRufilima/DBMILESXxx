from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import MAX_TEAM_USERS
from ..models import WebCompany, WebUser


def ensure_company_owners(db: Session) -> int:
    """Marca um acesso principal em empresas antigas sem proprietário definido."""
    changed = 0
    companies = db.scalars(select(WebCompany)).all()
    for company in companies:
        already = db.scalar(
            select(WebUser.id).where(WebUser.company_id == company.id, WebUser.is_owner.is_(True)).limit(1)
        )
        if already:
            continue
        owner = db.scalar(
            select(WebUser)
            .where(WebUser.company_id == company.id)
            .order_by((WebUser.role == "admin").desc(), WebUser.created_at.asc(), WebUser.id.asc())
            .limit(1)
        )
        if owner:
            owner.is_owner = True
            owner.role = "admin"
            changed += 1
    if changed:
        db.commit()
    return changed


def team_user_count(db: Session, company_id: int) -> int:
    """Conta usuários adicionais; o acesso principal não entra no limite."""
    return int(
        db.scalar(
            select(func.count(WebUser.id)).where(
                WebUser.company_id == company_id,
                WebUser.is_owner.is_(False),
            )
        )
        or 0
    )


def remaining_team_slots(db: Session, company_id: int) -> int:
    return max(0, MAX_TEAM_USERS - team_user_count(db, company_id))


def can_create_team_user(db: Session, company_id: int) -> bool:
    return team_user_count(db, company_id) < MAX_TEAM_USERS
