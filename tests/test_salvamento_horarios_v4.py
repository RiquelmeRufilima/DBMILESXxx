"""Smoke test: salva e reabre a opção no SQLite de testes (nunca no Neon)."""
from __future__ import annotations
import json
import re
from sqlalchemy import select
from app.database import SessionLocal
from app.models import Airline, QuoteGroup, QuoteOptionIndex, WebQuote
from test_security import started_app, make_company, make_user, make_group, logged, csrf_from


def test_salvar_permanecer_e_salvar_fechar(started_app):
    company = make_company('Empresa Salvar Horários 4')
    make_user('salvar-horarios-v4@example.com', company_id=company, role='admin', owner=True)
    client = logged(started_app, 'salvar-horarios-v4@example.com')
    with SessionLocal() as db:
        user = db.scalar(select(__import__('app.models',fromlist=['WebUser']).WebUser).where(__import__('app.models',fromlist=['WebUser']).WebUser.email=='salvar-horarios-v4@example.com'))
        group_id=make_group(user.id, company, 'Alternativas de teste')
        airline = db.scalar(select(Airline).where(Airline.active.is_(True),Airline.builtin.is_(True)))
        assert airline, 'Companhia original não carregada no SQLite'
        calc_type=next((t for t in airline.calculation_types if t.active),None)
        assert calc_type, 'Tipo de cálculo não carregado'
        airline_id,type_id=airline.id,calc_type.id
    url=f'/calculations/new?group_id={group_id}&airline_id={airline_id}&type_id={type_id}&calc=1'
    page=client.get(url)
    assert page.status_code == 200 and 'Não foi possível abrir esta tela' not in page.text, page.text[:400]
    csrf=csrf_from(page.text)
    form={'csrf_token':csrf,'group_id':str(group_id),'airline_id':str(airline_id),'calculation_type_id':str(type_id),
          'scope_key':'one_way','variant_key':'primary','save_destination':'stay','bags_override':'0',
          'itinerary_json':json.dumps({'sides':[]}), 'flight_details_touched':'1',
          'flight_details_json':json.dumps([{'segment_key':'one_way','departure_date':'2026-12-01','departure_time':'08:20','preferred':True}, {'segment_key':'one_way','stops':['BSB'],'legs':[{'departure':'2026-12-01T09:00','arrival':'2026-12-01T10:00','origin_tz':'-03:00','destination_tz':'-03:00'},{'departure':'2026-12-01T11:00','arrival':'2026-12-01T12:00','origin_tz':'-03:00','destination_tz':'-03:00'}]}])}
    # Preenche campos de cálculo dinâmicos exigidos pelo próprio banco de teste
    with SessionLocal() as db:
        from app.routers.calculations import _effective_calculation_fields
        ct=db.get(__import__('app.models',fromlist=['CalculationType']).CalculationType,type_id)
        for field in _effective_calculation_fields(db,ct):
            key='field_'+field.key
            if field.field_type=='select':
                choices=json.loads(field.options_json or '[]')
                form[key]=str(choices[0] if choices else field.default_value or '0')
            else:
                form[key]=str(field.default_value or '1') if field.key!='milhas' else '1'
    saved=client.post('/calculations/calculate',data=form)
    assert saved.status_code==303, saved.text[:500]
    loc=saved.headers['location']; assert 'edit_id=' in loc and 'saved=1' in loc,loc
    reopened=client.get(loc)
    assert reopened.status_code==200 and 'Não foi possível abrir esta tela' not in reopened.text,reopened.text[:300]
    with SessionLocal() as db:
        option=db.scalar(select(WebQuote).join(QuoteOptionIndex,QuoteOptionIndex.quote_id==WebQuote.id).where(QuoteOptionIndex.group_id==group_id))
        assert option is not None
        stored=json.loads(option.input_json)
        assert len(stored.get('_flight_details') or []) == 2
        option_id=option.id
    form['option_id']=str(option_id)
    form['save_destination']='close'
    csrf=csrf_from(reopened.text)
    form['csrf_token']=csrf
    closed=client.post('/calculations/calculate',data=form)
    assert closed.status_code==303 and closed.headers['location']==f'/calculations/group/{group_id}'
