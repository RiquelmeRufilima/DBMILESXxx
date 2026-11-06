"""Catálogo de companhias: cadastro automático na Vercel e tipo "Valor do site"."""
from pathlib import Path
from types import SimpleNamespace

from app.services import seed
from app.services.calculator import calculate
from app.services.travel_data import AIRLINE_OPTIONS, NO_MILES_AIRLINE_SLUGS, airline_key

ROOT = Path(__file__).resolve().parents[1]


def test_catalogo_tem_novas_companhias_sem_slug_repetido():
    slugs = [item["slug"] for item in AIRLINE_OPTIONS]
    assert len(slugs) == len(set(slugs))
    for slug in ("euroatlantic", "ryanair", "azulconecta", "map", "caboverde", "flydubai"):
        assert slug in slugs
    assert NO_MILES_AIRLINE_SLUGS <= set(slugs)


def test_apelidos_reconhecem_nomes():
    assert airline_key("EuroAtlantic Airways") == "euroatlantic"
    assert airline_key("Azul Conecta") == "azulconecta"
    assert airline_key("Azul Linhas Aéreas") == "azul"
    assert airline_key("Air Côte d'Ivoire") == "aircotedivoire"


def test_companhia_sem_milhas_usa_valor_do_site():
    item = next(b for b in seed.EXTRA_BUILTINS if b["slug"] == "euroatlantic")
    assert [t["legacy_key"] for t in item["types"]] == ["valor_site"]
    tap = next(b for b in seed.EXTRA_BUILTINS if b["slug"] == "tap")
    assert tap["types"][0]["legacy_key"] is None


def test_calculo_valor_do_site_com_desconto_e_bagagem():
    airline = SimpleNamespace(engine_type="formula")
    calc_type = SimpleNamespace(legacy_key="valor_site", formula="", apply_mode="total")
    result = calculate(airline, calc_type, {"valor_site": "5.000,00", "desconto_site": "10", "bagagem_unitaria": "300"}, 2, 0, 2)
    assert result.base == 4500.0
    assert result.baggage_total == 600.0
    assert result.total == 5100.0


def test_telas_completam_o_catalogo_na_vercel():
    calc = (ROOT / "app/routers/calculations.py").read_text(encoding="utf-8")
    airlines = (ROOT / "app/routers/airlines.py").read_text(encoding="utf-8")
    assert "ensure_catalog_airlines(db)" in calc
    assert "ensure_catalog_airlines(db)" in airlines


def test_seletor_de_horario_conta_opcao_so_com_data():
    picker = (ROOT / "app/templates/partials/flight_choice_picker.html").read_text(encoding="utf-8")
    assert "f.get('departure_date')" in picker
