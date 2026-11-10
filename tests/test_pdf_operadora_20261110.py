"""PDF do cliente: consolidadora/sistema mostra só a companhia que opera o voo."""
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import Airline, CalculationType, WebCompany, WebQuote, WebUser
from app.services.operating_airline import client_airline
from app.services.pdf_service import quote_context
from app.web import templates


def _setup(partnership):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.add(WebCompany(id=1, name="ISI"))
    db.add(WebUser(id=1, name="R", email="pdf-op@example.invalid", password_hash="x", company_id=1))
    db.add(Airline(id=50, name="LATAM Airlines", slug="latam-x", color="#e11", engine_type="formula", builtin=True, active=True, logo_path="imagens/latam.png"))
    db.add(Airline(id=60, owner_company_id=1, name="Hotel DO", slug="hdo", color="#123", engine_type="formula", catalog_category="consolidators", active=True))
    db.add(CalculationType(id=61, airline_id=60, name="Tarifa", slug="t", formula="tarifa"))
    db.flush()
    quote = WebQuote(user_id=1, company_id=1, airline_id=60, calculation_type_id=61, quote_name="Cli", origin="GIG", destination="REC",
                     passengers=1, babies=0, bags=0, currency="BRL", input_json=json.dumps({"_partnership": partnership}), breakdown_json="{}", total=1000)
    db.add(quote); db.commit(); db.refresh(quote)
    return db, quote


def test_consolidadora_mostra_a_operadora():
    db, quote = _setup({"partner_airline": "LATAM Airlines"})
    shown = client_airline(quote)
    assert shown["name"] == "LATAM Airlines" and shown["logo_path"] == "imagens/latam.png"
    html = templates.env.get_template("pdf/quote.html").render(**quote_context(quote), request=None)
    assert "LATAM Airlines" in html and "Hotel DO" not in html


def test_consolidadora_sem_operadora_nao_mostra_fornecedor():
    db, quote = _setup({})
    assert client_airline(quote)["name"] == ""
    html = templates.env.get_template("pdf/quote.html").render(**quote_context(quote), request=None)
    assert "Hotel DO" not in html and "Companhia aérea" in html


def test_companhia_normal_continua_igual():
    db, quote = _setup({"partner_airline": "GOL"})
    quote.airline_id = 50; db.commit(); db.refresh(quote)
    assert client_airline(quote)["name"] == "LATAM Airlines"
