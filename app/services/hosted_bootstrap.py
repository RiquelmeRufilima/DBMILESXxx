from __future__ import annotations

import logging
import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import WebCompany, WebUser
from ..security import hash_password, validate_password
from .user_defaults import ensure_user_defaults

logger = logging.getLogger(__name__)


def ensure_hosted_admin(db: Session) -> bool:
    """Cria o primeiro administrador somente quando o banco está vazio.

    Variáveis:
      BOOTSTRAP_ADMIN_EMAIL
      BOOTSTRAP_ADMIN_PASSWORD
      BOOTSTRAP_ADMIN_NAME
      BOOTSTRAP_COMPANY_NAME

    Depois do primeiro acesso, BOOTSTRAP_ADMIN_PASSWORD pode ser removida do
    Vercel e um novo deploy pode ser feito.
    """
    if db.scalar(select(WebUser.id).limit(1)) is not None:
        return False

    email = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()
    password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "")
    name = os.getenv("BOOTSTRAP_ADMIN_NAME", "Administrador").strip() or "Administrador"
    company_name = os.getenv("BOOTSTRAP_COMPANY_NAME", "DBMILESX").strip() or "DBMILESX"

    if not email or not password:
        logger.warning(
            "Banco sem usuários. Configure BOOTSTRAP_ADMIN_EMAIL e "
            "BOOTSTRAP_ADMIN_PASSWORD para criar o primeiro acesso."
        )
        return False

    valid, message = validate_password(password)
    if not valid:
        raise RuntimeError(f"BOOTSTRAP_ADMIN_PASSWORD inválida: {message}")

    company = WebCompany(name=company_name, email=email)
    db.add(company)
    db.flush()

    user = WebUser(
        company_id=company.id,
        email=email,
        password_hash=hash_password(password),
        name=name[:180],
        role="admin",
        active=True,
        is_owner=True,
        auth_version=1,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    ensure_user_defaults(db, user)
    logger.info("Primeiro administrador hospedado criado: %s", email)
    return True
