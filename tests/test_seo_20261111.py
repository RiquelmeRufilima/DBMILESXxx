"""SEO: robots.txt, sitemap.xml, llms.txt, meta tags, Analytics e cache de CDN."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.services import seo


def _client(monkeypatch, **env):
    for key in ("SITE_URL", "GA_MEASUREMENT_ID", "GOOGLE_SITE_VERIFICATION", "VERCEL_ENV"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return TestClient(app)


def test_robots_sitemap_llms(monkeypatch):
    c = _client(monkeypatch, SITE_URL="https://dbmilesx.com.br/")
    r = c.get("/robots.txt")
    assert r.status_code == 200 and "Disallow: /\n" in r.text and "Allow: /login$" in r.text
    assert "Sitemap: https://dbmilesx.com.br/sitemap.xml" in r.text
    assert "max-age" in r.headers["vercel-cdn-cache-control"] and "set-cookie" not in r.headers
    s = c.get("/sitemap.xml")
    assert s.headers["content-type"].startswith("application/xml")
    for path in seo.PUBLIC_PAGES:
        assert f"<loc>https://dbmilesx.com.br{path}</loc>" in s.text
    assert "/dashboard" not in s.text
    l = c.get("/llms.txt")
    assert l.text.startswith("# DBMILESX") and "https://dbmilesx.com.br/register" in l.text


def test_preview_fica_fora_da_busca(monkeypatch):
    c = _client(monkeypatch, VERCEL_ENV="preview", GA_MEASUREMENT_ID="G-ABC1234567")
    assert c.get("/robots.txt").text.endswith("Disallow: /\n")
    html = c.get("/login").text
    assert 'content="noindex, nofollow"' in html and "googletagmanager" not in html


def test_login_tem_titulo_descricao_e_canonical(monkeypatch):
    c = _client(monkeypatch, SITE_URL="https://dbmilesx.com.br", GOOGLE_SITE_VERIFICATION="abcDEF123_-xyz")
    html = c.get("/login").text
    assert "<title>DBMILESX | Sistema de cotação de passagens aéreas e milhas para agências</title>" in html
    assert '<meta name="robots" content="index, follow">' in html
    assert '<link rel="canonical" href="https://dbmilesx.com.br/login">' in html
    assert 'name="google-site-verification" content="abcDEF123_-xyz"' in html
    assert '"@type": "SoftwareApplication"' in html and "login-about" in html
    assert "googletagmanager" not in html  # sem GA_MEASUREMENT_ID, nada é carregado


def test_analytics_so_com_id_valido(monkeypatch):
    c = _client(monkeypatch, GA_MEASUREMENT_ID="G-ABC1234567")
    html = c.get("/login").text
    assert "gtag/js?id=G-ABC1234567" in html and "page_location: location.origin + location.pathname" in html
    assert "allow_ad_personalization_signals: false" in html
    c2 = _client(monkeypatch, GA_MEASUREMENT_ID="<script>")
    assert "googletagmanager" not in c2.get("/login").text


def test_paginas_internas_noindex(monkeypatch):
    assert not seo.page_seo("/dashboard")["indexable"]
    assert seo.page_seo("/terms")["indexable"]


def test_estatico_vai_para_cdn(monkeypatch):
    c = _client(monkeypatch)
    r = c.get("/static/css/app.css?v=5.29.1")
    assert r.status_code == 200 and r.headers["vercel-cdn-cache-control"] == "max-age=31536000"
    assert "set-cookie" not in r.headers
