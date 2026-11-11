"""Pacotes em Acompanhamentos, comissão (lucro) e seguradoras."""
from __future__ import annotations

from pathlib import Path

from app.routers import cadastros, service_tracking as st

ROOT = Path(__file__).resolve().parents[1] / "app"


def test_aba_pacotes_registrada():
    assert st.KINDS["pacotes"] == ("package", "Pacotes")
    assert "package" in st.EMPTY_SERVICES and st.SERVICE_LABELS["pacotes"] == "Pacote"
    # Etiquetas de pacotes não colidem com as de outros tipos.
    ids = {st._service_tag_id(10, kind, 3) for kind in st.KINDS}
    assert len(ids) == len(st.KINDS)
    assert "Pacote" in cadastros.COST_CATEGORIES and "Venda de Pacote" in cadastros.SALE_CATEGORIES
    assert 'href="/acompanhamentos/pacotes"' in (ROOT / "templates" / "base.html").read_text()


def test_editor_tem_pacote_comissao_e_seguradora():
    form = (ROOT / "templates" / "cadastros" / "cotacao_form.html").read_text()
    assert '{% include "cadastros/_pacote_comissao.html" %}' in form
    assert "package-commission-20261111.js" in form and "openPackageModal()" in form
    assert form.index("package-commission-20261111.js") < form.index("const initialData = readJsonData(")
    partial = (ROOT / "templates" / "cadastros" / "_pacote_comissao.html").read_text()
    assert 'data-insurer="Universal Assistance"' in partial and 'commission_box("pkg"' in partial
    assert (ROOT / "static" / "brand" / "seguros" / "universal-assistance.png").is_file()


def test_js_lanca_comissao_no_lugar_certo_sem_duplicar():
    js = (ROOT / "static" / "js" / "package-commission-20261111.js").read_text()
    # operadora recebe → Recebimento de comissão; agência → venda + custo líquido
    assert "commission.receive.push({ref" in js and "saleItems.push({ref" in js and "costItems.push({ref" in js
    assert "clearFinance(ref);" in js and "removeLinked(id);" in js
    # o nome da operadora não vai para o texto que aparece no PDF do cliente
    assert "const note = `Incluído no pacote ${name}.`;" in js


def test_lista_de_pacotes_mostra_inclusos():
    html = (ROOT / "templates" / "cadastros" / "service_tracking.html").read_text()
    assert "kind == 'pacotes'" in html and "startswith('/static/brand/seguros/')" in html
