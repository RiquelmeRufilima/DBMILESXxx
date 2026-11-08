"""Avatar persistente: substituição real, proteção do Blob e exibição no chat."""
import asyncio
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import ChatMessage, UserChatContact, UserProfile, WebCompany, WebUser
from app.routers import profile, company
from app.services.realtime import avatar_url


def session():
    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.add_all([WebCompany(id=1, name='ISI'), WebCompany(id=2, name='Externa')]); db.flush()
    for uid, cid in [(1, 1), (2, 1), (3, 2)]:
        db.add(WebUser(id=uid, company_id=cid, name=f'Usuário {uid}',
                       email=f'u{uid}@local.invalid', password_hash='x', active=True))
        db.add(UserProfile(user_id=uid));
    db.commit()
    return db


class Request:
    def __init__(self, values=None, content=b'', headers=None):
        self.session = {'flashes': []}
        self.values = values or {}
        self._content = content
        self.headers = headers or {}
    async def form(self): return self.values
    async def body(self): return self._content


def test_atualizar_foto_substitui_ponteiro_e_apaga_blob_antigo(monkeypatch):
    with session() as db:
        user = db.get(WebUser, 1)
        old = 'https://store.private.blob.vercel-storage.com/users/1/avatars/antiga.webp'
        new = 'https://store.private.blob.vercel-storage.com/users/1/avatars/nova.webp'
        user.profile.avatar_path = profile._blob_avatar_route(1, old)
        db.commit()
        deleted = []
        monkeypatch.setattr(profile, 'blob_delete', lambda url: deleted.append(url))
        monkeypatch.setattr(profile, 'current_user', lambda request, session: user)
        monkeypatch.setattr(profile, 'validate_csrf_token', lambda *args: True)
        monkeypatch.setattr(profile, 'flash', lambda *args: None)
        async def broadcast(*args): return None
        monkeypatch.setattr(profile.manager, 'broadcast', broadcast)
        request = Request({'csrf_token': 'csrf', 'name': 'Nome Novo', 'phone': '',
                           'avatar_blob_url': new})
        result = asyncio.run(profile.update_profile(request, None, db))
        assert result.status_code == 303
        assert db.get(WebUser, 1).profile.avatar_path == profile._blob_avatar_route(1, new)
        assert deleted == [old]
        assert '/users/1/avatars/nova' not in (deleted[0])


def test_alterar_dados_sem_imagem_preserva_foto(monkeypatch):
    with session() as db:
        user = db.get(WebUser, 1)
        path = 'profile/avatar-file/1/aaa'
        user.profile.avatar_path = path
        db.commit()
        deleted = []
        monkeypatch.setattr(profile, 'blob_delete', lambda url: deleted.append(url))
        monkeypatch.setattr(profile, 'current_user', lambda request, session: user)
        monkeypatch.setattr(profile, 'validate_csrf_token', lambda *args: True)
        monkeypatch.setattr(profile, 'flash', lambda *args: None)
        async def broadcast(*args): return None
        monkeypatch.setattr(profile.manager, 'broadcast', broadcast)
        asyncio.run(profile.update_profile(Request({'csrf_token': 'csrf', 'name': 'Outra Pessoa'}), None, db))
        assert db.get(WebUser, 1).profile.avatar_path == path
        assert not deleted


def test_proxy_avatar_so_foto_atual_e_colega_ou_contato(monkeypatch):
    with session() as db:
        current = db.get(WebUser, 1)
        outsider = db.get(WebUser, 3)
        url = 'https://store.private.blob.vercel-storage.com/users/1/avatars/atual.jpg'
        current.profile.avatar_path = profile._blob_avatar_route(1, url)
        db.commit()
        content = []
        monkeypatch.setattr(profile, 'blob_get', lambda u: (content.append(u) or (b'JPEGDATA', 'image/jpeg')))
        viewer = [outsider]
        monkeypatch.setattr(profile, 'current_user', lambda req, database: viewer[0])
        ref = profile._b64url_encode(url.encode('utf-8'))
        denied = asyncio.run(profile.serve_private_avatar(1, ref, object(), db))
        assert denied.status_code == 403 and content == []
        db.add(UserChatContact(owner_user_id=3, contact_user_id=1)); db.commit()
        allowed = asyncio.run(profile.serve_private_avatar(1, ref, object(), db))
        assert allowed.status_code == 200 and allowed.body == b'JPEGDATA'
        assert content == [url]
        old_ref = profile._b64url_encode(url.replace('atual', 'antiga').encode('utf-8'))
        stale = asyncio.run(profile.serve_private_avatar(1, old_ref, object(), db))
        assert stale.status_code == 404
        assert content == [url]


def test_upload_direto_so_aceita_imagens_validas(monkeypatch):
    with session() as db:
        user = db.get(WebUser, 1)
        monkeypatch.setattr(profile, 'current_user', lambda req, session: user)
        monkeypatch.setattr(profile, 'validate_csrf_token', lambda *args: True)
        monkeypatch.setattr(profile, 'blob_ready', lambda: True)
        stored = []
        def put(path, payload, media_type):
            stored.append((path, payload, media_type))
            return {'url': f'https://store.private.blob.vercel-storage.com/{path}'}
        monkeypatch.setattr(profile, 'blob_put', put)
        head = {'content-type': 'image/jpeg', 'x-csrf-token': 'ok'}
        invalid = asyncio.run(profile.avatar_upload_direct(Request(content=b'TEXT', headers=head), db))
        assert invalid.status_code == 400 and stored == []
        result = asyncio.run(profile.avatar_upload_direct(Request(content=b'\xff\xd8\xffxyz', headers=head), db))
        assert result.status_code == 200
        assert len(stored) == 1 and stored[0][0].startswith('users/1/avatars/')


def test_chat_entrega_avatar_atual_de_cada_usuario():
    with session() as db:
        user = db.get(WebUser, 1)
        url = 'https://store.private.blob.vercel-storage.com/users/1/avatars/chat.webp'
        user.profile.avatar_path = profile._blob_avatar_route(1, url)
        db.add(ChatMessage(company_id=1, user_id=1, message='Teste foto'))
        db.commit()
        member = company._chat_member_payload(user, 2)
        assert member['avatar_url'] == avatar_url(user)
        payload = company._group_message_payload(db.query(ChatMessage).first())
        assert payload['user_avatar_url'] == avatar_url(user)
        assert member['avatar_url'].startswith('/profile/avatar/1?v=')


def test_cliente_upload_por_blob_e_chat_usa_fotos():
    root = Path(__file__).resolve().parents[1]
    html = (root/'app/templates/profile/index.html').read_text()
    chat = (root/'app/static/js/chat.js').read_text()
    assert 'avatar-upload-direct' in html and 'avatar_blob_url' in html
    assert "input.removeAttribute('name')" in html
    assert 'avatarHtml(item)' in chat
    assert 'setHeaderAvatar(data.contact)' in chat
    assert 'user_avatar_url' in chat
