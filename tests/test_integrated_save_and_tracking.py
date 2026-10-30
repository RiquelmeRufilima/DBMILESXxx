"""Regressão de cotação aceita: salvar não fecha e persiste serviços/valores."""
import asyncio
import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import AcceptedQuote, QuoteGroup, WebCompany, WebUser
from app.routers import cadastros, service_tracking


class RequestStub:
    def __init__(self, fields):
        self.session = {"flashes": []}
        self.fields = fields
    async def form(self):
        return self.fields


def test_salvar_sem_fechar_persiste_hospedagem_e_valores(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(WebCompany(id=27, name="Empresa Teste"))
        db.add(WebUser(id=47, name="Agente", email="agent-salvar@example.invalid", password_hash="x", company_id=27, role="admin"))
        db.add(QuoteGroup(id=322, user_id=47, company_id=27, quote_name="Cotação de hospedagem"))
        db.add(AcceptedQuote(group_id=322, user_id=47, company_id=27, extra_json=json.dumps({"title": "Cotação de hospedagem"})))
        db.commit()
        monkeypatch.setattr(cadastros, "require_user", lambda req, session: db.get(WebUser, 47))
        monkeypatch.setattr(cadastros, "validate_csrf_token", lambda *args: True)
        fields = {
            "csrf_token": "valid", "title": "Cotação de hospedagem", "quote_code": "m0322",
            "adults": "1", "children": "0", "babies": "0", "notes": "Check-in do cliente",
            "flights_json": "[]", "passengers_json": "[]",
            "services_json": json.dumps({"hotel": [{"name": "Hotel Exemplo", "reservation_number": "RES-291", "nights": 2, "stars": "4", "start_date": "2026-11-03", "end_date": "2026-11-05", "value": 1100}]}),
            "cost_items_json": json.dumps([{"description": "Hotel", "value": 800}]),
            "sale_items_json": json.dumps([{"description": "Hospedagem", "value": 1100}]),
            "commission_json": json.dumps({"receive": [], "pay": [], "extra": 0}),
            "sale_json": json.dumps({"date": "2026-11-03", "notes": "Reserva confirmada"}),
        }
        response = asyncio.run(cadastros.salvar_cotacao(322, RequestStub(fields), db))
        assert response.status_code == 303
        assert response.headers["location"] == "/cadastros/cotacoes/322"
        payload = json.loads(db.get(AcceptedQuote, 322).extra_json)
        assert payload["services"]["hotel"][0]["reservation_number"] == "RES-291"
        assert payload["services"]["hotel"][0]["stars"] == "4"
        assert payload["cost_items"][0]["value"] == 800
        assert payload["sale_items"][0]["value"] == 1100
        assert payload["sale"]["notes"] == "Reserva confirmada"


def test_menu_e_calendario_restaurados():
    base = Path(__file__).resolve().parents[1] / "app"
    html = (base / "templates/base.html").read_text()
    for kind in service_tracking.KINDS:
        assert f"/acompanhamentos/{kind}" in html
    form = (base / "templates/cadastros/cotacao_form.html").read_text()
    assert "tag_row('group', group.id" in form
    assert 'quote-consistent-dates-20261030.js' in form
    assert 'updateStayDuration()' in form
    assert 'function updateHotelStars()' in form
    assert 'event.submitter?.name === \'save_close\'' in form
