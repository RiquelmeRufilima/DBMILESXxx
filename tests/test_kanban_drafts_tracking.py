"""Regressões de navegação do quadro e da edição; não depende do banco Neon."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'app' / 'templates' / 'cadastros'


def test_board_optimistic_without_reload():
    page = (ROOT / 'cotacoes.html').read_text()
    assert 'zone.appendChild(card)' in page
    assert 'updateLane(source)' in page
    assert 'if (!response.ok || result.ok !== true)' in page
    assert 'source.insertBefore(card, sibling)' in page
    assert 'location.reload()' not in page


def test_status_changes_do_not_post_or_reload():
    page = (ROOT / 'cotacao_form.html').read_text()
    status_handler = page.split('// Trocar fase não envia o formulário')[1].split("document.getElementById('clientName')")[0]
    assert "addEventListener('click'" in status_handler
    assert 'statusDraftNote.hidden = false' in status_handler
    assert 'fetch(' not in status_handler
    assert 'location.reload' not in status_handler
    assert 'statusField' in page


def test_tracking_reuses_existing_quote_editor():
    tracking = (ROOT / 'service_tracking.html').read_text()
    quote_form = (ROOT / 'cotacao_form.html').read_text()
    assert 'service_index={{ item.index }}' in tracking
    assert 'data-tab="orcamento"' in quote_form
    assert 'openServiceModal(serviceKey, index)' in quote_form


def test_neutral_board_theme():
    page = (ROOT / 'cotacoes.html').read_text()
    assert '.quotes-board-page .kanban-column{background:var(--panel)' in page
