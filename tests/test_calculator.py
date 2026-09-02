from types import SimpleNamespace

from app.services.calculator import calculate
from app.services.formula_engine import evaluate_formula


def legacy(key):
    airline = SimpleNamespace(engine_type="legacy")
    calc = SimpleNamespace(legacy_key=key, formula="", apply_mode="total")
    return airline, calc


def test_latam_is_per_passenger():
    airline, calc = legacy("latam_milhas")
    result = calculate(airline, calc, {"milhas": 10, "milheiro": 20, "taxa": 50, "bagagem_unitaria": 140}, 3, 0, 2)
    assert result.base == 750
    assert result.baggage_total == 280
    assert result.total == 1030


def test_gol_smiles_is_total():
    airline, calc = legacy("gol_smiles")
    result = calculate(airline, calc, {"milhas": 30, "milheiro": 15, "taxa": 100, "bagagem_unitaria": 175}, 4, 0, 1)
    assert result.base == 550
    assert result.total == 725


def test_gol_discount():
    airline, calc = legacy("gol_desagio")
    result = calculate(airline, calc, {"valor_gol": 1000, "desagio": 20, "bagagem_unitaria": 175}, 2, 0, 0)
    assert result.base == 800


def test_azul_points_money():
    airline, calc = legacy("azul_pontos_dinheiro")
    result = calculate(
        airline,
        calc,
        {
            "milhas": 45.6,
            "milheiro": 16,
            "valor_dinheiro": 3780,
            "desconto_taxa": 10,
            "taxas_impostos": 232.68,
            "taxa_resgate_por_pax_trecho": 60,
            "numero_trechos": 2,
            "bagagem_unitaria": 175,
        },
        2,
        0,
        0,
    )
    expected = (45.6 * 16) + (3780 * 0.9) + 232.68 + (60 * 2 * 2)
    assert result.total == round(expected, 2)


def test_safe_formula_engine():
    result = evaluate_formula("((milhas * milheiro) + taxa) * (1 - desconto / 100)", {"milhas": 10, "milheiro": 20, "taxa": 50, "desconto": 10})
    assert result == 225
