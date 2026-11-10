"""Tutorial: navegação, onboarding persistente e mídia protegida com byte-ranges."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import UserPreference, WebUser
from app.routers import tutorial
from app.web import templates


def make_user_db():
    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add(WebUser(id=401, name='Agente Teste', email='tutorial@local.invalid', password_hash='x', active=True))
    session.add(UserPreference(user_id=401, settings_json='{"animations":true}'))
    session.commit()
    return session


def test_tutorial_persistence_reuses_settings_without_schema_migration():
    with make_user_db() as db:
        user = db.get(WebUser, 401)
        assert tutorial.welcome_pending(user)
        tutorial._acknowledge(db, user)
        assert tutorial.welcome_pending(user) is False
        assert json.loads(user.preference.settings_json) == {
            'animations': True, tutorial.WELCOME_KEY: True,
        }
        db.expire_all()
        assert not tutorial.welcome_pending(db.get(WebUser, 401))
        tutorial._acknowledge(db, db.get(WebUser, 401))  # repetido é idempotente
        assert not tutorial.welcome_pending(db.get(WebUser, 401))


def test_tutorial_csrf_and_user_link(monkeypatch):
    with make_user_db() as db:
        user = db.get(WebUser, 401)
        monkeypatch.setattr(tutorial, 'current_user', lambda request, db_: user)
        request = SimpleNamespace(session={'csrf_token': 'safe-token'})
        bad = tutorial.tutorial_welcome(request, 'wrong', 'tutorial', db)
        assert bad.status_code == 303 and bad.headers['location'] == '/dashboard'
        assert tutorial.welcome_pending(user)
        redirect = tutorial.tutorial_welcome(request, 'safe-token', 'tutorial', db)
        assert redirect.status_code == 303 and redirect.headers['location'] == '/tutorial'
        assert not tutorial.welcome_pending(user)
        redirect2 = tutorial.tutorial_welcome(request, 'safe-token', 'later', db)
        assert redirect2.headers['location'] == '/dashboard'


def test_only_authenticated_users_get_video(monkeypatch):
    with make_user_db() as db:
        monkeypatch.setattr(tutorial, 'current_user', lambda req, session: None)
        req = SimpleNamespace(method='GET', headers={})
        assert tutorial.tutorial_video(req, db).status_code == 401
        assert tutorial.tutorial_page(req, db).headers['location'] == '/login'


def test_video_supports_range_and_seeking(monkeypatch):
    with make_user_db() as db:
        user = db.get(WebUser, 401)
        monkeypatch.setattr(tutorial, 'current_user', lambda req, session: user)
        video = tutorial.MEDIA_FILE.read_bytes()
        assert video[:16].find(b'ftyp') >= 0  # MP4 em formato compatível
        size = len(video)
        for raw, expected in [('bytes=0-255', (0,255)), ('bytes=4096-', (4096,4096+tutorial.MAX_VIDEO_BYTES-1)),
                              ('bytes=-512', (size-512,size-1))]:
            req = SimpleNamespace(method='GET', headers={'range': raw})
            resp = tutorial.tutorial_video(req, db)
            assert resp.status_code == 206
            assert resp.headers['content-range'] == f'bytes {expected[0]}-{expected[1]}/{size}'
            assert resp.headers['accept-ranges'] == 'bytes'
            assert int(resp.headers['content-length']) <= tutorial.MAX_VIDEO_BYTES
            async def collect():
                parts=[]
                async for chunk in resp.body_iterator:
                    parts.append(chunk)
                return b''.join(parts)
            assert asyncio.run(collect()) == video[expected[0]:expected[1]+1]
        invalid = tutorial.tutorial_video(SimpleNamespace(method='GET', headers={'range': f'bytes={size}-'}), db)
        assert invalid.status_code == 416
        assert invalid.headers['content-range'] == f'bytes */{size}'
        head = tutorial.tutorial_video(SimpleNamespace(method='HEAD', headers={'range': 'bytes=0-512'}), db)
        assert head.status_code == 206 and head.headers['content-length'] == '513'


def test_menu_template_and_material_catalog():
    root = Path(__file__).resolve().parents[1]
    base = (root/'app/templates/base.html').read_text()
    dashboard = (root/'app/templates/dashboard.html').read_text()
    assert 'href="/tutorial"' in base
    assert 'href="/tutorial"' in dashboard
    assert 'action="/tutorial/welcome"' in dashboard
    assert 'value="tutorial"' in dashboard and 'value="later"' in dashboard
    assert tutorial.TUTORIAL_ITEMS[0]['slug'] == 'cotacao' and len(tutorial.TUTORIAL_ITEMS) >= 8
    for template in ['tutorial/index.html', 'dashboard.html', 'base.html']:
        assert templates.env.get_template(template) is not None


def test_video_range_via_http_not_gzipped(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.setattr(tutorial, 'current_user', lambda req, db: SimpleNamespace(id=401))
    # Mesmo com Accept-Encoding: gzip, os bytes do MP4 precisam ficar intactos.
    with TestClient(app) as client:
        resp = client.get('/tutorial/video/cotacao', headers={'Range':'bytes=0-1023', 'Accept-Encoding':'gzip'})
    assert resp.status_code == 206
    assert resp.headers['content-range'].startswith('bytes 0-1023/')
    assert resp.headers.get('content-encoding') in (None, 'identity')
    assert resp.content == tutorial.MEDIA_FILE.read_bytes()[:1024]
