"""Regressões: logo e capa persistentes, telas de equipe, bagagem por direção."""
import asyncio
import io
from pathlib import Path

import pytest
from fastapi import UploadFile

from app.main import app
from app.models import CompanyCover
from app.routers import company
from app.services import pdf_service
from app.web import templates


def test_rotas_de_empresa_estao_no_modulo_ativo():
    routes = {(r.path, method) for r in app.routes for method in getattr(r, 'methods', set())}
    for path, method in (
        ('/company/branding', 'POST'),
        ('/company/branding/remove-logo', 'POST'),
        ('/company/branding/remove-cover', 'POST'),
        ('/company/logo', 'GET'),
        ('/company/cover', 'GET'),
    ):
        assert (path, method) in routes


def test_templates_com_painel_e_bagagens_por_trecho():
    for template in ('dashboard.html', 'company/dashboard.html', 'calculations/new.html'):
        templates.env.get_template(template)
    base = Path(__file__).resolve().parents[1] / 'app'
    luggage = (base / 'templates/calculations/new.html').read_text()
    assert 'name="bags_outbound"' in luggage
    assert 'name="bags_return"' in luggage
    assert 'dbmBagTotalCount' in luggage
    company_html = (base / 'templates/company/dashboard.html').read_text()
    assert 'name="cover"' in company_html
    assert 'name="logo"' in company_html
    assert '/company/logo' in company_html
    assert '/company/cover' in company_html


def test_imagem_blob_nao_expoe_credenciais(monkeypatch):
    monkeypatch.setattr(company, 'blob_get', lambda url: (b'fake-image', 'image/png'))
    payload, mime = company._image_bytes('blob:https://example.blob.vercel-storage.com/logo.png')
    assert payload == b'fake-image'
    assert mime == 'image/png'
    monkeypatch.setattr(pdf_service, 'blob_get', lambda url: (b'fake-image', 'image/png'))
    assert pdf_service.file_to_data_uri('blob:https://example.blob.vercel-storage.com/logo.png').startswith('data:image/png;base64,')


def test_upload_rejeita_imagem_falsa(monkeypatch):
    monkeypatch.setattr(company, 'blob_ready', lambda: False)
    upload = UploadFile(filename='logo.png', file=io.BytesIO(b'texto em vez de imagem'))
    with pytest.raises(ValueError, match='não é uma imagem válida'):
        asyncio.run(company._save_company_image(upload, 123, 'logo'))


def test_novo_registro_de_capa_nao_muda_tabela_existente():
    assert CompanyCover.__tablename__ == 'company_covers'
    assert 'image_path' in CompanyCover.__table__.columns
