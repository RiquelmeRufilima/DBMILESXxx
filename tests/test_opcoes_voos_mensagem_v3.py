"""Regressões do painel de mensagens e alternativas da mesma cotação."""
from pathlib import Path
import re
import subprocess

from jinja2 import Environment

from app.routers.calculations import _normalize_flight_details, _flight_detail_chips


def _parts():
    return [{"key": "outbound", "origin": "FOR", "destination": "GRU"},
            {"key": "return", "origin": "GRU", "destination": "FOR"}]


def test_sem_horarios_ou_paradas_continua_opcional():
    assert _normalize_flight_details([], _parts(), "round_trip") == []
    assert _normalize_flight_details([{"segment_key": "outbound", "preferred": True}], _parts(), "round_trip") == []


def test_alternativas_com_mesma_companhia_tem_selecao_unica():
    rows = [{"segment_key": "outbound", "departure_date": "2026-11-12", "departure_time": "08:20"},
            {"segment_key": "outbound", "departure_date": "2026-11-12", "departure_time": "14:10", "preferred": True},
            {"segment_key": "return", "departure_date": "2026-11-20", "departure_time": "20:40"}]
    output = _normalize_flight_details(rows, _parts(), "round_trip")
    assert len(output) == 3
    assert [item['preferred'] for item in output] == [False, True, True]
    assert all('cost' not in item and 'fare' not in item for item in output)


def test_conexao_espera_duracao_e_virada_do_dia():
    raw=[{"segment_key":"outbound", "stops":["BSB"], "preferred":True, "legs":[
        {"departure":"2026-12-01T21:05","origin_tz":"-03:00","arrival":"2026-12-01T22:30","destination_tz":"-03:00"},
        {"departure":"2026-12-01T23:55","origin_tz":"-03:00","arrival":"2026-12-02T00:40","destination_tz":"-03:00"}]}]
    out = _normalize_flight_details(raw, _parts(), "round_trip")
    assert out[0]['stops'] == ['BSB']
    assert out[0]['duration_minutes'] == 215
    assert out[0]['wait_minutes'] == [85]
    assert out[0]['arrival_date'] == '2026-12-02'
    assert any('via BSB' in v for v in _flight_detail_chips(out))


def test_conexao_invalida_e_horarios_incompletos_nao_inventam_duracao():
    raw=[{"segment_key":"outbound", "stops":["FOR","?","BSB","BSB"], "legs":[
        {"departure":"2026-12-01T08:00", "arrival":"2026-12-01T09:30"},
        {"departure":"2026-12-01T11:00", "arrival":"2026-12-01T12:30"}]}]
    out=_normalize_flight_details(raw,_parts(),"round_trip")
    assert out[0]['stops']==['BSB']
    # Aeroportos brasileiros têm fuso fixo: FOR → BSB → GRU (todos -03:00) = 4h30.
    assert out[0]['duration_minutes'] == 270
    assert out[0]['wait_minutes'] == [90]
    # Internacional sem fuso informado: não inventa duração (horário de verão lá fora).
    intl=[{"key":"outbound","origin":"GRU","destination":"LIS"}]
    raw_intl=[{"segment_key":"outbound","stops":["MAD"],"legs":[
        {"departure":"2026-12-01T08:00","arrival":"2026-12-01T22:00"},
        {"departure":"2026-12-01T23:30","arrival":"2026-12-02T00:40"}]}]
    out_intl=_normalize_flight_details(raw_intl,intl,"one_way")
    assert out_intl[0]['duration_minutes'] is None
    assert out_intl[0]['wait_minutes'] == [90]  # espera usa horário local do mesmo aeroporto


def test_modo_claro_e_painel_compacto_preservados():
    tpl=Path('app/templates/calculations/result.html').read_text()
    css=Path('app/static/css/dbm-message-settings-20261103.css').read_text()
    assert 'id="dbmMessageSettings"' in tpl
    assert all(f'value="{value}"' in tpl for value in ['total','per_person','per_leg','per_person_leg'])
    assert all(f'id="{field}"' in tpl for field in ['dbmMessageShowTimes','dbmMessageShowFare','dbmMessageMaxInstallments'])
    assert 'html[data-theme="light"] #dbmMessageSettings' in css
    assert 'dbm-msg-row input[type="radio"]' in css
    assert 'Venda ao cliente' in tpl and 'quote.commercial.profit_value is not none' in tpl


def test_js_templates_compilam():
    for name in ('new','result','group'):
        template=Path('app/templates/calculations/'+name+'.html').read_text()
        Environment().parse(template)
        for script in re.findall(r'<script(?:\s[^>]*)?>(.*?)</script>',template,re.S | re.I):
            if not script.strip() or ('function rowHtml(detail,index,number)' not in script and 'availableFlightOptions=' not in script):
                continue
            script=re.sub(r'\{\{[\s\S]*?\}\}','null',script)
            script=re.sub(r'\{%[\s\S]*?%\}','',script)
            r=subprocess.run(['node','--check','-'],input=script,text=True,capture_output=True)
            assert r.returncode==0, r.stderr
