"""Responsável da cotação salvo sem recarregar a página (resposta em JSON)."""
import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import QuoteGroup, WebUser
from tests.test_security import csrf_from, logged, make_company, make_user


@pytest.fixture(scope="module")
def setup():
    with TestClient(app):
        company = make_company("Agência Responsável")
        make_user("resp-admin@example.invalid", company_id=company, role="admin", owner=True)
        make_user("resp-membro@example.invalid", company_id=company, role="membro")
        db = SessionLocal()
        admin = db.query(WebUser).filter_by(email="resp-admin@example.invalid").one()
        membro = db.query(WebUser).filter_by(email="resp-membro@example.invalid").one()
        group = QuoteGroup(user_id=admin.id, company_id=company, quote_name="Resp")
        db.add(group); db.commit()
        ids = (group.id, membro.id)
        db.close()
        yield logged(None, "resp-admin@example.invalid"), ids


def test_troca_de_responsavel_responde_json(setup):
    client, (group_id, membro_id) = setup
    token = csrf_from(client.get("/calculations/history").text)
    resp = client.post(f"/calculations/group/{group_id}/assign", data={"csrf_token": token, "assigned_user_id": str(membro_id)},
                       headers={"X-Requested-With": "XMLHttpRequest"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True and resp.json()["user_id"] == membro_id
    db = SessionLocal()
    assert db.get(QuoteGroup, group_id).assigned_user_id == membro_id
    db.close()


def test_erro_tambem_vem_em_json(setup):
    client, (group_id, _membro) = setup
    resp = client.post(f"/calculations/group/{group_id}/assign", data={"csrf_token": "errado"},
                       headers={"X-Requested-With": "XMLHttpRequest"})
    assert resp.status_code == 400 and resp.json()["ok"] is False


def test_sem_javascript_continua_redirecionando(setup):
    client, (group_id, membro_id) = setup
    token = csrf_from(client.get("/calculations/history").text)
    resp = client.post(f"/calculations/group/{group_id}/assign", data={"csrf_token": token, "assigned_user_id": str(membro_id)}, follow_redirects=False)
    assert resp.status_code == 303
