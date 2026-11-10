"""Atualização automática e segura do banco a cada deploy.

Compara os modelos do código (app/models.py) com o banco real e cria apenas o
que falta: tabelas novas e colunas novas. Nunca apaga nem altera dados.

Para não pesar a abertura do sistema no Vercel, guarda uma "impressão digital"
do esquema numa tabela pequena (dbm_schema_state). Em cada inicialização faz
uma única consulta: se a impressão bate, não faz mais nada. Se o código mudou
(deploy com coluna nova), compara e cria o que falta uma vez só.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.schema import CreateTable

logger = logging.getLogger(__name__)

STATE_TABLE = "dbm_schema_state"
LOCK_KEY = 7310452901  # trava do PostgreSQL: dois deploys não atualizam ao mesmo tempo


@dataclass
class SyncReport:
    skipped: bool = False
    tables_created: list[str] = field(default_factory=list)
    columns_added: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if self.skipped:
            return "banco já atualizado"
        parts = []
        if self.tables_created:
            parts.append(f"tabelas criadas: {', '.join(self.tables_created)}")
        if self.columns_added:
            parts.append(f"colunas criadas: {', '.join(self.columns_added)}")
        if self.warnings:
            parts.append(f"avisos: {'; '.join(self.warnings)}")
        return " | ".join(parts) or "nada a criar"


def schema_fingerprint(metadata) -> str:
    """Muda sempre que uma tabela ou coluna é adicionada aos modelos."""
    items = []
    for table in sorted(metadata.tables.values(), key=lambda t: t.name):
        items.append(table.name + ":" + ",".join(sorted(c.name for c in table.columns)))
    return hashlib.sha256("\n".join(items).encode()).hexdigest()[:32]


def _column_ddl(column, dialect) -> str:
    """DDL de uma coluna nova. Sem default no banco, entra como opcional (NULL)
    para nunca falhar em tabelas que já têm linhas."""
    ddl = f"{dialect.identifier_preparer.quote(column.name)} {column.type.compile(dialect=dialect)}"
    default = column.server_default
    if default is not None and getattr(default, "arg", None) is not None:
        arg = default.arg
        value = arg.text if hasattr(arg, "text") else str(arg)
        if dialect.name == "postgresql" and str(column.type).upper() == "BOOLEAN":
            value = {"0": "FALSE", "1": "TRUE"}.get(value.strip("'"), value)
        if hasattr(arg, "text"):
            ddl += f" DEFAULT {value}"
        else:
            ddl += " DEFAULT '" + value.replace("'", "''") + "'"
        if not column.nullable:
            ddl += " NOT NULL"
    return ddl


def _read_state(engine: Engine) -> str | None:
    try:
        with engine.connect() as conn:
            return conn.execute(text(f"SELECT fingerprint FROM {STATE_TABLE} WHERE id = 1")).scalar()
    except Exception:
        return None


def _write_state(conn, fingerprint: str) -> None:
    conn.execute(text(f"CREATE TABLE IF NOT EXISTS {STATE_TABLE} (id INTEGER PRIMARY KEY, fingerprint VARCHAR(64) NOT NULL, updated_at VARCHAR(40))"))
    conn.execute(text(f"DELETE FROM {STATE_TABLE} WHERE id = 1"))
    conn.execute(
        text(f"INSERT INTO {STATE_TABLE} (id, fingerprint, updated_at) VALUES (1, :f, CURRENT_TIMESTAMP)"),
        {"f": fingerprint},
    )


def plan(engine: Engine, metadata) -> tuple[list, list[tuple]]:
    """O que falta no banco: (tabelas, [(tabela, coluna)])."""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    missing_tables = [t for t in metadata.sorted_tables if t.name not in existing_tables]
    missing_columns = []
    for table in metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        have = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name not in have:
                missing_columns.append((table, column))
    return missing_tables, missing_columns


def sync_schema(engine: Engine, metadata, *, force: bool = False, dry_run: bool = False) -> SyncReport:
    report = SyncReport()
    fingerprint = schema_fingerprint(metadata)
    if not force and not dry_run and _read_state(engine) == fingerprint:
        report.skipped = True
        return report

    dialect = engine.dialect
    is_pg = dialect.name == "postgresql"
    with engine.begin() as conn:
        if is_pg and not dry_run:
            conn.execute(text("SET LOCAL lock_timeout = '3s'"))
            conn.execute(text("SET LOCAL statement_timeout = '20s'"))
            got_lock = conn.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": LOCK_KEY}).scalar()
            if not got_lock:
                report.skipped = True
                report.warnings.append("outra inicialização já está atualizando o banco")
                return report

        missing_tables, missing_columns = plan(conn, metadata)
        for table in missing_tables:
            report.tables_created.append(table.name)
            if not dry_run:
                conn.execute(CreateTable(table, if_not_exists=True))
        for table, column in missing_columns:
            name = f"{table.name}.{column.name}"
            report.columns_added.append(name)
            if not column.nullable and column.server_default is None:
                report.warnings.append(f"{name} criada como opcional (sem valor padrão no banco)")
            if dry_run:
                continue
            exists = " IF NOT EXISTS" if is_pg else ""
            conn.execute(text(f"ALTER TABLE {dialect.identifier_preparer.quote(table.name)} ADD COLUMN{exists} {_column_ddl(column, dialect)}"))
        if not dry_run:
            _write_state(conn, fingerprint)
    return report


def sync_schema_safely(engine: Engine, metadata) -> SyncReport | None:
    """Versão da inicialização: nunca derruba o sistema por causa do banco."""
    try:
        report = sync_schema(engine, metadata)
        if not report.skipped or report.warnings:
            logger.info("Atualização do banco: %s", report.summary())
        return report
    except Exception as exc:
        logger.warning("Atualização automática do banco falhou (o sistema continua): %s", exc)
        return None
