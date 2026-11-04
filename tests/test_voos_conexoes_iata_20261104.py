"""Voos diretos/conexões, aeroportos por opção (códigos IATA) e bloco visual do trecho."""
import json

from app.routers.calculations import _flight_view, _history_segment_rows, _normalize_flight_details, _duration_minutes_value
from app.services.travel_data import IATA_CITY_GROUPS, AIRPORTS, airport_city_label
from app.database import SessionLocal
from app.models import QuoteOptionIndex, WebQuote
from test_security import started_app, make_company, make_user, make_group, logged

SEG = [{"key": "outbound", "origin": "SAO", "destination": "FOR"}]


def test_grupos_iata_e_codigos():
    groups = {g["key"]: [a["code"] for a in g["airports"]] for g in IATA_CITY_GROUPS}
    assert groups["NYC"] == ["JFK", "LGA", "EWR"]
    assert groups["SAO"] == ["GRU", "CGH", "VCP"]
    assert groups["LON"] == ["LHR", "LGW", "STN", "LTN", "LCY", "SEN"]
    assert groups["PAR"] == ["CDG", "ORY", "BVA"]
    assert groups["ROM"] == ["FCO", "CIA"]
    assert groups["PT"] == ["OPO", "LIS", "FAO", "BYJ", "CAT", "BGC"]
    # Portugal é só agrupamento: POR não é código IATA.
    assert next(g for g in IATA_CITY_GROUPS if g["key"] == "PT")["code"] == ""
    assert "POR" not in AIRPORTS
    assert airport_city_label("GRU") == "São Paulo (Guarulhos)"
    assert airport_city_label("SAO") == "São Paulo"
    assert airport_city_label("FOR") == "Fortaleza"


def test_duracao_digitada():
    assert _duration_minutes_value("7h52") == 472
    assert _duration_minutes_value("1h28min") == 88
    assert _duration_minutes_value("7:52") == 472
    assert _duration_minutes_value("45min") == 45
    assert _duration_minutes_value("abc") is None
    assert _duration_minutes_value("") is None


def test_aeroporto_por_opcao_conexoes_e_esperas_digitadas():
    raw = [{"segment_key": "outbound", "origin_airport": "VCP", "departure_date": "2026-11-23",
            "departure_time": "06:00", "arrival_date": "2026-11-23", "arrival_time": "16:23",
            "stops": ["GIG", "REC"], "stop_waits": ["1h02", "2h55"], "duration_manual": "10h23"}]
    out = _normalize_flight_details(raw, SEG, "one_way")[0]
    assert out["origin"] == "VCP" and out["destination"] == "FOR"
    assert out["route_origin"] == "SAO"
    assert out["stops"] == ["GIG", "REC"] and out["is_direct"] is False
    assert out["wait_minutes"] == [62, 175]
    # VCP e FOR têm fuso conhecido (-03): duração calculada pelos horários.
    assert out["duration_minutes"] == 10 * 60 + 23


def test_somente_aeroporto_sem_horario_e_direto():
    out = _normalize_flight_details([{"segment_key": "outbound", "origin_airport": "GRU"}], SEG, "one_way")[0]
    assert out["origin"] == "GRU" and out["is_direct"] is True and out["departure_time"] == ""


def test_cotacao_antiga_sem_conexao_e_voo_direto_sem_horarios_ficticios():
    rows = _history_segment_rows(SEG, [], "2026-11-23")
    flight = rows[0]["flight"]
    assert flight["is_direct"] is True and flight["stops"] == []
    assert flight["departure_time"] == "" and flight["arrival_time"] == "" and flight["duration_minutes"] is None
    assert flight["origin"] == "SAO" and flight["destination"] == "FOR"
    view = _flight_view({"departure_date": "2026-11-23", "arrival_date": "2026-11-24", "departure_time": "23:11", "arrival_time": "00:55"}, "GRU", "FOR", "")
    assert view["day_offset"] == 1


def test_bloco_visual_nas_opcoes_salvas_e_historico(started_app):
    comp = make_company("Voos IATA 20261104")
    uid = make_user("voos-iata-20261104@example.com", company_id=comp, role="admin", owner=True)
    gid = make_group(uid, comp, "Voos IATA")
    scope = {"key": "outbound", "segments": [{"key": "outbound", "origin": "SAO", "destination": "FOR", "departure_date": "2026-11-23"}]}
    details = [{"segment_key": "outbound", "origin_airport": "GRU", "departure_date": "2026-11-23", "departure_time": "08:00",
                "arrival_date": "2026-11-23", "arrival_time": "15:52", "stops": ["BSB"], "stop_waits": ["1h28"]}]
    with SessionLocal() as db:
        q = WebQuote(user_id=uid, company_id=comp, quote_name="Voos IATA", origin="SAO", destination="FOR", total=1340.12, bags=1,
                     input_json=json.dumps({"_scope": scope, "_flight_details": details}), breakdown_json="{}")
        old = WebQuote(user_id=uid, company_id=comp, quote_name="Voos IATA", origin="SAO", destination="FOR", total=999.0,
                       input_json=json.dumps({"_scope": scope}), breakdown_json="{}")
        db.add_all([q, old]); db.flush()
        db.add_all([QuoteOptionIndex(quote_id=q.id, group_id=gid), QuoteOptionIndex(quote_id=old.id, group_id=gid)]); db.commit()
    client = logged(started_app, "voos-iata-20261104@example.com")
    for url in (f"/calculations/group/{gid}", "/calculations/history"):
        page = client.get(url)
        assert page.status_code == 200 and "Não foi possível abrir" not in page.text
        assert "dbm-route-row" in page.text
        assert "Com conexão" in page.text and "1h28 de espera" in page.text and "7h52" in page.text
        assert "São Paulo (Guarulhos)" in page.text
        assert "Voo direto" in page.text  # cotação antiga sem conexão
        assert "bagagem(ns)" in page.text  # bagagens continuam no lugar
