"""Smoke tests: radio de alternativas salvo, acesso isolado e integridade dos dados.
Todos os testes rodam apenas em SQLite temporário conforme tests/conftest.py.
"""
import json
from sqlalchemy import select
from app.database import SessionLocal
from app.models import QuoteGroup, QuoteOptionIndex, WebQuote, WebUser
from test_security import started_app, make_company, make_user, make_group, logged, csrf_from


def test_selecao_visual_em_opcoes_e_historico_preserva_dados(started_app):
    comp = make_company('V5 escolha visual por sentido')
    uid = make_user('flight-selector-v5@example.com', company_id=comp, role='admin', owner=True)
    group_id = make_group(uid, comp, 'V5 voos mesma companhia')
    data = {
        '_scope': {'key': 'round_trip', 'segments': [
            {'key': 'outbound', 'origin': 'FOR', 'destination': 'GRU'},
            {'key': 'return', 'origin': 'GRU', 'destination': 'FOR'}]},
        '_flight_details': [
            {'segment_key':'outbound','departure_date':'2026-11-16','departure_time':'08:20','arrival_date':'2026-11-16','arrival_time':'11:50','preferred':True,'stops':[]},
            {'segment_key':'outbound','departure_date':'2026-11-16','departure_time':'16:45','arrival_date':'2026-11-17','arrival_time':'01:00','stops':['BSB'],'preferred':False,'custom_legacy_field':'PRESERVAR',
             'legs':[{'departure':'2026-11-16T16:45','arrival':'2026-11-16T18:00','origin_tz':'-03:00','destination_tz':'-03:00'},
                     {'departure':'2026-11-16T19:25','arrival':'2026-11-17T01:00','origin_tz':'-03:00','destination_tz':'-03:00'}]},
            {'segment_key':'return','departure_date':'2026-11-20','departure_time':'12:00','arrival_date':'2026-11-20','arrival_time':'15:20','preferred':True},
        ],
        '_financial_legacy': {'miles': 1200, 'profit': None},
        'custom_unknown': 'PRESERVAR'
    }
    with SessionLocal() as db:
        q=WebQuote(user_id=uid,company_id=comp,quote_name='V5 voos mesma companhia',origin='FOR',destination='GRU',passengers=2,bags=1,total=549.00,input_json=json.dumps(data),breakdown_json='{}')
        db.add(q);db.flush()
        db.add(QuoteOptionIndex(quote_id=q.id,group_id=group_id,position=0));db.commit();quote_id=q.id
    client=logged(started_app,'flight-selector-v5@example.com')
    group=client.get(f'/calculations/group/{group_id}')
    assert group.status_code==200 and 'Não foi possível abrir esta tela' not in group.text
    assert 'dbm-flight-picker' in group.text
    assert '16:45' in group.text and 'BSB' in group.text
    history=client.get('/calculations/history')
    assert history.status_code==200 and 'Não foi possível abrir esta tela' not in history.text
    assert 'dbm-flight-picker' in history.text
    # Bloqueia CSRF antes de modificar qualquer preferência.
    invalid=client.post(f'/calculations/option/{quote_id}/flight-choice',data={'csrf_token':'invalido','option_index':'1','segment_key':'outbound'})
    assert invalid.status_code==403
    token=csrf_from(group.text)
    saved=client.post(f'/calculations/option/{quote_id}/flight-choice',data={'csrf_token':token,'option_index':'1','segment_key':'outbound'})
    assert saved.status_code==200,saved.text[:300]
    assert saved.json()['ok']
    with SessionLocal() as db:
        quote=db.get(WebQuote,quote_id)
        updated=json.loads(quote.input_json)
        assert quote.total==549.00 and quote.bags==1
        assert updated['_financial_legacy']==data['_financial_legacy']
        assert updated['custom_unknown']=='PRESERVAR'
        assert updated['_flight_details'][1]['custom_legacy_field']=='PRESERVAR'
        assert updated['_flight_details'][0]['preferred'] is False
        assert updated['_flight_details'][1]['preferred'] is True
        assert updated['_flight_details'][2]['preferred'] is True  # volta independente
        assert updated['_flight_details'][1]['stops']==['BSB']
    again=client.get(f'/calculations/group/{group_id}')
    assert again.status_code==200
    assert 'Escolha o horário' in again.text and 'Selecionada' in again.text and 'BSB · 1h25 de espera' in again.text
    bad=client.post(f'/calculations/option/{quote_id}/flight-choice',data={'csrf_token':token,'option_index':'55','segment_key':'outbound'})
    assert bad.status_code==422
    stranger_comp=make_company('V5 outra empresa')
    make_user('flight-selector-other-v5@example.com',company_id=stranger_comp,role='admin',owner=True)
    stranger=logged(started_app,'flight-selector-other-v5@example.com')
    other_token=csrf_from(stranger.get('/calculations/history').text)
    denied=stranger.post(f'/calculations/option/{quote_id}/flight-choice',data={'csrf_token':other_token,'option_index':'0','segment_key':'outbound'})
    assert denied.status_code==404


def test_historico_sem_alternativas_nao_quebra(started_app):
    comp=make_company('V5 sem alternativas')
    uid=make_user('flight-selector-empty-v5@example.com',company_id=comp,role='admin',owner=True)
    gid=make_group(uid,comp,'V5 cotacao antiga sem horarios')
    with SessionLocal() as db:
        q=WebQuote(user_id=uid,company_id=comp,quote_name='V5 cotacao antiga sem horarios',origin='FOR',destination='REC',total=42.0,input_json='{}',breakdown_json='{}')
        db.add(q);db.flush();db.add(QuoteOptionIndex(quote_id=q.id,group_id=gid));db.commit()
    client=logged(started_app,'flight-selector-empty-v5@example.com')
    assert client.get(f'/calculations/group/{gid}').status_code==200
    assert client.get('/calculations/history').status_code==200


def test_botoes_da_cotacao_manual_salvar_e_fechar_mantidos(monkeypatch):
    import asyncio
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.database import Base
    from app.models import AcceptedQuote, QuoteGroup, WebCompany, WebUser
    from app.routers import cadastros
    from pathlib import Path

    # Garante que o conserto de horários não transferiu esses botões para a calculadora.
    editor = (Path(__file__).resolve().parents[1] / 'app/templates/cadastros/cotacao_form.html').read_text()
    assert 'name="save_close" value="1"' in editor
    assert '<button class="secondary-button" type="submit">Salvar</button>' in editor
    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)

    class RequestStub:
        def __init__(self, form):
            self.session={'flashes': []}
            self._form=form
        async def form(self):
            return self._form

    with Session(engine) as db:
        db.add(WebCompany(id=300, name='Salvar manual teste V5'))
        db.add(WebUser(id=301, name='Usuário', email='manual-v5@example.invalid', password_hash='x', company_id=300, role='admin'))
        db.add(QuoteGroup(id=302, user_id=301, company_id=300, quote_name='Cotação já aceita'))
        db.add(AcceptedQuote(group_id=302, user_id=301, company_id=300, extra_json=json.dumps({'title':'Antes','services':{'hotel':[{'name':'Hotel salvo'}]}})))
        db.commit()
        monkeypatch.setattr(cadastros,'require_user',lambda req,db: db.get(WebUser,301))
        monkeypatch.setattr(cadastros,'validate_csrf_token',lambda *a: True)
        base={'csrf_token':'ok','title':'Depois','adults':'1','children':'0','babies':'0','quote_code':'M0302'}
        saved=asyncio.run(cadastros.salvar_cotacao(302,RequestStub(base),db))
        assert saved.status_code==303 and saved.headers['location']=='/cadastros/cotacoes/302'
        closed=asyncio.run(cadastros.salvar_cotacao(302,RequestStub({**base,'save_close':'1'}),db))
        assert closed.status_code==303 and closed.headers['location']=='/cadastros/cotacoes'
        payload=json.loads(db.get(AcceptedQuote,302).extra_json)
        assert payload['services']['hotel'][0]['name']=='Hotel salvo'
