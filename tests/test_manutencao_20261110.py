"""Manutenção: banco atualizado automaticamente e nada de cópias/backups no app."""
from pathlib import Path

from sqlalchemy import Column, Integer, MetaData, String, Boolean, Table, create_engine, inspect, text

from app.database import Base
from app.services.schema_sync import plan, schema_fingerprint, sync_schema

ROOT = Path(__file__).resolve().parents[1]


def _old_and_new():
    old = MetaData()
    Table("clientes", old, Column("id", Integer, primary_key=True), Column("nome", String(80)))
    new = MetaData()
    Table("clientes", new, Column("id", Integer, primary_key=True), Column("nome", String(80)),
          Column("apelido", String(40)), Column("vip", Boolean, nullable=False, server_default=text("0")))
    Table("pedidos", new, Column("id", Integer, primary_key=True))
    return old, new


def test_cria_coluna_e_tabela_que_faltam_sem_perder_dados():
    engine = create_engine("sqlite://")
    old, new = _old_and_new()
    old.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO clientes (id, nome) VALUES (1, 'Maria')"))

    report = sync_schema(engine, new)
    assert report.tables_created == ["pedidos"]
    assert sorted(report.columns_added) == ["clientes.apelido", "clientes.vip"]
    cols = {c["name"] for c in inspect(engine).get_columns("clientes")}
    assert {"apelido", "vip"} <= cols
    with engine.connect() as conn:
        assert conn.execute(text("SELECT nome, vip FROM clientes")).one() == ("Maria", 0)

    # Segunda inicialização: só confere a impressão digital e não faz nada.
    assert sync_schema(engine, new).skipped is True


def test_simulacao_nao_altera_o_banco():
    engine = create_engine("sqlite://")
    old, new = _old_and_new()
    old.create_all(engine)
    report = sync_schema(engine, new, dry_run=True)
    assert report.columns_added and "pedidos" in report.tables_created
    assert "apelido" not in {c["name"] for c in inspect(engine).get_columns("clientes")}


def test_banco_vazio_recebe_todo_o_sistema():
    from app import models  # noqa: F401
    engine = create_engine("sqlite://")
    sync_schema(engine, Base.metadata)
    with engine.connect() as conn:
        tables, columns = plan(conn, Base.metadata)
    assert tables == [] and columns == []


def test_impressao_digital_muda_quando_surge_coluna_nova():
    old, new = _old_and_new()
    assert schema_fingerprint(old) != schema_fingerprint(new)


def test_sem_copias_e_backups_dentro_do_app():
    proibidos = [
        p for p in (ROOT / "app").rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
        and (".bak" in p.name or "-ISIVIAGENS" in p.name or " (1)" in p.name or " (2)" in p.name)
    ]
    assert not (ROOT / "app" / "app").exists(), "pasta duplicada app/app"
    assert proibidos == [], f"Remova cópias antigas: {proibidos}"
