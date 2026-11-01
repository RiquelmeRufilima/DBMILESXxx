"""Regressões da Fase 2. Rodar junto de tests/test_security.py."""
from __future__ import annotations

from app.services.security_headers import CSP_REPORT_ONLY, apply_phase2_headers
from starlette.responses import Response
from test_security import started_app, make_user, new_client, login


def test_csp_em_monitoramento_no_login(started_app):
    response = new_client(started_app).get('/login')
    assert response.status_code == 200
    assert response.headers['Content-Security-Policy-Report-Only'] == CSP_REPORT_ONLY
    assert 'Content-Security-Policy' not in response.headers
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert response.headers['X-Frame-Options'] == 'SAMEORIGIN'
    assert response.headers['Referrer-Policy'] == 'strict-origin-when-cross-origin'
    assert response.headers['X-Permitted-Cross-Domain-Policies'] == 'none'


def test_sem_csp_em_json_ou_estatico(started_app):
    client = new_client(started_app)
    for target in ('/health', '/static/css/app.css'):
        response = client.get(target)
        assert response.status_code == 200
        assert 'Content-Security-Policy-Report-Only' not in response.headers
        assert response.headers.get('X-Permitted-Cross-Domain-Policies') == 'none'


def test_herda_csp_especial_sem_sobrescrever():
    response = Response('ok', media_type='text/html', headers={'Content-Security-Policy': "default-src 'none'"})
    apply_phase2_headers(response)
    assert response.headers['Content-Security-Policy'] == "default-src 'none'"
    assert 'Content-Security-Policy-Report-Only' not in response.headers


def test_mfa_permanece_opcional_para_administrador(started_app):
    make_user('fase2-mfa-opcional@teste.com', role='admin', owner=True)
    client = new_client(started_app)
    response = login(client, 'fase2-mfa-opcional@teste.com', ip='10.210.1.1')
    assert response.status_code == 303
    assert response.headers['location'] == '/dashboard'
    assert client.get('/dashboard').status_code == 200
    text = client.get('/settings?tab=security').text
    assert '2FA' in text and 'opcional' in text
