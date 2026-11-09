"""Aceitar voo em cotação existente e mover/criar acompanhamentos."""
import asyncio
import json

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models import AcceptedQuote, QuoteGroup, QuoteTag, QuoteTagLink, WebCompany, WebUser
from app.routers import cadastros, service_tracking


class RequestStub:
    def __init__(self, fields=None):
        self.session = {"flashes": []}
        self.fields = fields or {}
        self.headers = {}
    async def form(self):
        return self.fields


def _db(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.add(WebCompany(id=1, name="Empresa"))
    db.add(WebUser(id=10, name="Agente", email="agente-destino@example.invalid", password_hash="x", company_id=1, role="admin"))
    db.commit()
    for module in (cadastros, service_tracking):
        monkeypatch.setattr(module, "require_user", lambda req, session: db.get(WebUser, 10), raising=False)
        monkeypatch.setattr(module, "validate_csrf_token", lambda *args: True, raising=False)
    return db


def _accepted(db, gid, payload, name=None):
    db.add(QuoteGroup(id=gid, user_id=10, company_id=1, quote_name=name or f"Cotação {gid}"))
    db.add(AcceptedQuote(group_id=gid, user_id=10, company_id=1, status="aguardando", sale_value=0, extra_json=json.dumps(payload)))
    db.commit()


def test_voo_aceito_em_cotacao_existente_soma_valores(monkeypatch):
    db = _db(monkeypatch)
    _accepted(db, 100, {
        "title": "Cliente Maria", "client_name": "Maria", "quote_code": "q0100",
        "flights": [{"label": "Voo de Ida", "origin": "FOR", "destination": "GRU", "departure_date": "2026-12-01"}],
        "cost_items": [{"description": "Ida", "value": 1000}],
        "sale_items": [{"description": "Ida", "value": 1500}],
        "commercial_offer": {"cost_value": 1000, "cash_sale_value": 1500},
    })
    db.add(QuoteGroup(id=200, user_id=10, company_id=1, quote_name="Volta Maria", origin="GRU", destination="FOR"))
    db.commit()
    seeded = {
        "flights": [{"label": "Voo de Volta", "origin": "GRU", "destination": "FOR", "departure_date": "2026-12-10", "selected_schedule": True}],
        "cost_items": [{"description": "Volta", "value": 700}],
        "sale_items": [{"description": "Volta", "value": 900}],
        "commission": {"receive": [], "pay": [], "extra": 0},
        "commercial_offer": {"cost_value": 700, "cash_sale_value": 900},
    }
    monkeypatch.setattr(cadastros, "_seed_payload", lambda group, quote=None: json.loads(json.dumps(seeded)))
    monkeypatch.setattr(cadastros, "_first_option_for_group", lambda *a: None)

    response = asyncio.run(cadastros.adicionar_cotacao_aceita(200, RequestStub({"csrf_token": "x", "target_group_id": "100"}), db))

    assert response.headers["location"] == "/cadastros/cotacoes/100"
    target = db.get(AcceptedQuote, 100)
    data = json.loads(target.extra_json)
    assert [f["label"] for f in data["flights"]] == ["Voo de Ida", "Voo de Volta"]
    assert all(f.get("selected_schedule") for f in data["flights"])  # os dois continuam na agenda
    assert sum(r["value"] for r in data["cost_items"]) == 1700
    assert sum(r["value"] for r in data["sale_items"]) == 2400
    assert target.sale_value == 2400
    assert data["commercial_offer"]["profit_value"] == 700
    # A cotação de origem NÃO vira uma cotação nova.
    assert db.get(AcceptedQuote, 200) is None


def test_cotacao_de_outra_empresa_nao_pode_ser_destino(monkeypatch):
    db = _db(monkeypatch)
    db.add(WebCompany(id=2, name="Outra"))
    db.add(WebUser(id=20, name="Outro", email="outro-destino@example.invalid", password_hash="x", company_id=2, role="admin"))
    db.add(QuoteGroup(id=300, user_id=20, company_id=2, quote_name="Alheia"))
    db.add(AcceptedQuote(group_id=300, user_id=20, company_id=2, extra_json="{}"))
    db.add(QuoteGroup(id=301, user_id=10, company_id=1, quote_name="Minha"))
    db.commit()
    monkeypatch.setattr(cadastros, "_first_option_for_group", lambda *a: None)
    req = RequestStub({"csrf_token": "x", "target_group_id": "300"})
    asyncio.run(cadastros.adicionar_cotacao_aceita(301, req, db))
    assert json.loads(db.get(AcceptedQuote, 300).extra_json) == {}
    assert db.get(AcceptedQuote, 301) is None


def test_destinos_lista_e_exclui(monkeypatch):
    db = _db(monkeypatch)
    _accepted(db, 401, {"title": "Viagem Lisboa", "client_name": "João", "quote_code": "q0401"})
    _accepted(db, 402, {"title": "Viagem Roma", "client_name": "Ana", "quote_code": "q0402"})
    body = json.loads(cadastros.destinos_cotacoes(RequestStub(), q="lisboa", exclude=0, db=db).body)
    assert [i["id"] for i in body["items"]] == [401]
    body = json.loads(cadastros.destinos_cotacoes(RequestStub(), q="", exclude=402, db=db).body)
    assert [i["id"] for i in body["items"]] == [401]


def test_mover_hospedagem_para_cotacao_existente_leva_etiquetas(monkeypatch):
    db = _db(monkeypatch)
    hotels = [{"name": "Hotel A"}, {"name": "Hotel B"}, {"name": "Hotel C"}]
    _accepted(db, 500, {"client_name": "Maria", "services": {"hotel": hotels}})
    _accepted(db, 600, {"client_name": "Maria", "services": {"hotel": [{"name": "Hotel X"}]}})
    tag = QuoteTag(company_id=1, user_id=10, name="VIP", color="#000000", kind="acompanhamento")
    db.add(tag); db.flush()
    tid = service_tracking._service_tag_id
    db.add(QuoteTagLink(tag_id=tag.id, target_kind="service", target_id=tid(500, "hospedagens", 0)))
    db.add(QuoteTagLink(tag_id=tag.id, target_kind="service", target_id=tid(500, "hospedagens", 2)))
    db.commit()

    response = asyncio.run(service_tracking.mover_acompanhamento("hospedagens", 500, 0, RequestStub({"csrf_token": "x", "target_group_id": "600"}), db))
    assert response.headers["location"] == "/acompanhamentos/hospedagens"

    src = json.loads(db.get(AcceptedQuote, 500).extra_json)["services"]["hotel"]
    dst = json.loads(db.get(AcceptedQuote, 600).extra_json)["services"]["hotel"]
    assert [h["name"] for h in src] == ["Hotel B", "Hotel C"]
    assert [h["name"] for h in dst] == ["Hotel X", "Hotel A"]
    ids = set(db.scalars(select(QuoteTagLink.target_id).where(QuoteTagLink.target_kind == "service")).all())
    assert ids == {tid(600, "hospedagens", 1), tid(500, "hospedagens", 1)}


def test_mover_para_nova_cotacao_e_novo_acompanhamento(monkeypatch):
    db = _db(monkeypatch)
    _accepted(db, 700, {"client_name": "Carlos", "services": {"transport": [{"name": "Transfer"}]}})
    asyncio.run(service_tracking.mover_acompanhamento("transportes", 700, 0, RequestStub({"csrf_token": "x", "target_group_id": ""}), db))
    novos = db.scalars(select(AcceptedQuote).where(AcceptedQuote.group_id != 700)).all()
    assert len(novos) == 1
    data = json.loads(novos[0].extra_json)
    assert data["client_name"] == "Carlos"
    assert data["services"]["transport"] == [{"name": "Transfer"}]
    assert json.loads(db.get(AcceptedQuote, 700).extra_json)["services"]["transport"] == []

    resp = asyncio.run(service_tracking.novo_acompanhamento("seguros", RequestStub({"csrf_token": "x", "target_group_id": "700"}), db))
    assert resp.headers["location"] == "/cadastros/cotacoes/700?origem=seguros&tab=orcamento&new_service=insurance"
