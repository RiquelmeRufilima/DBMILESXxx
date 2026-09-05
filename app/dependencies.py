from __future__ import annotations

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from .models import WebUser
from .services.user_defaults import ensure_user_defaults


def current_user(request: Request, db: Session) -> WebUser | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    user = db.scalar(
        select(WebUser)
        .where(WebUser.id == int(user_id))
        .options(joinedload(WebUser.profile), joinedload(WebUser.preference))
    )
    if user is None or not user.active:
        request.session.clear()
        return None

    session_version = request.session.get("auth_version")
    if session_version is not None and int(session_version) != int(user.auth_version or 1):
        request.session.clear()
        return None
    if session_version is None:
        request.session["auth_version"] = int(user.auth_version or 1)

    # Perfil e preferências já vêm na mesma consulta. A rotina de criação só
    # roda para contas antigas que realmente estejam sem uma dessas linhas.
    if user.profile is None or user.preference is None:
        ensure_user_defaults(db, user)
        user = db.scalar(
            select(WebUser)
            .where(WebUser.id == int(user_id))
            .options(joinedload(WebUser.profile), joinedload(WebUser.preference))
        ) or user
    return user


def require_user(request: Request, db: Session) -> WebUser:
    user = current_user(request, db)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Login necessário")
    return user


def require_admin(user: WebUser) -> None:
    if user.role not in {"admin", "gerente"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso restrito")
