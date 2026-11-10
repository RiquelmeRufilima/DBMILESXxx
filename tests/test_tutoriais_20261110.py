"""Central de tutoriais: abas, guias completos e prints existentes."""
from pathlib import Path

from app.services.tutorial_guides import TABS, guide_count

STATIC = Path(__file__).resolve().parents[1] / "app" / "static" / "tutorial"


def test_guias_completos_e_com_print():
    slugs = set()
    for tab in TABS:
        assert tab["key"] and tab["label"] and tab["guides"]
        for guide in tab["guides"]:
            assert guide["slug"] not in slugs, f"guia repetido: {guide['slug']}"
            slugs.add(guide["slug"])
            assert len(guide["steps"]) >= 3, guide["slug"]
            assert all(title and text for title, text in guide["steps"])
            assert (STATIC / f"{guide['image']}.webp").exists(), f"falta o print {guide['image']}.webp"
    assert guide_count() == len(slugs) >= 20


def test_pagina_tutorial_com_sessao():
    from fastapi.testclient import TestClient
    from app.main import app
    from tests.test_security import logged, make_company, make_user
    with TestClient(app):
        company = make_company("Agência Tutorial")
        make_user("tutorial@example.invalid", company_id=company, role="membro")
        client = logged(None, "tutorial@example.invalid")
        html = client.get("/tutorial").text
    assert html.count('role="tab"') == len(TABS)
    assert html.count('class="tg-guide"') == guide_count()
    assert 'src="/static/tutorial/consolidadoras.webp"' in html
