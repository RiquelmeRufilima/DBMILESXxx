from pathlib import Path
from app.services.airline_logos import logo_from_name

ROOT = Path(__file__).resolve().parents[1]

def test_voepass_image_is_deployable():
    image = ROOT / "app" / "imagens" / "voepass.png"
    assert image.is_file() and image.stat().st_size > 1000
    assert logo_from_name("Voepass") == "/imagens/voepass.png"
    assert logo_from_name("Passaredo") == "/imagens/voepass.png"

def test_light_overrides_scoped_and_inside_style():
    calculator = (ROOT / "app/templates/calculations/new.html").read_text()
    board = (ROOT / "app/templates/cadastros/cotacoes.html").read_text()
    for page in (calculator, board):
        head = page.split("<style>", 1)[1].split("</style>", 1)[0]
        assert 'html[data-theme="light"]' in head
    assert '.quote-base-summary .summary-grid > div' in calculator
    assert '.quotes-board-page .quote-kanban-card' in board
