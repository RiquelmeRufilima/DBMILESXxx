"""Testes sem Neon para o acompanhamento e edição de mensagens."""
import asyncio
import json
from types import SimpleNamespace
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.database import Base
from app.models import WebCompany, WebUser, QuoteGroup, AcceptedQuote, ChatMessage
from app.routers import company, service_tracking


def _db():
    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    return Session(engine)


def _users(db):
    db.add_all([WebCompany(id=1, name='Empresa A'), WebCompany(id=2, name='Empresa B')]); db.flush()
    users=[WebUser(id=1, name='Ana', email='a@test.invalid', password_hash='test', company_id=1),
           WebUser(id=2, name='Beto', email='b@test.invalid', password_hash='test', company_id=1),
           WebUser(id=3, name='Carlos', email='c@test.invalid', password_hash='test', company_id=2)]
    db.add_all(users);db.flush();return users


def test_tracking_isolated_by_company():
    with _db() as db:
        a,b,c=_users(db)
        db.add_all([QuoteGroup(id=10,user_id=1,company_id=1,quote_name='A'),QuoteGroup(id=20,user_id=3,company_id=2,quote_name='B')]);db.flush()
        for id, user in ((10,a),(20,c)):
            db.add(AcceptedQuote(group_id=id, user_id=user.id,company_id=user.company_id,extra_json=json.dumps({'services':{'hotel':[{'hotel':'Test Hotel'}]}})))
        db.flush()
        assert len(db.scalars(select(AcceptedQuote).where(service_tracking._visible_filter(a))).all()) == 1
        assert len(db.scalars(select(AcceptedQuote).where(service_tracking._visible_filter(b))).all()) == 1
        assert len(db.scalars(select(AcceptedQuote).where(service_tracking._visible_filter(c))).all()) == 1
        assert service_tracking._list_services({'services':{'hotel':[{'name':'Hotel'}]}},'hotel') == [{'name':'Hotel'}]
        assert service_tracking._list_services({'services':{'hotel': 'invalid'}},'hotel') == []


def test_edit_message_author_only_and_company_isolation(monkeypatch):
    with _db() as db:
        a,b,c=_users(db)
        db.add(ChatMessage(id=100,company_id=1,user_id=1,message='Texto anterior'));db.flush()
        async def csrf(req): return {'message': 'Novo texto'}, None
        monkeypatch.setattr(company,'_json_with_csrf',csrf)
        monkeypatch.setattr(company,'current_user',lambda req,db: b)
        response=asyncio.run(company.chat_edit_message_api('g-100',object(),db))
        assert response.status_code == 403
        monkeypatch.setattr(company,'current_user',lambda req,db: c)
        response=asyncio.run(company.chat_edit_message_api('g-100',object(),db))
        assert response.status_code == 404
        monkeypatch.setattr(company,'current_user',lambda req,db: a)
        result=asyncio.run(company.chat_edit_message_api('g-100',object(),db))
        assert result['ok'] is True
        assert db.get(ChatMessage,100).message == 'Novo texto'


def test_edit_rejects_empty_and_invalid_key(monkeypatch):
    with _db() as db:
        a,*_=_users(db)
        monkeypatch.setattr(company,'current_user',lambda req,db: a)
        async def csrf(req): return {'message': ''}, None
        monkeypatch.setattr(company,'_json_with_csrf',csrf)
        response=asyncio.run(company.chat_edit_message_api('malicioso',object(),db))
        assert response.status_code == 400
        db.add(ChatMessage(id=9, company_id=1, user_id=1, message='Oi'));db.flush()
        response=asyncio.run(company.chat_edit_message_api('g-9',object(),db))
        assert response.status_code == 400
