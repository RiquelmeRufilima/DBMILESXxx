from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


_INDEX_STATEMENTS = (
    "CREATE INDEX IF NOT EXISTS idx_perf_quotes_company_created ON web_quotes (company_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_perf_quotes_user_created ON web_quotes (user_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_perf_groups_company_created ON web_quote_groups (company_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_perf_groups_user_created ON web_quote_groups (user_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_perf_notifications_user_read_created ON web_notifications (user_id, read, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_perf_tasks_company_status_due ON web_company_tasks (company_id, status, due_at)",
    "CREATE INDEX IF NOT EXISTS idx_perf_tasks_creator_status_due ON web_company_tasks (created_by_user_id, status, due_at)",
    "CREATE INDEX IF NOT EXISTS idx_perf_persons_company_pending ON web_persons (company_id, is_complete, active, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_perf_persons_user_pending ON web_persons (user_id, is_complete, active, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_perf_airlines_company_active ON web_airlines (owner_company_id, active, builtin, name)",
    "CREATE INDEX IF NOT EXISTS idx_perf_options_group_position ON web_quote_option_index (group_id, position)",
)


def ensure_performance_indexes(engine: Engine) -> None:
    """Cria índices compostos usados pelas telas mais acessadas.

    É idempotente: depois do primeiro deploy, os CREATE INDEX IF NOT EXISTS
    viram apenas verificações rápidas.
    """
    try:
        with engine.begin() as conn:
            for statement in _INDEX_STATEMENTS:
                conn.execute(text(statement))
    except Exception as exc:
        # Índice é otimização, nunca motivo para impedir o sistema de abrir.
        logger.warning("Não foi possível garantir todos os índices de performance: %s", exc)
