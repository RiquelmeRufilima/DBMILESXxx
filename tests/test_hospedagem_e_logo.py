"""Regressão: hospedagem nunca exige IATA e não perde os serviços no salvamento."""
import asyncio
import json
from types import SimpleNamespace
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.database import Base
from app.models import WebCompany, WebUser, QuoteGroup, AcceptedQuote
from app.routers import cadastros, airlines, service_tracking
from app.config import AIRLINE_IMAGE_DIR


class FakeRequest:
    def __init__(self, form):
        self.session = {'flashes': []}
        self._form = form
    async def form(self):
        return self._form


def test_salvar_hospedagem_sem_iata_e_sem_apagar_reserva(monkeypatch):
    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(WebCompany(id=1, name='Empresa A'))
        db.add(WebUser(id=1, name='Agente', email='a@teste.invalid', password_hash='x', company_id=1, role='admin'))
        db.add(QuoteGroup(id=110, user_id=1, company_id=1, quote_name='Everaldo'))
        saved = {'quote_code':'m0110','title':'Everaldo','services':{'hotel':[{'name':'Rede Andrade Mirante Hotel','address':'Foz do Iguaçu','start_date':'2026-11-03','end_date':'2026-11-05','reservation_number':'433455362800'}]},'flights':[], 'passengers':[], 'cost_items':[], 'sale_items':[]}
        db.add(AcceptedQuote(group_id=110,user_id=1,company_id=1,extra_json=json.dumps(saved)))
        db.commit()
        user=db.get(WebUser,1)
        monkeypatch.setattr(cadastros, 'require_user', lambda request, session: user)
        monkeypatch.setattr(cadastros, 'validate_csrf_token', lambda *args: True)
        req=FakeRequest({'csrf_token':'ok', 'title':'Everaldo', 'quote_code':'m0110','adults':'1', 'children':'0', 'babies':'0', 'save_close':'1'})
        response=asyncio.run(cadastros.salvar_cotacao(110,req,db))
        assert response.status_code == 303
        assert response.headers['location']=='/cadastros/cotacoes'
        stored=json.loads(db.get(AcceptedQuote,110).extra_json)
        assert stored['services']['hotel'][0]['reservation_number']=='433455362800'
        assert stored['services']['hotel'][0]['start_date']=='2026-11-03'
        assert stored['flights']==[]


def test_servico_preserva_cidade_sem_convertela_em_aeroporto(monkeypatch):
    engine=create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(WebCompany(id=1,name='Teste'))
        db.add(WebUser(id=1,name='Agente',email='user@teste.invalid',password_hash='x', company_id=1))
        db.add(QuoteGroup(id=12,user_id=1,company_id=1,quote_name='Hospedagem'))
        db.add(AcceptedQuote(group_id=12,user_id=1,company_id=1,extra_json='{}'))
        db.commit()
        monkeypatch.setattr(cadastros,'require_user',lambda req,session: db.get(WebUser,1))
        monkeypatch.setattr(cadastros,'validate_csrf_token',lambda *args: True)
        services={'hotel':[{'name':'Hotel','address':'Avenida República Argentina, Foz do Iguaçu','origin':'Foz do Iguaçu','destination':'Cascavel'}]}
        req=FakeRequest({'csrf_token':'ok','title':'Hospedagem','adults':'1','children':'0','babies':'0','services_json':json.dumps(services)})
        response=asyncio.run(cadastros.salvar_cotacao(12,req,db))
        assert response.status_code==303
        obj=json.loads(db.get(AcceptedQuote,12).extra_json)
        assert obj['services']['hotel'][0]['origin']=='Foz do Iguaçu'
        assert obj['services']['hotel'][0]['destination']=='Cascavel'


def test_logo_voepass_na_companhia_original():
    assert (AIRLINE_IMAGE_DIR/'voepass.png').is_file()
    original=SimpleNamespace(name='Voepass Linhas Aéreas', builtin=True, logo_path=None)
    assert airlines._catalog_logo(original)=='/imagens/voepass.png'
    customized=SimpleNamespace(name='Voepass',builtin=False,logo_path='uploads/airlines/meu-logo.png')
    assert airlines._catalog_logo(customized)=='/uploads/airlines/meu-logo.png'


def test_datas_legadas_de_hospedagem():
    s={'checkin':'2026-11-03','checkout':'2026-11-05'}
    assert service_tracking._service_val(s,'start_date','checkin')=='2026-11-03'
    assert service_tracking._service_val(s,'end_date','checkout')=='2026-11-05'
