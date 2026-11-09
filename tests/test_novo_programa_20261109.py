"""Tela de novo cadastro: categoria, salvar de verdade, teste da fórmula e erros sem perder dados."""
from __future__ import annotations

import json
import os

import pytest

assert os.environ["DATABASE_URL"].startswith("sqlite:///"), "SQLite de testes obrigatório"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Airline  # noqa: E402
from app.web import catalog_group  # noqa: E402
from tests.test_security import csrf_from, logged, make_company, make_user  # noqa: E402


@pytest.fixture(scope="module")
def admin_client():
    with TestClient(app):
        company = make_company("Agência Programas")
        make_user("programas-admin@example.invalid", company_id=company, role="admin", owner=True)
        yield logged(None, "programas-admin@example.invalid")


def _airline(name):
    db = SessionLocal()
    try:
        return db.scalars(select(Airline).where(Airline.name == name)).first()
    finally:
        db.close()


def test_tela_tem_as_quatro_categorias(admin_client):
    html = admin_client.get("/airlines/new").text
    for value in ("miles", "airlines", "systems", "consolidators"):
        assert f'name="catalog_kind" value="{value}"' in html
    assert "Programa de milhas" in html


def test_cria_programa_de_milhas_que_aparece_na_aba_certa(admin_client):
    token = csrf_from(admin_client.get("/airlines/new").text)
    fields = [
        {"label": "Milhas", "key": "milhas", "field_type": "number", "default_value": "0"},
        {"label": "Valor do milheiro (R$)", "key": "milheiro", "field_type": "number", "default_value": "0"},
        {"label": "Taxas (R$)", "key": "taxa", "field_type": "number", "default_value": "0"},
    ]
    resp = admin_client.post("/airlines/new", data={
        "csrf_token": token, "catalog_kind": "miles", "name": "Smiles Teste", "market_scope": "both",
        "color": "#ff8800", "calculation_name": "Milhas + taxas", "apply_mode": "total",
        "formula": "(milhas / 1000 * milheiro) + taxa", "fields_json": json.dumps(fields),
    })
    assert resp.status_code == 303, resp.text[:500]
    airline = _airline("Smiles Teste")
    assert airline is not None
    assert airline.catalog_category == "airlines" and airline.catalog_display == "miles"
    db = SessionLocal()
    try:
        loaded = db.get(Airline, airline.id)
        assert catalog_group(loaded) == "miles"
        assert len(loaded.calculation_types) == 1
    finally:
        db.close()
    page = admin_client.get("/airlines").text
    assert 'data-category="miles" data-airline-name="smiles teste"' in page


def test_sem_campos_usa_o_modelo_da_categoria(admin_client):
    token = csrf_from(admin_client.get("/airlines/new").text)
    resp = admin_client.post("/airlines/new", data={"csrf_token": token, "catalog_kind": "consolidators", "name": "Pátria Teste"})
    assert resp.status_code == 303
    airline = _airline("Pátria Teste")
    assert airline.catalog_category == "consolidators"


def test_erro_mantem_os_dados_preenchidos(admin_client):
    token = csrf_from(admin_client.get("/airlines/new").text)
    resp = admin_client.post("/airlines/new", data={
        "csrf_token": token, "catalog_kind": "miles", "name": "Programa Com Erro",
        "formula": "milhas * valor_inexistente",
        "fields_json": json.dumps([{"label": "Milhas", "key": "milhas"}]),
    })
    assert resp.status_code == 400
    assert "Não foi salvo" in resp.text
    assert 'value="Programa Com Erro"' in resp.text
    assert _airline("Programa Com Erro") is None


def test_nome_repetido_nao_duplica(admin_client):
    token = csrf_from(admin_client.get("/airlines/new").text)
    resp = admin_client.post("/airlines/new", data={"csrf_token": token, "catalog_kind": "miles", "name": "Smiles Teste"})
    assert resp.status_code == 400
    assert "Já existe um cadastro" in resp.text


def test_teste_instantaneo_da_formula(admin_client):
    ok = admin_client.post("/airlines/formula-preview", json={
        "formula": "(milhas / 1000 * milheiro) + taxa",
        "fields": [{"label": "Milhas", "key": "milhas"}, {"label": "Milheiro", "key": "milheiro"}, {"label": "Taxa", "key": "taxa"}],
        "values": {"milhas": "50000", "milheiro": "17,50", "taxa": "120"},
    }).json()
    assert ok == {"ok": True, "result": 995.0}
    bad = admin_client.post("/airlines/formula-preview", json={"formula": "milhas *", "fields": [{"label": "Milhas", "key": "milhas"}]}).json()
    assert bad["ok"] is False and bad["error"]


def test_trocar_categoria_na_edicao(admin_client):
    airline = _airline("Pátria Teste")
    page = admin_client.get(f"/airlines/{airline.id}").text
    token = csrf_from(page)
    resp = admin_client.post(f"/airlines/{airline.id}/category", data={"csrf_token": token, "catalog_kind": "miles"})
    assert resp.status_code == 303
    updated = _airline("Pátria Teste")
    assert (updated.catalog_category, updated.catalog_display) == ("airlines", "miles")
