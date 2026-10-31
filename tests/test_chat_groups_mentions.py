"""Grupos criados no chat, menções com @ e encaminhamento de cotação (sem Neon)."""
import asyncio

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models import (ChatGroupMember, ChatGroupMessage, ChatMessage, UserChatContact, WebCompany,
                        Notification, WebQuote, WebUser)
from app.routers import company


def _db():
    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    return Session(engine)


def _users(db):
    db.add_all([WebCompany(id=1, name='ISI'), WebCompany(id=2, name='Outra')]); db.flush()
    users = [
        WebUser(id=1, name='Ana Lima', email='a@t.invalid', password_hash='x', company_id=1, contact_id='DBM-000001'),
        WebUser(id=2, name='Beto Souza', email='b@t.invalid', password_hash='x', company_id=1, contact_id='DBM-000002'),
        WebUser(id=3, name='Carla Dias', email='c@t.invalid', password_hash='x', company_id=1, contact_id='DBM-000003'),
        WebUser(id=4, name='Estranho', email='d@t.invalid', password_hash='x', company_id=2, contact_id='DBM-000004'),
    ]
    db.add_all(users); db.flush()
    return users


def _as(monkeypatch, user, payload=None):
    monkeypatch.setattr(company, 'current_user', lambda req, db: user)
    async def csrf(req):
        return dict(payload or {}), None
    monkeypatch.setattr(company, '_json_with_csrf', csrf)


def test_criar_grupo_so_com_pessoas_permitidas(monkeypatch):
    company._CHAT_SCHEMA_READY = False
    with _db() as db:
        ana, beto, carla, estranho = _users(db)
        _as(monkeypatch, ana, {'name': 'Emissões', 'members': ['DBM-000002', 'DBM-000004']})
        result = asyncio.run(company.chat_group_create_api(object(), db))
        assert result['ok'] is True
        gid = result['group']['id']
        ids = {m.user_id for m in db.scalars(select(ChatGroupMember).where(ChatGroupMember.group_id == gid))}
        # Pessoa de outra empresa e fora da agenda não entra.
        assert ids == {1, 2}
        admin = db.scalar(select(ChatGroupMember).where(ChatGroupMember.group_id == gid, ChatGroupMember.user_id == 1))
        assert admin.is_admin is True
        # Quem não participa não lê.
        monkeypatch.setattr(company, 'current_user', lambda req, db: carla)
        resp = company.chat_group_messages_api(gid, object(), db=db)
        assert resp.status_code == 404


def test_mencao_notifica_e_conta_nao_lidas(monkeypatch):
    company._CHAT_SCHEMA_READY = False
    with _db() as db:
        ana, beto, carla, _ = _users(db)
        _as(monkeypatch, ana, {'name': 'Time', 'members': ['DBM-000002', 'DBM-000003']})
        gid = asyncio.run(company.chat_group_create_api(object(), db))['group']['id']
        _as(monkeypatch, ana, {'message': 'Oi @Beto Souza, confere a cotação?'})
        sent = asyncio.run(company.chat_group_send_api(gid, object(), db))
        assert sent['ok'] is True
        titles = {n.user_id: n.title for n in db.scalars(select(Notification).where(Notification.title.like('%mencionou%')))}
        assert 2 in titles and 3 not in titles
        # Beto vê 2 não lidas (criação + mensagem) até abrir o grupo.
        groups = company._chat_group_summaries(db, beto)
        assert groups[0]['unread'] == 2
        monkeypatch.setattr(company, 'current_user', lambda req, db: beto)
        data = company.chat_group_messages_api(gid, object(), db=db)
        assert [m['message'] for m in data['messages']][-1].startswith('Oi @Beto')
        assert {p['name'] for p in data['members']} == {'Ana Lima', 'Beto Souza', 'Carla Dias'}
        assert company._chat_group_summaries(db, beto)[0]['unread'] == 0


def test_mencao_no_chat_da_equipe_e_todos(monkeypatch):
    with _db() as db:
        ana, beto, carla, _ = _users(db)
        found, everyone = company._mentions('@carla dias pode ver?', [beto, carla], ana.id)
        assert found == {3} and everyone is False
        assert company._mentions('Atenção @todos', [beto, carla], ana.id)[1] is True
        db.add(ChatMessage(company_id=1, user_id=1, message='@Beto Souza olha isso')); db.flush()
        company._notify_group(db, ana, '@Beto Souza olha isso'); db.flush()
        rows = {n.user_id: n.title for n in db.scalars(select(Notification))}
        assert 'mencionou' in rows[2] and 'mencionou' not in rows[3]


def test_encaminhar_cotacao_para_grupo_com_texto(monkeypatch):
    company._CHAT_SCHEMA_READY = False
    with _db() as db:
        ana, beto, *_ = _users(db)
        db.add(WebQuote(id=50, user_id=1, company_id=1, quote_name='Lays', origin='GRU', destination='THE',
                        passengers=5, total=1000)); db.flush()
        _as(monkeypatch, ana, {'name': 'Vendas', 'members': ['DBM-000002']})
        gid = asyncio.run(company.chat_group_create_api(object(), db))['group']['id']
        _as(monkeypatch, ana, {'quote_id': 50, 'target': f'grp-{gid}', 'message': '💰 Por: R$ *7.698,90*'})
        result = asyncio.run(company.chat_quote_forward_api(object(), db))
        assert result['ok'] is True
        last = db.scalars(select(ChatGroupMessage).where(ChatGroupMessage.group_id == gid).order_by(ChatGroupMessage.id.desc())).first()
        assert 'R$ *7.698,90*' in last.message and '/calculations/result/50' in last.message
        # Encaminhar para grupo do qual não participa é recusado.
        targets, problem = company._forward_targets(db, db.get(WebUser, 4), [f'grp-{gid}'])
        assert targets == [] and problem


def test_chave_de_mensagem_de_grupo_criado():
    assert company._parse_message_keys(['c-7', 'g-1', 'p-2', 'x-3']) == [('cgroup', 7), ('group', 1), ('private', 2)]


def test_lista_de_destinatarios_tem_equipe_grupos_e_agenda(monkeypatch):
    company._CHAT_SCHEMA_READY = False
    with _db() as db:
        ana, beto, carla, estranho = _users(db)
        db.add(UserChatContact(owner_user_id=1, contact_user_id=4)); db.flush()
        _as(monkeypatch, ana, {'name': 'G1', 'members': ['DBM-000003']})
        asyncio.run(company.chat_group_create_api(object(), db))
        data = company.chat_targets_api(object(), db=db)
        assert data['team']['target'] == 'group'
        assert [g['name'] for g in data['groups']] == ['G1']
        assert {p['contact_id'] for p in data['people']} == {'DBM-000002', 'DBM-000003', 'DBM-000004'}
