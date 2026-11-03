"""Proteções estáticas para a funcionalidade progressiva do quadro."""
from pathlib import Path

from app.web import templates

ROOT = Path(__file__).resolve().parents[1]


def text(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_template_board_and_diagnostics_compilam():
    templates.env.get_template("cadastros/cotacoes.html")
    templates.env.get_template("diagnostics/performance.html")
    templates.env.get_template("calculations/history.html")


def test_esqueleto_autenticado_e_condicao_antes_de_buscar_cotacoes():
    source = text("app/routers/cadastros.py")
    route = source.split('def cotacoes(request: Request',1)[1].split('def _group_options_for_history',1)[0]
    assert route.index('if qp.get("__load") != "1":') < route.index('    rows = db.scalars(')
    assert 'board_deferred=True' in route and 'board_deferred=False' in route
    assert 'AcceptedQuote.user_id == user_filter' in route
    assert 'AcceptedQuote.selected_at >= datetime.combine' in route


def test_board_renderiza_por_lotes_e_preserva_interacoes():
    page = text("app/templates/cadastros/cotacoes.html")
    assert 'board-lane-skeleton' in page
    assert 'loadBoardProgressively' in page
    assert "appendBatch()" in page
    assert "board.addEventListener('dragstart'" in page
    assert 'data-load-more' in page
    assert 'Carregar mais 10' in page


def test_diagnostico_e_sessao_protegida():
    code = text("app/routers/performance.py")
    page = text("app/templates/diagnostics/performance.html")
    assert 'require_user(request, db)' in code
    assert 'credentials:\'same-origin\'' in page
    assert 'AbortController' in page
    assert 'Copiar relatório' in page
    assert 'navigator.clipboard.writeText' in page
