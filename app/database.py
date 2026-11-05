from __future__ import annotations

import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool

from .config import DATABASE_URL, IS_VERCEL


class Base(DeclarativeBase):
    pass


if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
elif IS_VERCEL:
    # Falha rápido se o Neon/Postgres estiver indisponível, em vez de deixar a
    # Function presa até o timeout da Vercel.
    connect_args = {
        "connect_timeout": 8,
        "application_name": "dbmilesx-vercel",
    }
else:
    connect_args = {}

if not DATABASE_URL.startswith("sqlite"):
    # Compatível com o pooler do Neon (PgBouncer): sem prepared statements no servidor.
    connect_args["prepare_threshold"] = None

engine_options = {
    "connect_args": connect_args,
    "pool_pre_ping": True,
    "future": True,
}
if IS_VERCEL and not DATABASE_URL.startswith("sqlite"):
    # Desempenho: antes cada pedido abria uma conexão NOVA com o Neon (TCP + TLS +
    # autenticação = várias idas e voltas pela rede). Agora a instância do Vercel
    # reaproveita uma conexão aberta entre pedidos. pool_pre_ping descarta
    # conexões que o Neon encerrou; pool_recycle renova antes do tempo limite.
    # Para voltar ao modo antigo: variável DB_POOL_MODE=null no Vercel.
    if os.getenv("DB_POOL_MODE", "").strip().lower() == "null":
        engine_options["poolclass"] = NullPool
    else:
        engine_options.update(pool_size=1, max_overflow=4, pool_recycle=240, pool_timeout=10)

engine = create_engine(DATABASE_URL, **engine_options)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
