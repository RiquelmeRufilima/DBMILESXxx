"""Regressão: perfil aparece em conversas privadas entre empresas diferentes."""
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import PrivateChatMessage, UserChatContact, UserProfile, WebCompany, WebUser
from app.routers import profile
from app.services.realtime import avatar_url


def make_db():
    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.add_all([WebCompany(id=101, name='ISI'), WebCompany(id=102, name='Parceiro')])
    for uid, company in ((11, 101), (22, 102), (33, 102)):
        db.add(WebUser(id=uid, company_id=company, name=f'Pessoa {uid}', email=f'{uid}@local.invalid', password_hash='x', active=True))
        db.add(UserProfile(user_id=uid))
    db.commit()
    return db


def test_recebedor_de_mensagem_ve_foto_sem_agenda(monkeypatch):
    with make_db() as db:
        me, other = db.get(WebUser, 11), db.get(WebUser, 22)
        first = 'https://store.private.blob.vercel-storage.com/users/11/avatars/antes.jpg'
        me.profile.avatar_path = profile._blob_avatar_route(11, first)
        db.add(PrivateChatMessage(sender_id=11, recipient_id=22, message='Olá', company_id=101))
        db.commit()
        assert db.query(UserChatContact).count() == 0
        monkeypatch.setattr(profile, 'current_user', lambda req, db_: other)
        accessed = []
        monkeypatch.setattr(profile, 'blob_get', lambda url: (accessed.append(url) or (b'img', 'image/jpeg')))
        response = profile.serve_current_avatar(11, object(), db)
        assert response.status_code == 200
        assert accessed == [first]
        assert avatar_url(me).startswith('/profile/avatar/11?v=')


def test_foto_nova_no_mesmo_endereco_e_antiga_invalida(monkeypatch):
    with make_db() as db:
        me, other = db.get(WebUser, 11), db.get(WebUser, 22)
        db.add(PrivateChatMessage(sender_id=22, recipient_id=11, message='Oi', company_id=102))
        old_url = 'https://store.private.blob.vercel-storage.com/users/11/avatars/old.jpg'
        new_url = 'https://store.private.blob.vercel-storage.com/users/11/avatars/new.jpg'
        me.profile.avatar_path = profile._blob_avatar_route(11, old_url)
        me.profile.updated_at = datetime(2026, 11, 8, 10, 0, 0)
        db.commit()
        old_front_url = avatar_url(me).split('?')[0]
        assert old_front_url == '/profile/avatar/11'
        me.profile.avatar_path = profile._blob_avatar_route(11, new_url)
        me.profile.updated_at = me.profile.updated_at + timedelta(minutes=1)
        db.commit()
        assert avatar_url(me).split('?')[0] == old_front_url
        monkeypatch.setattr(profile, 'current_user', lambda req, db_: other)
        downloaded = []
        monkeypatch.setattr(profile, 'blob_get', lambda url: (downloaded.append(url) or (b'new-photo', 'image/jpeg')))
        result = profile.serve_current_avatar(11, object(), db)
        assert result.status_code == 200 and result.body == b'new-photo'
        assert downloaded == [new_url]
        ref = profile._b64url_encode(old_url.encode('utf-8'))
        stale = asyncio.run(profile.serve_private_avatar(11, ref, object(), db))
        assert stale.status_code == 404


def test_perfil_privado_para_contato_sem_relacao(monkeypatch):
    with make_db() as db:
        me, stranger = db.get(WebUser, 11), db.get(WebUser, 33)
        url = 'https://store.private.blob.vercel-storage.com/users/11/avatars/real.jpg'
        me.profile.avatar_path = profile._blob_avatar_route(11, url)
        db.commit()
        monkeypatch.setattr(profile, 'current_user', lambda req, db_: stranger)
        monkeypatch.setattr(profile, 'blob_get', lambda url: (_ for _ in ()).throw(AssertionError('not authorized')))
        result = profile.serve_current_avatar(11, object(), db)
        assert result.status_code == 403


def test_vinculo_ja_salvo_em_qualquer_direcao_autoriza(monkeypatch):
    with make_db() as db:
        a,b = db.get(WebUser,11),db.get(WebUser,22)
        db.add(UserChatContact(owner_user_id=a.id,contact_user_id=b.id))
        db.commit()
        assert profile._can_view_avatar(db, b, a)
        assert profile._can_view_avatar(db, a, b)


def test_avisos_de_chat_usa_endereco_estavel_e_nao_recria_avatar_periodicamente():
    root = Path(__file__).resolve().parents[1]
    chat=(root/'app/static/js/chat.js').read_text()
    assert 'holder.dataset.renderSignature !== signature' in chat
    assert 'item.avatar_url' in chat
    assert (root/'app/web.py').read_text().count('templates.env.globals["avatar_url"]') == 1
