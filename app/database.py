from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool

from .config import DATABASE_URL, IS_VERCEL


class Base(DeclarativeBase):
    pass


connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine_options = {
    "connect_args": connect_args,
    "pool_pre_ping": True,
    "future": True,
}
if IS_VERCEL and not DATABASE_URL.startswith("sqlite"):
    # Evita manter pools locais presos a instâncias serverless diferentes.
    # Se o provedor oferecer URL de pooler (Neon/Supabase), use-a em DATABASE_URL.
    engine_options["poolclass"] = NullPool

engine = create_engine(DATABASE_URL, **engine_options)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
