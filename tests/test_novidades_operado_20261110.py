"""Aviso único de novidades e "Operado por" na arte de programas de milhas."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import UserPreference, WebUser
from app.routers import tutorial

ROOT = Path(__file__).resolve().parents[1] / "app"


def _db(settings: dict):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.add(WebUser(id=7, name="Equipe", email="equipe@local.invalid", password_hash="x", active=True))
    db.add(UserPreference(user_id=7, settings_json=json.dumps(settings)))
    db.commit()
    return db


def test_novidades_aparecem_uma_unica_vez(monkeypatch):
    with _db({tutorial.WELCOME_KEY: True}) as db:
        user = db.get(WebUser, 7)
        assert tutorial.news_pending(user)
        monkeypatch.setattr(tutorial, "current_user", lambda request, db_: user)
        request = SimpleNamespace(session={"csrf_token": "ok"})
        assert tutorial.tutorial_news(request, "errado", "later", db).headers["location"] == "/dashboard"
        assert tutorial.news_pending(user)
        resp = tutorial.tutorial_news(request, "ok", "later", db)
        assert resp.status_code == 303 and resp.headers["location"] == "/dashboard"
        db.expire_all()
        assert not tutorial.news_pending(db.get(WebUser, 7))
        # As boas-vindas continuam vistas.
        assert not tutorial.welcome_pending(db.get(WebUser, 7))


def test_usuario_novo_ve_so_as_boas_vindas():
    with _db({}) as db:
        user = db.get(WebUser, 7)
        assert tutorial.welcome_pending(user) and not tutorial.news_pending(user)
        tutorial._acknowledge(db, user)
        assert not tutorial.welcome_pending(user) and not tutorial.news_pending(user)


def test_dashboard_mostra_o_aviso():
    html = (ROOT / "templates" / "dashboard.html").read_text()
    assert "show_news and not show_tutorial_welcome" in html and "/tutorial/novidades" in html


def test_arte_mostra_operado_por_e_emissor():
    js = (ROOT / "static" / "js" / "flight-quote-art-20261102.js").read_text()
    assert "Operado pela ${data.airline}" in js and "EMITIDO PELA" in js
    tpl = (ROOT / "templates" / "calculations" / "result.html").read_text()
    assert "'issuer':" in tpl
    router = (ROOT / "routers" / "calculations.py").read_text()
    assert '"issuer": issuer' in router
