"""Testes isolados das melhorias de paginação e check-in."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta
import pytest
from sqlalchemy.exc import IntegrityError

_test_dir = tempfile.mkdtemp(prefix="dbm-progressive-")
os.environ["DATABASE_URL"] = f"sqlite:///{_test_dir}/db.sqlite"
os.environ["SECRET_KEY"] = "progressive-tests-local-only-very-long-secret"
os.environ["APP_ENV"] = "test"
os.environ["RUN_FULL_STARTUP_MAINTENANCE"] = "0"
os.environ["PERSISTENT_ROOT"] = _test_dir
os.environ.pop("VERCEL", None)

from starlette.requests import Request
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import (AcceptedQuote, ChatMessage, CheckinReminder, Notification,
                        Person, PrivateChatMessage, QuoteGroup, QuoteGroupTripDetail,
                        WebCompany, WebUser)
from app.services.checkin_reminders import BRAZIL_TZ, process_checkin_reminders
from app.routers.company import _private_messages, _private_conversation_summaries, messages_api
from app.routers.persons import person_list
from app.routers.calculations import history
from app.routers.notifications import notifications_page
from app.routers.auth import _account_for_email


def _request(user_id: int, path: str) -> Request:
    return Request({"type":"http", "http_version":"1.1", "scheme":"http", "server":("testserver",80),
                    "client":("127.0.0.1",1234), "method":"GET", "path":path,
                    "raw_path":path.encode(), "root_path":"", "query_string":b"", "headers":[],
                    "session":{"user_id":user_id,"auth_version":1}})


def test_progressive_persons_chat_and_checkin():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        company = WebCompany(name="Teste Progressivo")
        db.add(company); db.flush()
        user = WebUser(name="Usuário Teste", email="progressive@example.com", password_hash="invalid",
                       company_id=company.id, contact_id="DBM-900001", active=True)
        partner = WebUser(name="Parceiro", email="partner@example.com", password_hash="invalid",
                          company_id=company.id, contact_id="DBM-900002", active=True)
        db.add_all([user, partner]); db.flush()
        for i in range(25):
            db.add(Person(name=f"Pessoa {i:02d}", user_id=user.id, company_id=company.id, is_complete=True))
        for i in range(47):
            db.add(ChatMessage(user_id=user.id, company_id=company.id, message=f"Grupo {i}"))
            db.add(PrivateChatMessage(sender_id=user.id, recipient_id=partner.id, message=f"Privado {i}"))
        quote = QuoteGroup(user_id=user.id, company_id=company.id, quote_name="Viagem de teste")
        db.add(quote); db.flush()
        depart = datetime.now(BRAZIL_TZ) + timedelta(hours=30)
        trip = QuoteGroupTripDetail(group_id=quote.id, departure_date=depart.strftime("%Y-%m-%d"))
        db.add(trip)
        db.add(AcceptedQuote(group_id=quote.id, user_id=user.id, company_id=company.id,
                             extra_json=json.dumps({"flights": [{"departure_date": depart.strftime("%Y-%m-%d"),
                               "departure_time": depart.strftime("%H:%M"), "notification_mode": "notificar_48h"}]})))
        db.commit()
        uid = user.id

    with SessionLocal() as db:
        user = db.get(WebUser, uid)
        partner = db.scalar(__import__('sqlalchemy').select(WebUser).where(WebUser.email == 'partner@example.com'))
        page = person_list(_request(uid,'/persons'), q='', tag=[], offset=0, db=db)
        assert len(page.context['complete']) == 20 and page.context['has_more']
        next_page = person_list(_request(uid,'/persons'), q='', tag=[], offset=20, partial=True, db=db)
        assert len(next_page.context['complete']) == 5 and not next_page.context['has_more']
        group = messages_api(_request(uid,'/company/messages'), db=db)
        assert len(group['messages']) == 30 and group['has_more']
        older = messages_api(_request(uid,'/company/messages'), before_id=group['messages'][0]['id'], db=db)
        assert len(older['messages']) == 17 and not older['has_more']
        assert len(_private_messages(db, user, partner)) == 30
        assert len(_private_conversation_summaries(db,user)) == 1
        result = history(_request(uid,'/calculations/history'), tag=[], db=db)
        assert result.context['total_items'] == 1
        first = process_checkin_reminders(db)
        second = process_checkin_reminders(db)
        assert first['notifications_created'] == 1
        assert second['notifications_created'] == 0
        assert db.query(CheckinReminder).count() == 1
        assert db.query(Notification).count() == 1
        for i in range(25):
            db.add(Notification(user_id=uid, title=f'Aviso {i}', message='Teste'))
        db.commit()
        first_batch = notifications_page(_request(uid,'/notifications'), db=db)
        second_batch = notifications_page(_request(uid,'/notifications'), offset=20, partial=True, db=db)
        assert len(first_batch.context['notifications']) == 20 and first_batch.context['has_more']
        assert len(second_batch.context['notifications']) == 6 and not second_batch.context['has_more']


def test_case_insensitive_unique_email():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        db.add(WebUser(name='Conta única', email='Unique@example.com', password_hash='invalid'))
        db.commit()
        user, duplicated = _account_for_email(db, '  UNIQUE@EXAMPLE.COM  ')
        assert user is not None and not duplicated
        db.add(WebUser(name='Tentativa duplicada', email=' unique@example.COM ', password_hash='invalid'))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
