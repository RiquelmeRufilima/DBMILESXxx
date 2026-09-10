from __future__ import annotations

import logging
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


def _columns(engine: Engine, table: str) -> set[str]:
    try:
        return {col["name"] for col in inspect(engine).get_columns(table)}
    except Exception:
        return set()


def _add_column_sqlite(conn, table: str, name: str, ddl: str) -> None:
    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def _add_column_postgres(conn, table: str, name: str, ddl: str) -> None:
    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {ddl}"))


def _add_columns(engine: Engine, table: str, spec: dict[str, str]) -> None:
    existing = _columns(engine, table)
    if not existing:
        return
    dialect = engine.dialect.name
    with engine.begin() as conn:
        for name, ddl in spec.items():
            if name in existing:
                continue
            try:
                if dialect == "postgresql":
                    pg_ddl = (
                        ddl.replace("INTEGER", "INTEGER")
                           .replace("VARCHAR(80)", "VARCHAR(80)")
                           .replace("VARCHAR(180)", "VARCHAR(180)")
                           .replace("VARCHAR(500)", "VARCHAR(500)")
                           .replace("FLOAT", "DOUBLE PRECISION")
                           .replace("TEXT", "TEXT")
                           .replace("DATETIME", "TIMESTAMP")
                    )
                    # SQLite aceita 0/1 como default de BOOLEAN; PostgreSQL exige
                    # FALSE/TRUE. Corrige migrações de bancos antigos.
                    pg_ddl = pg_ddl.replace("BOOLEAN DEFAULT 0", "BOOLEAN DEFAULT FALSE")
                    pg_ddl = pg_ddl.replace("BOOLEAN DEFAULT 1", "BOOLEAN DEFAULT TRUE")
                    _add_column_postgres(conn, table, name, pg_ddl)
                else:
                    _add_column_sqlite(conn, table, name, ddl)
                logger.info("Coluna adicionada: %s.%s", table, name)
            except Exception as exc:
                logger.warning("Não foi possível adicionar coluna %s.%s: %s", table, name, exc)


def ensure_runtime_schema(engine: Engine) -> None:
    """Pequenas migrações compatíveis com bancos locais já existentes.

    Base.metadata.create_all cria tabelas novas, mas não adiciona colunas em tabelas
    antigas. Esta rotina mantém bancos já usados compatíveis com as versões novas.
    """
    accepted_cols = {
        "quote_id": "INTEGER",
        "updated_at": "DATETIME",
        "status": "VARCHAR(40) DEFAULT 'aceita' NOT NULL",
        "channel": "VARCHAR(80)",
        "locator": "VARCHAR(80)",
        "sale_value": "FLOAT",
        "payment_status": "VARCHAR(60)",
        "invoice_status": "VARCHAR(60)",
        "terms": "TEXT",
        "extra_json": "TEXT DEFAULT '{}' NOT NULL",
    }
    flight_cols = {
        "quote_id": "INTEGER",
        "updated_at": "DATETIME",
        "notification_mode": "VARCHAR(60)",
        "locator": "VARCHAR(80)",
        "flight_number": "VARCHAR(80)",
        "airline_name": "VARCHAR(180)",
        "departure_time": "VARCHAR(20)",
        "arrival_time": "VARCHAR(20)",
        "checkin_link": "VARCHAR(500)",
        "extra_json": "TEXT DEFAULT '{}' NOT NULL",
    }
    _add_columns(engine, "web_accepted_quotes", accepted_cols)
    _add_columns(engine, "web_flight_registry", flight_cols)
    quote_trip_cols = {
        "client_person_id": "INTEGER",
    }
    _add_columns(engine, "web_quote_trip_details", quote_trip_cols)
    quote_group_trip_cols = {
        "client_person_id": "INTEGER",
        "variants_json": "TEXT DEFAULT '[]' NOT NULL",
        "flexibility_days": "INTEGER DEFAULT 0 NOT NULL",
    }
    _add_columns(engine, "web_quote_group_trip_details", quote_group_trip_cols)

    airline_existing_cols = _columns(engine, "web_airlines")
    airline_scope_was_missing = bool(airline_existing_cols) and "market_scope" not in airline_existing_cols
    airline_cols = {
        "market_scope": "VARCHAR(20) DEFAULT 'both' NOT NULL",
        "partner_airlines_json": "TEXT DEFAULT '[]' NOT NULL",
    }
    _add_columns(engine, "web_airlines", airline_cols)

    # Na primeira atualização de um banco antigo, classifica as companhias
    # padrão uma única vez. Depois disso, alterações feitas pelo administrador
    # não são sobrescritas em novos reinícios.
    if airline_scope_was_missing:
        try:
            with engine.begin() as conn:
                builtin_true = "TRUE" if engine.dialect.name == "postgresql" else "1"
                conn.execute(text(
                    "UPDATE web_airlines "
                    "SET market_scope = CASE "
                    "WHEN slug IN ('azul','gol','latam') THEN 'both' "
                    "WHEN slug = 'voepass' THEN 'national' "
                    "ELSE 'international' END "
                    f"WHERE builtin = {builtin_true}"
                ))
        except Exception as exc:
            logger.warning("Não foi possível classificar companhias padrão: %s", exc)

    commercial_cols = {
        "cost_basis": "FLOAT",
        "profit_value": "FLOAT",
        "profit_percent": "FLOAT",
        "sent_to_client_at": "DATETIME",
        "card_difference_value": "FLOAT",
        "card_installment_value": "FLOAT",
        "card_total_value": "FLOAT",
        "card_interest_mode": "VARCHAR(20) DEFAULT 'cash' NOT NULL",
        "card_installments": "INTEGER DEFAULT 1 NOT NULL",
    }
    _add_columns(engine, "web_quote_commercial", commercial_cols)

    quote_group_cols = {
        "assigned_user_id": "INTEGER",
    }
    _add_columns(engine, "web_quote_groups", quote_group_cols)
    user_cols = {
        "is_owner": "BOOLEAN DEFAULT 0 NOT NULL",
        "auth_version": "INTEGER DEFAULT 1 NOT NULL",
    }
    _add_columns(engine, "web_users", user_cols)
    chat_cols = {
        "attachment_path": "VARCHAR(500)",
        "attachment_name": "VARCHAR(255)",
        "attachment_type": "VARCHAR(80)",
        "attachment_size": "INTEGER",
    }
    _add_columns(engine, "web_chat_messages", chat_cols)
    task_cols = {
        "company_id": "INTEGER",
        "created_by_user_id": "INTEGER",
        "assigned_user_id": "INTEGER",
        "quote_group_id": "INTEGER",
        "title": "VARCHAR(180)",
        "description": "TEXT",
        "priority": "VARCHAR(20) DEFAULT 'normal' NOT NULL",
        "status": "VARCHAR(30) DEFAULT 'pendente' NOT NULL",
        "due_at": "DATETIME",
        "completed_at": "DATETIME",
        "photo_path": "VARCHAR(500)",
        "created_at": "DATETIME",
        "updated_at": "DATETIME",
    }
    _add_columns(engine, "web_company_tasks", task_cols)
