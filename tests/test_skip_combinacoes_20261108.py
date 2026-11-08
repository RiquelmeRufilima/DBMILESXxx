"""Regras de Skip por direção, combinações e privacidade da mensagem do cliente."""
from pathlib import Path
import re
import subprocess

from jinja2 import Environment

from app.routers.calculations import _calculation_scopes, _history_segment_rows

ROOT = Path(__file__).resolve().parents[1]


def test_skip_normal_da_volta_usa_for_gru_com_destino_nao_voado_editavel():
    base = {"origin": "GRU", "destination": "FOR", "travel_type": "round_trip",
            "departure_date": "2026-11-12", "return_date": "2026-11-27"}
    scopes = {item["key"]: item for item in _calculation_scopes(base)}
    ida = scopes["skip_normal"]
    volta = scopes["skip_normal_return"]
    assert ida["skip_mode"] == volta["skip_mode"] == "normal"
    assert ida["segments"][0]["origin"] == "GRU"
    assert ida["segments"][0]["destination"] == "FOR"
    assert volta["skip_direction"] == "return"
    assert volta["flown_segment"] == 1
    assert volta["segments"][0]["origin"] == "FOR"
    assert volta["segments"][0]["destination"] == "GRU"
    assert volta["segments"][1]["origin"] == "GRU"
    assert volta["segments"][1]["destination"] == ""
    assert volta["segments"][0]["date"] == "2026-11-27"
    assert scopes["skip_inverse_return"]["flown_segment"] == 2


def test_skip_multitrecho_permite_escolher_qual_perna_e_voada():
    base = {"travel_type": "multi_city", "origin": "GRU", "destination": "FOR", "segments": [
        {"origin": "GRU", "destination": "FOR", "date": "2026-11-12"},
        {"origin": "FOR", "destination": "REC", "date": "2026-11-16"},
        {"origin": "REC", "destination": "GRU", "date": "2026-11-25"},
    ]}
    scopes = {item["key"]: item for item in _calculation_scopes(base)}
    for index, (orig, dest) in enumerate((("GRU", "FOR"), ("FOR", "REC"), ("REC", "GRU")), 1):
        normal = scopes[f"skip_normal_segment_{index}"]
        inverse = scopes[f"skip_inverse_segment_{index}"]
        assert (normal["segments"][0]["origin"], normal["segments"][0]["destination"]) == (orig, dest)
        assert (inverse["segments"][1]["origin"], inverse["segments"][1]["destination"]) == (orig, dest)
        assert normal["skip_direction"] == f"segment_{index}"
        assert inverse["skip_direction"] == f"segment_{index}"


def test_status_de_skipe_combinado_permanece_no_historico_operacional():
    rows = _history_segment_rows([
        {"key": "combined_1_1", "origin": "GRU", "destination": "FOR", "status": "flown"},
        {"key": "combined_1_2", "origin": "FOR", "destination": "LIS", "status": "not_flown", "date": "2026-11-13"},
        {"key": "combined_2_1", "origin": "FOR", "destination": "GRU", "status": "flown"},
        {"key": "combined_2_2", "origin": "GRU", "destination": "REC", "status": "not_flown"},
    ], [
        {"segment_key": "combined_1_1", "departure_date": "2026-11-12", "departure_time": "10:00"},
        {"segment_key": "combined_2_1", "departure_date": "2026-11-27", "departure_time": "15:00"},
    ])
    assert [item["status"] for item in rows] == ["flown", "not_flown", "flown", "not_flown"]
    assert [item["route"] for item in rows] == ["GRU → FOR", "FOR → LIS", "FOR → GRU", "GRU → REC"]
    assert not rows[1]["schedules"] and not rows[3]["schedules"]
    assert rows[0]["schedules"] and rows[2]["schedules"]


def test_mensagem_cliente_filtra_nao_voados_e_mostra_multitrecho_diferente():
    result = (ROOT / "app/templates/calculations/result.html").read_text(encoding="utf8")
    assert "visibleSegments =" in result
    assert "row.status!=='not_flown'" in result
    assert "clientTravelType==='multi_city'" in result
    assert "visibleSegments.slice(0,1)" in result
    assert "if(skipRecord){addOperationalSegments();}" in result
    assert "else if(hasSkipComponents || combinedRecord){addOperationalSegments();}" in result


def test_opcoes_salvas_oferecem_combinacao_entre_subcotacoes_e_duplicacao_multipla():
    page = (ROOT / "app/templates/calculations/group.html").read_text(encoding="utf8")
    backend = (ROOT / "app/routers/calculations.py").read_text(encoding="utf8")
    assert 'id="groupCombineForm"' in page
    assert 'form="groupCombineForm"' in page
    assert 'name="target_variant_key"' in page
    assert 'name="target_variant_keys"' in page
    assert 'form.getlist("target_variant_keys")' in backend
    assert 'source_variant_key' in backend
    assert '"source_quote_id": int(item.id)' in backend
    for path in ("new.html", "result.html", "group.html", "history.html"):
        Environment().parse((ROOT / "app/templates/calculations" / path).read_text(encoding="utf8"))


def test_javascript_da_tela_de_combinacao_tem_sintaxe_valida():
    page = (ROOT / "app/templates/calculations/group.html").read_text(encoding="utf8")
    js = re.search(r'<script>\s*\(\(\)=>\{\s*const form=document.getElementById\(\'groupCombineForm\'\).*?</script>', page, re.S)
    assert js
    proc = subprocess.run(["node", "--check", "-"], input=js.group(0)[8:-9], text=True, capture_output=True)
    assert proc.returncode == 0, proc.stderr
