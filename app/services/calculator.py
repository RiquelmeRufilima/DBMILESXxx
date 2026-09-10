from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..models import Airline, CalculationType
from .formula_engine import evaluate_formula


@dataclass
class CalculationResult:
    base: float
    baggage_total: float
    extra_total: float
    total: float
    breakdown: dict[str, Any]


def _num(values: dict[str, Any], key: str, default: float = 0.0) -> float:
    value = values.get(key, default)
    if value is None or value == "":
        return float(default)
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(" ", "")
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return float(default)


def _legacy_calculation(
    key: str,
    values: dict[str, Any],
    passengers: int,
    bags: int,
    extra_name: str,
    extra_value: float,
) -> CalculationResult:
    milhas = _num(values, "milhas")
    milheiro = _num(values, "milheiro")
    taxa = _num(values, "taxa")
    bag_fee = _num(values, "bagagem_unitaria")
    base = 0.0
    baggage_total = bags * bag_fee
    details: dict[str, Any] = {}

    # Fórmulas abaixo reproduzem a lógica da calculadora Streamlit original.
    if key == "latam_milhas":
        value_miles = (milhas * milheiro) * passengers
        value_fees = taxa * passengers
        base = value_miles + value_fees
        details = {
            "milhas_por_passageiro": milhas,
            "valor_milhas": value_miles,
            "taxas_por_passageiro": taxa,
            "valor_taxas": value_fees,
            "modo": "por_passageiro",
        }

    elif key == "gol_smiles":
        value_miles = milhas * milheiro
        base = value_miles + taxa
        details = {"valor_milhas": value_miles, "valor_taxas": taxa, "modo": "total"}

    elif key == "gol_desagio":
        full_value = _num(values, "valor_gol")
        discount_percent = _num(values, "desagio")
        discount = full_value * (discount_percent / 100)
        base = full_value - discount
        details = {
            "valor_cheio": full_value,
            "desagio_percentual": discount_percent,
            "desconto": discount,
            "modo": "total",
        }

    elif key == "azul_pontos":
        value_points = milhas * milheiro
        base = value_points + taxa
        details = {"valor_pontos": value_points, "valor_taxas": taxa, "modo": "total"}

    elif key in {"azul_pontos_dinheiro", "azulpelomundo_pontos_dinheiro"}:
        value_points = milhas * milheiro
        cash_original = _num(values, "valor_dinheiro")
        fee_discount_percent = _num(values, "desconto_taxa", 10)
        cash_discounted = cash_original * (1 - (fee_discount_percent / 100))
        taxes = _num(values, "taxas_impostos")
        redemption_fee = _num(values, "taxa_resgate_por_pax_trecho", 60)
        segments = int(_num(values, "numero_trechos", 1))
        redemption_total = redemption_fee * passengers * segments
        total_fees = cash_discounted + taxes + redemption_total
        base = value_points + total_fees
        details = {
            "valor_pontos": value_points,
            "taxa_dinheiro_original": cash_original,
            "desconto_taxa_percentual": fee_discount_percent,
            "taxa_dinheiro_com_desconto": cash_discounted,
            "taxa_impostos": taxes,
            "taxa_resgate_por_pax_trecho": redemption_fee,
            "numero_trechos": segments,
            "taxa_resgate_total": redemption_total,
            "valor_taxas_total": total_fees,
            "modo": "total",
        }

    elif key == "american_milhas":
        value_miles = milhas * milheiro
        base = value_miles + taxa
        route = str(values.get("rota_american") or "Brasil ↔ EUA")
        details = {
            "valor_milhas": value_miles,
            "valor_taxas": taxa,
            "rota": route,
            "modo": "total",
        }

    elif key == "azulpelomundo_pontos":
        value_points = milhas * milheiro
        base = value_points + taxa
        details = {"valor_pontos": value_points, "valor_taxas": taxa, "modo": "total"}

    else:
        raise ValueError(f"Tipo de cálculo legado não reconhecido: {key}")

    extra_total = max(0.0, float(extra_value or 0.0))
    total = base + baggage_total + extra_total
    details.update(
        {
            "valor_base": round(base, 2),
            "bagagens": bags,
            "bagagem_unitaria": round(bag_fee, 2),
            "valor_bagagens": round(baggage_total, 2),
            "custo_adicional_nome": extra_name if extra_total > 0 else None,
            "custo_adicional_valor": round(extra_total, 2),
        }
    )
    return CalculationResult(
        base=round(base, 2),
        baggage_total=round(baggage_total, 2),
        extra_total=round(extra_total, 2),
        total=round(total, 2),
        breakdown=details,
    )


def calculate(
    airline: Airline,
    calculation_type: CalculationType,
    values: dict[str, Any],
    passengers: int,
    babies: int,
    bags: int,
    extra_name: str = "",
    extra_value: float = 0.0,
) -> CalculationResult:
    passengers = max(1, int(passengers or 1))
    babies = max(0, int(babies or 0))
    bags = max(0, int(bags or 0))

    values = dict(values)
    values.update(
        {
            "passageiros": passengers,
            "bebes": babies,
            "bagagens": bags,
        }
    )

    if airline.engine_type == "legacy" and calculation_type.legacy_key:
        return _legacy_calculation(
            calculation_type.legacy_key,
            values,
            passengers,
            bags,
            extra_name,
            extra_value,
        )

    base = evaluate_formula(calculation_type.formula, values)
    if calculation_type.apply_mode == "per_passenger":
        base *= passengers

    extra_total = max(0.0, float(extra_value or 0.0))
    total = base + extra_total
    breakdown = {
        "formula": calculation_type.formula,
        "modo": calculation_type.apply_mode,
        "resultado_formula": round(base, 2),
        "variaveis": values,
        "custo_adicional_nome": extra_name if extra_total > 0 else None,
        "custo_adicional_valor": round(extra_total, 2),
        "valor_base": round(base, 2),
        "valor_bagagens": 0.0,
    }
    return CalculationResult(
        base=round(base, 2),
        baggage_total=0.0,
        extra_total=round(extra_total, 2),
        total=round(base + extra_total, 2),
        breakdown=breakdown,
    )
