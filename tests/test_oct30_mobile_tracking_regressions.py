"""Teste de regressões de interface e do quadro de cotações - 30/10."""
from pathlib import Path

from app.web import templates

ROOT = Path(__file__).resolve().parents[1]


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_templates_compilam_e_preservam_acompanhamentos():
    for name in (
        "cadastros/cotacoes.html",
        "cadastros/service_tracking.html",
        "cadastros/cotacao_form.html",
        "calculations/history.html",
        "partials/tags.html",
    ):
        assert templates.env.get_template(name) is not None


def test_quadro_nao_insere_cotacao_nao_aceita_na_espera():
    route = read("app/routers/cadastros.py")
    section = route.split('def cotacoes(request: Request', 1)[1].split('def _group_options_for_history', 1)[0]
    assert 'cards.append({"item": item, "accepted": True' in section
    assert '"accepted": False' not in section


def test_mobile_exibe_faixas_verticais_e_dez_por_vez():
    html = read("app/templates/cadastros/cotacoes.html")
    assert 'flex-direction:column!important' in html
    assert 'data-load-more' in html
    assert 'data-page-size="10"' in html
    assert 'const current=initial?10' in html


def test_hospedagem_tem_classificacao_visual_e_acao_editar():
    html = read("app/templates/cadastros/service_tracking.html")
    assert 'tracking-hotel-stars' in html
    assert 'range(stars)' in html
    assert 'service_index={{ item.index }}' in html


def test_criacao_etiqueta_visivel_sem_perder_ja_existentes():
    dialog = read("app/templates/partials/tags.html")
    script = read("app/static/js/tags.js")
    assert 'id="tagCreateButton"' in dialog
    assert 'Nova etiqueta' in script
    assert 'tag_ids: [...selected]' in script


def test_estilos_do_tema_escuro_nao_foram_substituidos():
    css = read("app/static/css/dbm-light-and-compact-20261030.css")
    assert 'html[data-theme="light"] .accepted-editor .itinerary-pro-panel' in css
    assert 'html[data-theme="light"] .calc-flow-page .flow-summary-card' in css
