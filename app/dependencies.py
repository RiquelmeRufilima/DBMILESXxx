from __future__ import annotations

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from .models import WebUser
from .services.user_defaults import ensure_user_defaults


def current_user(request: Request, db: Session) -> WebUser | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    user = db.get(WebUser, int(user_id))
    if user is None or not user.active:
        request.session.clear()
        return None

    session_version = request.session.get("auth_version")
    if session_version is not None and int(session_version) != int(user.auth_version or 1):
        request.session.clear()
        return None
    if session_version is None:
        request.session["auth_version"] = int(user.auth_version or 1)

    # Primeiro acesso criado pelo Google: enquanto o usuário ainda não definir
    # uma senha local, nenhuma área autenticada do DBMILESX pode ser aberta.
    # As rotas específicas de criação de senha não passam por current_user(),
    # portanto continuam acessíveis normalmente.
    if str(user.password_hash or "").startswith("google_pending$"):
        request.session["google_password_setup_required"] = True
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/auth/google/create-password"},
            detail="Conclua o primeiro acesso criando sua senha.",
        )

    request.session.pop("google_password_setup_required", None)
    ensure_user_defaults(db, user)
    return user


def require_user(request: Request, db: Session) -> WebUser:
    user = current_user(request, db)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Login necessário")
    return user


def require_admin(user: WebUser) -> None:
    if user.role not in {"admin", "gerente"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso restrito")
