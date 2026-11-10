from types import SimpleNamespace as NS

from app.routers.calculations import _art_operator


def test_arte_usa_a_companhia_que_opera():
    q = NS(segment_partner_airlines=[{"name": "LATAM Airlines", "logo_path": "imagens/latam.png"}, {"name": "LATAM Airlines", "logo_path": ""}], partner_airline="")
    assert _art_operator(q) == {"name": "LATAM Airlines", "logo": "/imagens/latam.png"}


def test_trechos_com_companhias_diferentes():
    q = NS(segment_partner_airlines=[{"name": "GOL", "logo_path": "imagens/gol2.png"}, {"name": "Azul", "logo_path": "imagens/azul.png"}], partner_airline="")
    assert _art_operator(q) == {"name": "GOL + Azul", "logo": "/imagens/gol2.png"}


def test_sem_operadora_nao_mostra_o_fornecedor():
    q = NS(segment_partner_airlines=[], partner_airline="")
    assert _art_operator(q) == {"name": "", "logo": ""}
