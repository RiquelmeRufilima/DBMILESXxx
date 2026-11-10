from types import SimpleNamespace as NS

from app.routers.calculations import _calculation_method_label


def _q(airline, calc):
    return NS(airline=NS(name=airline), calculation_type=NS(name=calc))


def test_desagio_da_gol_mostra_o_tipo_de_calculo():
    assert _calculation_method_label(_q("GOL Linhas Aéreas", "Deságio")) == "Deságio"


def test_milhas_continuam_com_nome_do_programa():
    assert _calculation_method_label(_q("GOL Linhas Aéreas", "Smiles (Milhas)")) == "Smiles"
    assert _calculation_method_label(_q("LATAM Airlines", "Milhas LATAM Pass")) == "LATAM Pass"
    assert _calculation_method_label(_q("Azul Linhas Aéreas", "Pontos + Dinheiro")) == "Azul Pontos + Dinheiro"
