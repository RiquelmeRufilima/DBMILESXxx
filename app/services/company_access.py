from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from ..models import CompanyInvite

logger = logging.getLogger(__name__)
_SCHEMA_READY = False


def ensure_company_access_schema(db: Session) -> None:
    """Prepara apenas o schema necessário à área Empresa.

    No Vercel o cold start propositalmente não executa a migração completa.
    Por isso a coluna adicionada na V2.17 precisa ser garantida antes de qualquer
    SELECT em web_companies. A operação é idempotente.
    """
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return

    bind = db.get_bind()

    try:
        columns = {col["name"] for col in inspect(bind).get_columns("web_companies")}
        if columns and "join_code_hash" not in columns:
            ddl = (
                "ALTER TABLE web_companies ADD COLUMN IF NOT EXISTS join_code_hash VARCHAR(255)"
                if bind.dialect.name == "postgresql"
                else "ALTER TABLE web_companies ADD COLUMN join_code_hash VARCHAR(255)"
            )
            with bind.begin() as conn:
                conn.execute(text(ddl))
            logger.info("Coluna web_companies.join_code_hash criada.")
    except Exception as exc:
        logger.warning("Falha ao garantir join_code_hash: %s", exc)
        raise

    # Tabela nova: create(checkfirst=True) é leve e segura.
    CompanyInvite.__table__.create(bind=bind, checkfirst=True)
    _SCHEMA_READY = True
