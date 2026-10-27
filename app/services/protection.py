"""Proteções de segurança: limite de tentativas e bloqueio pelo administrador.

Tudo fica no banco (e não na memória) porque no Vercel cada requisição pode cair
em uma instância diferente. As tabelas são criadas sob demanda, no mesmo padrão
de services/auth_email.py, para não exigir migração manual no Neon.
"""
from __future__ import annotations

import hashlib
import logging
import math
from datetime import datetime, timedelta

from fastapi import Request
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..models import AuthAttempt, QuoteTag, QuoteTagLink, UserAccessBlock

logger = logging.getLogger(__name__)

_SCHEMA_READY = False


# Limites padrão: (máximo de tentativas, janela em minutos)
LIMITS: dict[str, tuple[int, int]] = {
    "login_email": (5, 15),       # 5 senhas erradas por e-mail a cada 15 min
    "login_ip": (20, 15),         # 20 erros por IP a cada 15 min
    "register_ip": (8, 60),       # 8 cadastros por IP por hora
    "code_ip": (15, 15),          # códigos de e-mail digitados por IP
    "code_email": (10, 60),       # códigos errados para o mesmo e-mail por hora
    "forgot_ip": (6, 60),         # pedidos de recuperação de senha por IP
    "company_join": (8, 15),      # tentativas de código da empresa por usuário
    "contact_lookup": (30, 10),   # buscas de ID de contato (evita varredura)
    "public_request_ip": (15, 60),  # formulário público de solicitação
}


def ensure_protection_schema(db: Session) -> None:
    """Cria as tabelas novas uma única vez por instância."""
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    bind = db.get_bind()
    for table in (
        AuthAttempt.__table__,
        UserAccessBlock.__table__,
        QuoteTag.__table__,
        QuoteTagLink.__table__,
    ):
        try:
            table.create(bind=bind, checkfirst=True)
        except Exception as exc:  # pragma: no cover - corrida entre instâncias
            logger.warning("Tabela %s não pôde ser criada agora: %s", table.name, exc)
    _SCHEMA_READY = True


def client_ip(request: Request) -> str:
    """IP real do visitante. No Vercel, x-forwarded-for é definido pela plataforma."""
    headers = request.headers
    for name in ("x-vercel-forwarded-for", "x-real-ip", "x-forwarded-for"):
        value = headers.get(name)
        if value:
            return value.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "unknown")[:64]


def _key(value: str) -> str:
    """Guarda só um hash (não armazena e-mail/IP em texto puro)."""
    return hashlib.sha256(str(value or "").strip().lower().encode("utf-8")).hexdigest()


def seconds_until_allowed(db: Session, bucket: str, key: str) -> int:
    """0 = pode tentar. >0 = segundos até liberar."""
    ensure_protection_schema(db)
    limit, minutes = LIMITS.get(bucket, (10, 15))
    since = datetime.utcnow() - timedelta(minutes=minutes)
    hashed = _key(key)
    try:
        count = db.scalar(
            select(func.count(AuthAttempt.id)).where(
                AuthAttempt.bucket == bucket,
                AuthAttempt.key == hashed,
                AuthAttempt.created_at >= since,
            )
        ) or 0
        if count < limit:
            return 0
        oldest = db.scalar(
            select(func.min(AuthAttempt.created_at)).where(
                AuthAttempt.bucket == bucket,
                AuthAttempt.key == hashed,
                AuthAttempt.created_at >= since,
            )
        )
    except Exception as exc:
        # Nunca derruba o login por falha do limitador.
        logger.warning("Limitador indisponível (%s): %s", bucket, exc)
        db.rollback()
        return 0
    if oldest is None:
        return 0
    remaining = (oldest + timedelta(minutes=minutes) - datetime.utcnow()).total_seconds()
    return max(1, int(math.ceil(remaining)))


def register_attempt(db: Session, bucket: str, key: str, *, commit: bool = True) -> None:
    ensure_protection_schema(db)
    try:
        db.add(AuthAttempt(bucket=bucket, key=_key(key), created_at=datetime.utcnow()))
        if commit:
            db.commit()
    except Exception as exc:
        logger.warning("Não foi possível registrar tentativa (%s): %s", bucket, exc)
        db.rollback()


def clear_attempts(db: Session, bucket: str, key: str, *, commit: bool = True) -> None:
    ensure_protection_schema(db)
    try:
        db.execute(delete(AuthAttempt).where(AuthAttempt.bucket == bucket, AuthAttempt.key == _key(key)))
        if commit:
            db.commit()
    except Exception as exc:
        logger.warning("Não foi possível limpar tentativas (%s): %s", bucket, exc)
        db.rollback()


def prune_old_attempts(db: Session) -> None:
    """Remove registros com mais de 1 dia (chamado de vez em quando)."""
    ensure_protection_schema(db)
    try:
        db.execute(delete(AuthAttempt).where(AuthAttempt.created_at < datetime.utcnow() - timedelta(days=1)))
        db.commit()
    except Exception:
        db.rollback()


def wait_message(seconds: int) -> str:
    minutes = max(1, int(math.ceil(seconds / 60)))
    return f"Muitas tentativas. Aguarde {minutes} minuto(s) e tente novamente."


# ---------------------------------------------------------------------------
# Bloqueio pelo administrador
# ---------------------------------------------------------------------------
def is_blocked(db: Session, user_id: int | None) -> bool:
    if not user_id:
        return False
    ensure_protection_schema(db)
    try:
        return db.get(UserAccessBlock, int(user_id)) is not None
    except Exception:
        db.rollback()
        return False


def set_blocked(db: Session, user_id: int, blocked: bool, by_user_id: int | None = None) -> None:
    """Não faz commit: quem chama decide."""
    ensure_protection_schema(db)
    current = db.get(UserAccessBlock, int(user_id))
    if blocked and current is None:
        db.add(UserAccessBlock(user_id=int(user_id), blocked_by_user_id=by_user_id))
    elif not blocked and current is not None:
        db.delete(current)
