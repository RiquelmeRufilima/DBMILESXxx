"""Regressão: campos opcionais vazios não exibem/gravam 'None'."""
from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment

from app.routers.calculations import _base_from_group, _base_from_quote, _optional_client_text


ROOT = Path(__file__).resolve().parents[1]


def _trip(**values):
    values = {
        "client_person_id": None,
        "client_name": None,
        "client_email": None,
        "client_phone": None,
        "notes": None,
        "travel_type": "one_way",
        "departure_date": "2026-11-01",
        "return_date": None,
        "segments_json": "[]",
        "variants_json": "[]",
        "flexibility_days": 0,
        **values,
    }
    return SimpleNamespace(**values)


def _group(trip):
    return SimpleNamespace(
        id=10, quote_name="Junior", origin="NVT", destination="AJU",
        passengers=1, babies=0, bags=0, source_request_id=None, trip=trip,
    )


def test_group_edit_does_not_display_missing_client_values():
    base = _base_from_group(_group(_trip()))
    assert all(base[k] == "" for k in ("client_name", "client_email", "client_phone", "notes"))


def test_legacy_literal_none_is_suppressed_but_real_data_preserved():
    base = _base_from_group(_group(_trip(client_name="None", client_email=" null ", client_phone="undefined")))
    assert all(base[k] == "" for k in ("client_name", "client_email", "client_phone"))
    assert _optional_client_text(" cliente@exemplo.com ") == "cliente@exemplo.com"
    assert _optional_client_text("(85) 99999-0000") == "(85) 99999-0000"


def test_old_quote_edit_does_not_show_null():
    quote = SimpleNamespace(
        trip=_trip(), quote_name="Cotação teste", origin="FOR", destination="GRU",
        passengers=1, babies=0, bags=0,
    )
    base = _base_from_quote(quote)
    assert base["client_name"] == base["client_email"] == base["client_phone"] == ""


def test_optional_client_inputs_render_empty_with_none_values():
    source = (ROOT / "app/templates/calculations/new.html").read_text()
    env = Environment(autoescape=True)
    for key in ("client_name", "client_email", "client_phone"):
        assert f'name="{key}" value="{{{{ base.{key} or \'\' }}}}"' in source
        field = env.from_string('{{ base.' + key + " or '' }}")
        assert field.render(base={key: None}) == ""
    assert "{{ base.notes or '' }}" in source
