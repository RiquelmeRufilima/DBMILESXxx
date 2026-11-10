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


def test_videos_dos_tutoriais():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.routers.tutorial import TUTORIAL_ITEMS, VIDEO_FILES
    from tests.test_security import logged, make_company, make_user
    videos = [i for i in TUTORIAL_ITEMS if i["kind"] == "video"]
    assert len(videos) >= 8
    for item in videos:
        assert VIDEO_FILES[item["slug"]].is_file(), item["slug"]
        if item.get("poster"):
            assert (Path(__file__).resolve().parents[1] / "app" / item["poster"].lstrip("/")).is_file()
    with TestClient(app):
        assert TestClient(app).get("/tutorial/video/criar-programa").status_code == 401
        company = make_company("Agência Vídeos")
        make_user("videos@example.invalid", company_id=company, role="membro")
        client = logged(None, "videos@example.invalid")
        resp = client.get("/tutorial/video/criar-programa", headers={"Range": "bytes=0-1023"})
        assert resp.status_code == 206 and resp.content == VIDEO_FILES["criar-programa"].read_bytes()[:1024]
        assert client.get("/tutorial/video/..%2F..%2Fconfig").status_code == 404
        assert client.get("/tutorial/video/nao-existe").status_code == 404
        html = client.get("/tutorial").text
    assert html.count("<video") == len(videos)
    assert html.count('preload="metadata"') == 1
