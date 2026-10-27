"""Testes de segurança do DBMILESX.

Rodar no Codespace (NUNCA aponta para o banco de produção: usa um SQLite
temporário criado só para o teste):

    pip install pytest
    python -m pytest tests/test_security.py -v

Cobre: SQL injection, XSS, CSRF, acesso entre empresas (IDOR), limite de
tentativas, bloqueio pelo administrador, redirecionamento aberto, cabeçalhos
de segurança, código de entrada da empresa e etiquetas.
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

import pytest

# --- Ambiente isolado: precisa vir ANTES de importar o app ------------------
_TMP = tempfile.mkdtemp(prefix="dbmilesx-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_TMP) / 'test.db'}"
os.environ["SECRET_KEY"] = "test-secret-key-only-for-pytest-1234567890"
os.environ["APP_ENV"] = "test"
os.environ["RUN_FULL_STARTUP_MAINTENANCE"] = "0"
os.environ["SESSION_HTTPS_ONLY"] = "0"
os.environ.pop("VERCEL", None)
os.environ.pop("BOOTSTRAP_ADMIN_EMAIL", None)
os.environ.pop("BOOTSTRAP_ADMIN_PASSWORD", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app import config  # noqa: E402

assert config.DATABASE_URL.startswith("sqlite"), "Os testes só podem rodar em SQLite temporário!"

from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import AcceptedQuote, Person, QuoteGroup, WebCompany, WebUser  # noqa: E402
from app.security import hash_password  # noqa: E402

PASSWORD = "SenhaForte123"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def started_app():
    with TestClient(app) as client:  # executa o lifespan (cria tabelas)
        yield client


def _db():
    return SessionLocal()


def make_company(name: str) -> int:
    db = _db()
    try:
        company = WebCompany(name=name)
        db.add(company)
        db.commit()
        return company.id
    finally:
        db.close()


def make_user(email: str, *, company_id: int | None = None, role: str = "membro", owner: bool = False, active: bool = True) -> int:
    db = _db()
    try:
        user = WebUser(
            email=email.lower(),
            password_hash=hash_password(PASSWORD),
            name=email.split("@")[0].title(),
            role=role,
            active=active,
            is_owner=owner,
            company_id=company_id,
        )
        db.add(user)
        db.commit()
        return user.id
    finally:
        db.close()


def make_group(user_id: int, company_id: int | None, name: str) -> int:
    db = _db()
    try:
        group = QuoteGroup(user_id=user_id, company_id=company_id, quote_name=name, origin="FOR", destination="GRU")
        db.add(group)
        db.commit()
        return group.id
    finally:
        db.close()


def csrf_from(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html) or re.search(r'name="csrf-token" content="([^"]+)"', html)
    assert match, "csrf_token não encontrado na página"
    return match.group(1)


def new_client(started_app) -> TestClient:
    return TestClient(app, follow_redirects=False)


def login(client: TestClient, email: str, password: str = PASSWORD, ip: str = "10.0.0.1"):
    page = client.get("/login")
    token = csrf_from(page.text)
    return client.post(
        "/login",
        data={"email": email, "password": password, "csrf_token": token},
        headers={"x-forwarded-for": ip},
    )


def logged(started_app, email: str) -> TestClient:
    client = new_client(started_app)
    response = login(client, email, ip=f"10.1.{abs(hash(email)) % 250}.1")
    assert response.status_code == 303 and response.headers["location"] == "/dashboard", response.text
    return client


def page_csrf(client: TestClient, url: str = "/settings") -> str:
    return csrf_from(client.get(url, follow_redirects=True).text)


# ---------------------------------------------------------------------------
# SQL injection
# ---------------------------------------------------------------------------
SQLI_PAYLOADS = [
    "' OR '1'='1",
    "' OR 1=1 --",
    "admin'--",
    "%' UNION SELECT email, password_hash FROM web_users --",
    "'; DROP TABLE web_users; --",
    "\" OR \"\"=\"",
]


@pytest.mark.parametrize("payload", SQLI_PAYLOADS)
def test_sql_injection_no_login(started_app, payload):
    make_user(f"sqli{abs(hash(payload)) % 10_000}@teste.com")
    client = new_client(started_app)
    response = login(client, payload, payload, ip=f"10.9.{abs(hash(payload)) % 250}.9")
    assert response.status_code == 303
    assert response.headers["location"] == "/login"  # não entrou


def test_sql_injection_na_busca_do_historico_nao_vaza_outra_empresa(started_app):
    a = make_company("Empresa SQL A")
    b = make_company("Empresa SQL B")
    ua = make_user("sql-a@teste.com", company_id=a, role="admin", owner=True)
    ub = make_user("sql-b@teste.com", company_id=b, role="admin", owner=True)
    make_group(ub, b, "SEGREDO_DA_EMPRESA_B")
    make_group(ua, a, "Cotacao normal A")
    client = logged(started_app, "sql-a@teste.com")
    for payload in SQLI_PAYLOADS:
        response = client.get("/calculations/history", params={"q": payload})
        assert response.status_code == 200
        assert "SEGREDO_DA_EMPRESA_B" not in response.text
    # A tabela continua existindo depois do "DROP TABLE"
    db = _db()
    try:
        assert db.query(WebUser).count() >= 2
    finally:
        db.close()


def test_sql_injection_na_busca_de_pessoas(started_app):
    a = make_company("Empresa Pessoas A")
    b = make_company("Empresa Pessoas B")
    make_user("pes-a@teste.com", company_id=a, role="admin", owner=True)
    ub = make_user("pes-b@teste.com", company_id=b, role="admin", owner=True)
    db = _db()
    try:
        db.add(Person(name="PASSAGEIRO_SECRETO_B", company_id=b, user_id=ub))
        db.commit()
    finally:
        db.close()
    client = logged(started_app, "pes-a@teste.com")
    for payload in SQLI_PAYLOADS:
        response = client.get("/persons/search", params={"q": payload})
        assert response.status_code == 200
        assert "PASSAGEIRO_SECRETO_B" not in response.text


# ---------------------------------------------------------------------------
# Acesso entre empresas (IDOR)
# ---------------------------------------------------------------------------
def test_usuario_nao_abre_cotacao_de_outra_empresa(started_app):
    a = make_company("Empresa IDOR A")
    b = make_company("Empresa IDOR B")
    make_user("idor-a@teste.com", company_id=a, role="admin", owner=True)
    ub = make_user("idor-b@teste.com", company_id=b, role="admin", owner=True)
    group_b = make_group(ub, b, "COTACAO_PRIVADA_B")
    client = logged(started_app, "idor-a@teste.com")
    for url in (
        f"/calculations/new?group_id={group_b}&calc=1",
        f"/calculations/group/{group_b}",
        f"/cadastros/cotacoes/{group_b}/preview/data",
    ):
        response = client.get(url, follow_redirects=True)
        assert "COTACAO_PRIVADA_B" not in response.text, url


def test_admin_database_restrito(started_app):
    c = make_company("Empresa Gerente")
    make_user("dono-g@teste.com", company_id=c, role="admin", owner=True)
    make_user("gerente-g@teste.com", company_id=c, role="gerente")
    make_user("solto-admin@teste.com", company_id=None, role="admin")
    for email in ("gerente-g@teste.com", "solto-admin@teste.com"):
        client = logged(started_app, email)
        response = client.get("/admin/database")
        assert response.status_code == 303 and response.headers["location"] == "/dashboard", email


def test_admin_nao_reseta_senha_do_dono(started_app):
    c = make_company("Empresa Reset")
    owner_id = make_user("dono-r@teste.com", company_id=c, role="admin", owner=True)
    make_user("admin-r@teste.com", company_id=c, role="admin")
    client = logged(started_app, "admin-r@teste.com")
    token = page_csrf(client, "/admin/database")
    client.post(f"/admin/database/users/{owner_id}/reset-password", data={"csrf_token": token})
    # O dono continua entrando com a senha original
    assert login(new_client(started_app), "dono-r@teste.com", ip="10.3.3.3").headers["location"] == "/dashboard"


# ---------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------
def test_csrf_obrigatorio_para_criar_empresa(started_app):
    make_user("csrf@teste.com")
    client = logged(started_app, "csrf@teste.com")
    client.post("/company/create", data={"name": "Empresa Sem Token", "csrf_token": "falso"})
    db = _db()
    try:
        assert db.query(WebCompany).filter(WebCompany.name == "Empresa Sem Token").count() == 0
    finally:
        db.close()


def test_csrf_obrigatorio_nas_etiquetas(started_app):
    make_user("csrf-tag@teste.com")
    client = logged(started_app, "csrf-tag@teste.com")
    response = client.post("/tags", json={"name": "Hack", "csrf_token": "falso"})
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# XSS
# ---------------------------------------------------------------------------
def test_xss_no_nome_da_pessoa_nao_executa(started_app):
    c = make_company("Empresa XSS")
    uid = make_user("xss@teste.com", company_id=c, role="admin", owner=True)
    payload = "x');alert(1);//<script>alert(2)</script>"
    db = _db()
    try:
        person = Person(name=payload, company_id=c, user_id=uid)
        db.add(person)
        db.commit()
        person_id = person.id
    finally:
        db.close()
    client = logged(started_app, "xss@teste.com")
    html = client.get(f"/persons/{person_id}", follow_redirects=True).text
    assert "<script>alert(2)</script>" not in html
    assert "');alert(1);//" not in html  # aspas escapadas dentro do confirm()


# ---------------------------------------------------------------------------
# Limite de tentativas e bloqueio
# ---------------------------------------------------------------------------
def test_limite_de_tentativas_no_login(started_app):
    make_user("forca-bruta@teste.com")
    client = new_client(started_app)
    for _ in range(5):
        assert login(client, "forca-bruta@teste.com", "errada", ip="10.7.7.7").headers["location"] == "/login"
    # Mesmo com a senha CERTA, fica bloqueado temporariamente
    response = login(client, "forca-bruta@teste.com", PASSWORD, ip="10.7.7.8")
    assert response.headers["location"] == "/login"


def test_usuario_bloqueado_nao_volta_pelo_cadastro(started_app):
    c = make_company("Empresa Bloqueio")
    make_user("dono-b@teste.com", company_id=c, role="admin", owner=True)
    member_id = make_user("bloqueado@teste.com", company_id=c)
    admin = logged(started_app, "dono-b@teste.com")
    token = page_csrf(admin, "/company")
    admin.post(f"/company/members/{member_id}/update", data={"role": "membro", "active": "", "csrf_token": token})

    visitor = new_client(started_app)
    token = csrf_from(visitor.get("/register").text)
    response = visitor.post("/register", data={
        "name": "Bloqueado", "email": "bloqueado@teste.com", "password": PASSWORD,
        "password_confirm": PASSWORD, "csrf_token": token, "job_title": "", "phone": "",
    }, headers={"x-forwarded-for": "10.5.5.5"})
    assert response.headers["location"] == "/login"
    assert login(new_client(started_app), "bloqueado@teste.com", ip="10.5.5.6").headers["location"] == "/login"


def test_codigo_da_empresa_errado_tem_limite(started_app):
    make_user("tenta-codigo@teste.com")
    client = logged(started_app, "tenta-codigo@teste.com")
    token = page_csrf(client)
    for _ in range(8):
        client.post("/company/join", data={"company_name": "", "code": "1-ABC-ZZZZZZZZ", "csrf_token": token})
    response = client.post("/company/join", data={"company_name": "", "code": "1-ABC-ZZZZZZZZ", "csrf_token": token}, follow_redirects=True)
    assert "Muitas tentativas" in response.text


def test_entrar_na_empresa_com_codigo_valido_compartilha_historico(started_app):
    c = make_company("Empresa Convite")
    make_user("dono-c@teste.com", company_id=c, role="admin", owner=True)
    novo_id = make_user("novo-membro@teste.com")
    make_group(novo_id, None, "HISTORICO_PESSOAL_DO_NOVO")
    admin = logged(started_app, "dono-c@teste.com")
    code = admin.get("/company/invite-code").json()["code"]

    novo = logged(started_app, "novo-membro@teste.com")
    token = page_csrf(novo)
    novo.post("/company/join", data={"company_name": "empresa convite", "code": code, "csrf_token": token})
    db = _db()
    try:
        assert db.get(WebUser, novo_id).company_id == c
    finally:
        db.close()
    # O dono enxerga a cotação antiga do novo membro
    assert "HISTORICO_PESSOAL_DO_NOVO" in admin.get("/calculations/history").text


def test_membro_comum_nao_gera_codigo(started_app):
    c = make_company("Empresa Codigo Membro")
    make_user("dono-m@teste.com", company_id=c, role="admin", owner=True)
    make_user("comum@teste.com", company_id=c, role="membro")
    client = logged(started_app, "comum@teste.com")
    assert client.get("/company/invite-code").status_code == 403


# ---------------------------------------------------------------------------
# Redirecionamento aberto e cabeçalhos
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("target", ["//evil.com", "/\\evil.com", "https://evil.com", "/\\/evil.com", "/%0d%0aevil"])
def test_redirecionamento_aberto_bloqueado(target):
    from app.routers.tasks import _safe_return_to

    result = _safe_return_to(target)
    assert result == "/tasks" or (result.startswith("/") and not result.startswith("//") and "\\" not in result)


def test_cabecalhos_de_seguranca(started_app):
    response = new_client(started_app).get("/login")
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "SAMEORIGIN"
    assert "Referrer-Policy" in response.headers


# ---------------------------------------------------------------------------
# Etiquetas: isolamento entre empresas
# ---------------------------------------------------------------------------
def test_etiquetas_isoladas_por_empresa(started_app):
    a = make_company("Empresa Tag A")
    b = make_company("Empresa Tag B")
    ua = make_user("tag-a@teste.com", company_id=a, role="admin", owner=True)
    ub = make_user("tag-b@teste.com", company_id=b, role="admin", owner=True)
    group_a = make_group(ua, a, "Cotacao Tag A")
    group_b = make_group(ub, b, "Cotacao Tag B")

    client_a = logged(started_app, "tag-a@teste.com")
    token_a = page_csrf(client_a, "/calculations/history")
    created = client_a.post("/tags/assign", json={"kind": "group", "id": group_a, "new_tag": "VIP", "csrf_token": token_a}).json()
    assert created["ok"] and created["tags"][0]["name"] == "VIP"
    tag_id = created["tags"][0]["id"]

    # Empresa A não consegue etiquetar cotação da empresa B
    denied = client_a.post("/tags/assign", json={"kind": "group", "id": group_b, "tag_ids": [tag_id], "csrf_token": token_a})
    assert denied.status_code == 404

    # Empresa B não vê, não usa e não apaga a etiqueta da empresa A
    client_b = logged(started_app, "tag-b@teste.com")
    token_b = page_csrf(client_b, "/calculations/history")
    assert all(t["id"] != tag_id for t in client_b.get("/tags/api").json()["tags"])
    used = client_b.post("/tags/assign", json={"kind": "group", "id": group_b, "tag_ids": [tag_id], "csrf_token": token_b}).json()
    assert used["tags"] == []
    assert client_b.post(f"/tags/{tag_id}/delete", json={"csrf_token": token_b}).status_code == 404

    # Filtro por etiqueta no histórico
    filtered = client_a.get(f"/calculations/history?tag={tag_id}").text
    assert "Cotacao Tag A" in filtered


# ---------------------------------------------------------------------------
# Etiquetas: tipos (cotação/voo/pessoa), página e voos
# ---------------------------------------------------------------------------
def test_pagina_de_etiquetas_e_tipos(started_app):
    c = make_company("Empresa Tipos")
    uid = make_user("tipos@teste.com", company_id=c, role="admin", owner=True)
    group = make_group(uid, c, "Cotacao Tipos")
    db = _db()
    try:
        person = Person(name="Pessoa Tipos", company_id=c, user_id=uid)
        db.add(person)
        db.commit()
        person_id = person.id
    finally:
        db.close()
    client = logged(started_app, "tipos@teste.com")
    token = page_csrf(client, "/tags")
    assert "Etiquetas" in client.get("/tags").text

    voo = client.post("/tags", json={"name": "PET", "kind": "voo", "csrf_token": token}).json()["tag"]
    pessoa = client.post("/tags", json={"name": "Cliente VIP", "kind": "pessoa", "csrf_token": token}).json()["tag"]
    assert voo["kind"] == "voo" and pessoa["kind"] == "pessoa"

    # Etiqueta de voo NÃO entra em pessoa (tipo errado é ignorado)
    r = client.post("/tags/assign", json={"kind": "person", "id": person_id, "tag_ids": [voo["id"], pessoa["id"]], "csrf_token": token}).json()
    assert [t["name"] for t in r["tags"]] == ["Cliente VIP"]
    assert "Pessoa Tipos" in client.get(f"/persons?tag={pessoa['id']}").text

    # Voo: id = group_id * 1000 + trecho
    r = client.post("/tags/assign", json={"kind": "flight", "id": group * 1000 + 1, "tag_ids": [voo["id"]], "csrf_token": token}).json()
    assert r["ok"] and r["tags"][0]["name"] == "PET"

    # Desativar e filtrar por situação
    client.post(f"/tags/{voo['id']}/update", json={"active": "0", "csrf_token": token})
    assert "PET" not in client.get("/tags?situacao=ativo").text
    assert "PET" in client.get("/tags?situacao=inativo").text


def test_tela_de_voos_com_logo_e_etiquetas(started_app):
    import json as _json
    c = make_company("Empresa Voos")
    uid = make_user("voos@teste.com", company_id=c, role="admin", owner=True)
    group = make_group(uid, c, "Cotacao Voos")
    db = _db()
    try:
        db.add(AcceptedQuote(group_id=group, user_id=uid, company_id=c, extra_json=_json.dumps({
            "client_name": "Rafael Teste",
            "flights": [{"kind": "ida", "origin": "FOR", "destination": "GRU", "departure_date": "2030-01-10",
                         "departure_time": "10:55", "airline": "LATAM Airlines", "locator": "ABC123"}],
        })))
        db.commit()
    finally:
        db.close()
    client = logged(started_app, "voos@teste.com")
    html = client.get("/cadastros/voos").text
    assert "Rafael Teste" in html and "/imagens/latam.png" in html and "ABC123" in html
    assert "10h55" in html and "t-distante" in html

    token = page_csrf(client, "/cadastros/voos")
    tag = client.post("/tags", json={"name": "Grupo Copa", "kind": "voo", "csrf_token": token}).json()["tag"]
    client.post("/tags/assign", json={"kind": "flight", "id": group * 1000, "tag_ids": [tag["id"]], "csrf_token": token})
    assert "Rafael Teste" in client.get(f"/cadastros/voos?tag={tag['id']}").text


def test_migracao_tabela_antiga_de_etiquetas():
    """Banco que já tinha a tabela de etiquetas sem as colunas novas (deploy anterior)."""
    from sqlalchemy import create_engine, inspect, text

    from app.services import protection
    from app.services.schema_migrations import _add_columns

    engine = create_engine(f"sqlite:///{Path(_TMP) / 'old.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE web_quote_tags (id INTEGER PRIMARY KEY, company_id INTEGER, user_id INTEGER, name VARCHAR(40) NOT NULL, color VARCHAR(9) NOT NULL, created_at DATETIME NOT NULL)"))
        conn.execute(text("INSERT INTO web_quote_tags (company_id, user_id, name, color, created_at) VALUES (1, 1, 'Antiga', '#fff000', '2026-10-27')"))
    _add_columns(engine, "web_quote_tags", {"kind": "VARCHAR(20) DEFAULT 'cotacao' NOT NULL", "active": "BOOLEAN DEFAULT 1 NOT NULL"})
    cols = {c["name"] for c in inspect(engine).get_columns("web_quote_tags")}
    assert {"kind", "active"} <= cols
    with engine.connect() as conn:
        assert conn.execute(text("SELECT kind, active FROM web_quote_tags")).one() == ("cotacao", 1)
