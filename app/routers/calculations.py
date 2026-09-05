from __future__ import annotations

import json
import logging
import re
import unicodedata
import uuid
from datetime import datetime
from typing import Any
from types import SimpleNamespace

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import delete, desc, func, inspect, literal, or_, select, union_all
from sqlalchemy.orm import Session, selectinload

from ..database import get_db, engine
from ..dependencies import current_user
from ..models import (
    Airline,
    AcceptedQuote,
    FlightRegistry,
    CalculationField,
    CalculationType,
    QuoteCommercial,
    QuoteActivity,
    QuoteGroup,
    QuoteGroupTripDetail,
    QuoteOptionIndex,
    QuoteRequest,
    Person,
    QuoteTripDetail,
    WebQuote,
    WebUser,
)
from ..security import validate_csrf_token
from ..services.calculator import CalculationResult, calculate
from ..services.travel_data import BR_AIRPORTS
from ..services.schema_migrations import ensure_runtime_schema
from ..services.quote_activity import record_quote_activity, publish_quote_activity
from ..web import context, flash, templates

router = APIRouter(prefix="/calculations", tags=["calculations"])
logger = logging.getLogger(__name__)
_ACTIVITY_TABLE_AVAILABLE: bool | None = None


# Campos que devem aparecer na tela de cálculo quando o banco veio de uma versão
# anterior e os campos da companhia ainda não foram criados em web_calculation_fields.
DEFAULT_FIELD_DEFINITIONS: dict[str, list[dict[str, Any]]] = {
    "latam_milhas": [
        {"key": "milhas", "label": "Milhas necessárias por passageiro", "field_type": "number", "default_value": "0", "min_value": 0, "step": 0.001},
        {"key": "milheiro", "label": "Valor do milheiro", "field_type": "number", "default_value": "0", "min_value": 0, "step": 0.01},
        {"key": "taxa", "label": "Taxa de embarque por passageiro", "field_type": "number", "default_value": "0", "min_value": 0, "step": 0.01},
        {"key": "bagagem_unitaria", "label": "Bagagem adicional por unidade", "field_type": "number", "default_value": "140", "min_value": 0, "step": 1},
    ],
    "gol_smiles": [
        {"key": "milhas", "label": "Milhas Smiles necessárias", "field_type": "number", "default_value": "0", "min_value": 0, "step": 0.001},
        {"key": "milheiro", "label": "Valor do milheiro", "field_type": "number", "default_value": "0", "min_value": 0, "step": 0.01},
        {"key": "taxa", "label": "Taxa de embarque", "field_type": "number", "default_value": "0", "min_value": 0, "step": 0.01},
        {"key": "bagagem_unitaria", "label": "Bagagem adicional por unidade", "field_type": "number", "default_value": "175", "min_value": 0, "step": 1},
    ],
    "gol_desagio": [
        {"key": "valor_gol", "label": "Valor cheio da passagem", "field_type": "number", "default_value": "0", "min_value": 0, "step": 0.01},
        {"key": "desagio", "label": "Percentual de deságio", "field_type": "percent", "default_value": "0", "min_value": 0, "max_value": 100, "step": 1},
        {"key": "bagagem_unitaria", "label": "Bagagem adicional por unidade", "field_type": "number", "default_value": "175", "min_value": 0, "step": 1},
    ],
    "azul_pontos": [
        {"key": "milhas", "label": "Pontos/Milhas totais em milheiros", "field_type": "number", "default_value": "0", "min_value": 0, "step": 0.001},
        {"key": "milheiro", "label": "Valor do milheiro", "field_type": "number", "default_value": "0", "min_value": 0, "step": 0.01},
        {"key": "taxa", "label": "Taxa de embarque", "field_type": "number", "default_value": "0", "min_value": 0, "step": 0.01},
        {"key": "bagagem_unitaria", "label": "Bagagem adicional por unidade", "field_type": "number", "default_value": "175", "min_value": 0, "step": 1},
    ],
    "azul_pontos_dinheiro": [
        {"key": "milhas", "label": "Pontos/Milhas totais em milheiros", "field_type": "number", "default_value": "0", "min_value": 0, "step": 0.001},
        {"key": "milheiro", "label": "Valor do milheiro", "field_type": "number", "default_value": "0", "min_value": 0, "step": 0.01},
        {"key": "valor_dinheiro", "label": "Valor em dinheiro", "field_type": "number", "default_value": "0", "min_value": 0, "step": 0.01},
        {"key": "desconto_taxa", "label": "Desconto no valor em dinheiro (%)", "field_type": "percent", "default_value": "10", "min_value": 0, "max_value": 100, "step": 1},
        {"key": "taxas_impostos", "label": "Taxas e impostos", "field_type": "number", "default_value": "0", "min_value": 0, "step": 0.01},
        {"key": "taxa_resgate_por_pax_trecho", "label": "Taxa de resgate por pax/trecho", "field_type": "number", "default_value": "60", "min_value": 0, "step": 1},
        {"key": "numero_trechos", "label": "Número de trechos", "field_type": "integer", "default_value": "1", "min_value": 1, "max_value": 20, "step": 1},
        {"key": "bagagem_unitaria", "label": "Bagagem adicional por unidade", "field_type": "number", "default_value": "175", "min_value": 0, "step": 1},
    ],
    "american_milhas": [
        {"key": "milhas", "label": "Milhas AAdvantage necessárias", "field_type": "number", "default_value": "0", "min_value": 0, "step": 0.001},
        {"key": "milheiro", "label": "Valor do milheiro", "field_type": "number", "default_value": "0", "min_value": 0, "step": 0.01},
        {"key": "taxa", "label": "Taxa de embarque", "field_type": "number", "default_value": "0", "min_value": 0, "step": 0.01},
        {"key": "rota_american", "label": "Tipo de rota", "field_type": "select", "default_value": "Brasil ↔ EUA", "options_json": json.dumps(["Brasil ↔ EUA", "EUA / Canadá / Caribe / México", "América do Sul ↔ EUA", "EUA ↔ Panamá / Colômbia / Peru / Equador"], ensure_ascii=False)},
    ],
    "azulpelomundo_pontos": [
        {"key": "milhas", "label": "Pontos/Milhas totais em milheiros", "field_type": "number", "default_value": "0", "min_value": 0, "step": 0.001},
        {"key": "milheiro", "label": "Valor do milheiro", "field_type": "number", "default_value": "0", "min_value": 0, "step": 0.01},
        {"key": "taxa", "label": "Taxa de embarque", "field_type": "number", "default_value": "0", "min_value": 0, "step": 0.01},
        {"key": "bagagem_unitaria", "label": "Bagagem adicional por unidade", "field_type": "number", "default_value": "175", "min_value": 0, "step": 1},
    ],
    "azulpelomundo_pontos_dinheiro": [
        {"key": "milhas", "label": "Pontos/Milhas totais em milheiros", "field_type": "number", "default_value": "0", "min_value": 0, "step": 0.001},
        {"key": "milheiro", "label": "Valor do milheiro", "field_type": "number", "default_value": "0", "min_value": 0, "step": 0.01},
        {"key": "valor_dinheiro", "label": "Valor em dinheiro", "field_type": "number", "default_value": "0", "min_value": 0, "step": 0.01},
        {"key": "desconto_taxa", "label": "Desconto no valor em dinheiro (%)", "field_type": "percent", "default_value": "10", "min_value": 0, "max_value": 100, "step": 1},
        {"key": "taxas_impostos", "label": "Taxas e impostos", "field_type": "number", "default_value": "0", "min_value": 0, "step": 0.01},
        {"key": "taxa_resgate_por_pax_trecho", "label": "Taxa de resgate por pax/trecho", "field_type": "number", "default_value": "60", "min_value": 0, "step": 1},
        {"key": "numero_trechos", "label": "Número de trechos", "field_type": "integer", "default_value": "1", "min_value": 1, "max_value": 20, "step": 1},
        {"key": "bagagem_unitaria", "label": "Bagagem adicional por unidade", "field_type": "number", "default_value": "175", "min_value": 0, "step": 1},
    ],
}

FORMULA_RESERVED_NAMES = {"passageiros", "bebes", "bagagens", "min", "max", "round", "abs"}


def _field_label(key: str) -> str:
    labels = {
        "milhas": "Milhas/Pontos",
        "milheiro": "Valor do milheiro",
        "taxa": "Taxa",
        "desconto": "Desconto (%)",
        "juros": "Juros (%)",
        "taxa_adicional": "Taxa adicional",
        "desconto_taxa": "Desconto da taxa (%)",
        "valor_dinheiro": "Valor em dinheiro",
        "taxa_resgate": "Taxa de resgate",
        "taxa_resgate_por_pax_trecho": "Taxa de resgate por pax/trecho",
        "numero_trechos": "Número de trechos",
    }
    return labels.get(key, key.replace("_", " ").title())


def _default_field_definitions(calc_type: CalculationType) -> list[dict[str, Any]]:
    if calc_type.legacy_key and calc_type.legacy_key in DEFAULT_FIELD_DEFINITIONS:
        return DEFAULT_FIELD_DEFINITIONS[calc_type.legacy_key]

    formula = calc_type.formula or "(milhas * milheiro) + taxa"
    keys = []
    for key in re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", formula):
        if key not in FORMULA_RESERVED_NAMES and key not in keys:
            keys.append(key)
    if not keys:
        keys = ["milhas", "milheiro", "taxa"]
    return [
        {
            "key": key,
            "label": _field_label(key),
            "field_type": "percent" if key in {"desconto", "juros", "desconto_taxa"} else ("integer" if key in {"numero_trechos"} else "number"),
            "default_value": "1" if key == "numero_trechos" else "0",
            "min_value": 0,
            "max_value": 100 if key in {"desconto", "juros", "desconto_taxa"} else None,
            "step": 1 if key == "numero_trechos" else 0.01,
        }
        for key in keys
    ]


def _as_field_spec(definition: dict[str, Any], index: int) -> SimpleNamespace:
    return SimpleNamespace(
        key=definition.get("key"),
        label=definition.get("label") or _field_label(str(definition.get("key") or "campo")),
        field_type=definition.get("field_type") or "number",
        default_value=definition.get("default_value") if definition.get("default_value") is not None else "0",
        required=bool(definition.get("required", False)),
        min_value=definition.get("min_value"),
        max_value=definition.get("max_value"),
        step=definition.get("step"),
        help_text=definition.get("help_text"),
        options_json=definition.get("options_json"),
        order_index=index,
    )


def _effective_calculation_fields(db: Session, calc_type: CalculationType | None) -> list[Any]:
    """Garante que os campos de cálculo apareçam mesmo em bancos V5 antigos.

    Algumas instalações ficaram com a tabela web_calculation_types criada, mas sem
    os registros de web_calculation_fields. Sem isso a tela mostrava o card da
    companhia, porém não exibia os parâmetros para digitar milhas, milheiro, taxa etc.
    """
    if calc_type is None:
        return []
    existing = list(calc_type.fields or [])
    if existing:
        return existing

    created_fields: list[CalculationField] = []
    for index, definition in enumerate(_default_field_definitions(calc_type)):
        field = CalculationField(
            calculation_type_id=calc_type.id,
            key=str(definition.get("key") or f"campo_{index + 1}"),
            label=str(definition.get("label") or _field_label(str(definition.get("key") or f"campo_{index + 1}"))),
            field_type=str(definition.get("field_type") or "number"),
            default_value=str(definition.get("default_value") if definition.get("default_value") is not None else "0"),
            required=bool(definition.get("required", False)),
            min_value=definition.get("min_value"),
            max_value=definition.get("max_value"),
            step=definition.get("step"),
            help_text=definition.get("help_text"),
            options_json=definition.get("options_json"),
            order_index=index,
        )
        db.add(field)
        created_fields.append(field)
    db.flush()
    calc_type.fields = created_fields
    return created_fields or [_as_field_spec(definition, index) for index, definition in enumerate(_default_field_definitions(calc_type))]


def _visible_airlines_query(user):
    if user.company_id:
        return select(Airline).where(
            Airline.active.is_(True),
            or_(Airline.builtin.is_(True), Airline.owner_company_id == user.company_id),
        )
    return select(Airline).where(
        Airline.active.is_(True),
        or_(Airline.builtin.is_(True), Airline.owner_user_id == user.id),
    )


def _quote_allowed(user, quote: WebQuote | None) -> bool:
    return bool(quote and (quote.user_id == user.id or (user.company_id and quote.company_id == user.company_id)))


def _group_allowed(user, group: QuoteGroup | None) -> bool:
    return bool(group and (group.user_id == user.id or (user.company_id and group.company_id == user.company_id)))


def _request_allowed(user, item: QuoteRequest | None) -> bool:
    return bool(item and (item.owner_user_id == user.id or (user.company_id and item.company_id == user.company_id)))


def _person_allowed(user, item: Person | None) -> bool:
    return bool(item and item.active and (item.user_id == user.id or (user.company_id and item.company_id == user.company_id)))


def _safe_json(raw: str | None, default):
    try:
        value = json.loads(raw or "")
        return value
    except Exception:
        return default


def _normalized_token(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "_", text.casefold()).strip("_")


def _normalize_travel_type(value: Any, *, segments: Any = None, return_date: Any = None) -> str:
    """Aceita nomes antigos/portugueses e devolve o tipo canônico.

    Algumas versões salvaram ``somente ida``, ``ida-volta`` ou valores vazios.
    A normalização evita que os cards Skip e as subcotações desapareçam.
    """
    token = _normalized_token(value)
    aliases = {
        "one_way": "one_way", "oneway": "one_way", "one_way_trip": "one_way",
        "so_ida": "one_way", "somente_ida": "one_way", "ida": "one_way",
        "round_trip": "round_trip", "roundtrip": "round_trip",
        "ida_e_volta": "round_trip", "ida_volta": "round_trip", "ida_mais_volta": "round_trip",
        "multi_city": "multi_city", "multicity": "multi_city", "multitrecho": "multi_city",
        "multi_trecho": "multi_city", "varios_trechos": "multi_city",
    }
    if token in aliases:
        return aliases[token]
    raw_segments = segments
    if isinstance(raw_segments, str):
        raw_segments = _safe_json(raw_segments, [])
    valid_segments = [item for item in (raw_segments or []) if isinstance(item, dict)] if isinstance(raw_segments, list) else []
    if len(valid_segments) > 2:
        return "multi_city"
    if len(valid_segments) == 2:
        first, second = valid_segments
        first_o, first_d = _clean_code(first.get("origin")), _clean_code(first.get("destination"))
        second_o, second_d = _clean_code(second.get("origin")), _clean_code(second.get("destination"))
        if first_o and first_d and first_o == second_d and first_d == second_o:
            return "round_trip"
        return "multi_city"
    if str(return_date or "").strip():
        return "round_trip"
    return "one_way"


def _blank_base() -> dict[str, Any]:
    return {
        "group_id": None,
        "quote_name": "Nova cotação",
        "origin": "",
        "destination": "",
        "passengers": 1,
        "babies": 0,
        "bags": 0,
        "travel_type": "round_trip",
        "departure_date": "",
        "return_date": "",
        "flexibility_days": 0,
        "segments": [],
        "client_person_id": None,
        "client_name": "",
        "client_email": "",
        "client_phone": "",
        "notes": "",
        "source_request_id": None,
        "mode": "new_base",
    }


def _stored_group_variants(group: QuoteGroup | None) -> list[dict[str, Any]]:
    """Lê as subcotações salvas sem deixar JSON antigo derrubar a tela."""
    if group is None or group.trip is None:
        return []
    raw = _safe_json(getattr(group.trip, "variants_json", "[]"), [])
    if not isinstance(raw, list):
        return []
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for idx, item in enumerate(raw[:30]):
        if not isinstance(item, dict):
            continue
        key = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(item.get("key") or f"sub-{idx+1}")).strip("-")[:60]
        if not key or key in seen or key == "primary":
            continue
        seen.add(key)
        segments = item.get("segments") if isinstance(item.get("segments"), list) else []
        travel_type = _normalize_travel_type(
            item.get("travel_type"), segments=segments, return_date=item.get("return_date")
        )
        normalized_variant_segments = [dict(seg) for seg in segments if isinstance(seg, dict)][:12] if travel_type == "multi_city" else []
        try:
            variant_passengers = max(1, min(100, int(item.get("passengers") or group.passengers or 1)))
        except (TypeError, ValueError):
            variant_passengers = max(1, min(100, int(group.passengers or 1)))
        try:
            variant_babies = max(0, min(100, int(item.get("babies") if item.get("babies") is not None else (group.babies or 0))))
        except (TypeError, ValueError):
            variant_babies = max(0, min(100, int(group.babies or 0)))
        result.append({
            "key": key,
            "name": str(item.get("name") or f"Subcotação {len(result)+1}").strip()[:120] or f"Subcotação {len(result)+1}",
            "origin": _clean_code(item.get("origin")),
            "destination": _clean_code(item.get("destination")),
            "passengers": variant_passengers,
            "babies": variant_babies,
            "travel_type": travel_type,
            "departure_date": _clean_date_value(item.get("departure_date")),
            "return_date": "" if travel_type == "one_way" else _clean_date_value(item.get("return_date")),
            "flexibility_days": max(0, min(30, int(item.get("flexibility_days") or 0))) if str(item.get("flexibility_days") or "0").lstrip("-").isdigit() else 0,
            "segments": normalized_variant_segments,
        })
    return result


def _group_variant_cards(group: QuoteGroup | None) -> list[dict[str, Any]]:
    if group is None:
        return []
    trip = group.trip
    primary = {
        "key": "primary",
        "name": "Cotação principal",
        "origin": group.origin or "",
        "destination": group.destination or "",
        "passengers": max(1, int(group.passengers or 1)),
        "babies": max(0, int(group.babies or 0)),
        "travel_type": _normalize_travel_type(
            trip.travel_type if trip else "round_trip",
            segments=_safe_json(trip.segments_json, []) if trip else [],
            return_date=trip.return_date if trip else None,
        ),
        "departure_date": trip.departure_date if trip else "",
        "return_date": trip.return_date if trip else "",
        "flexibility_days": max(0, int(getattr(trip, "flexibility_days", 0) or 0)) if trip else 0,
        "segments": _safe_json(trip.segments_json, []) if trip else [],
        "is_primary": True,
    }
    variants = [primary]
    for item in _stored_group_variants(group):
        variant = dict(item)
        variant["is_primary"] = False
        variants.append(variant)
    return variants


def _ensure_group_trip_detail(db: Session, group: QuoteGroup) -> QuoteGroupTripDetail:
    """Garante que grupos antigos também possam receber subcotações.

    O método também normaliza campos nulos deixados por versões anteriores, sem
    alterar cotações ou opções já existentes.
    """
    if group.trip is not None:
        trip = group.trip
        if not getattr(trip, "travel_type", None):
            trip.travel_type = _normalize_travel_type(None)
        if not getattr(trip, "segments_json", None):
            trip.segments_json = "[]"
        if not getattr(trip, "variants_json", None):
            trip.variants_json = "[]"
        if getattr(trip, "flexibility_days", None) is None:
            trip.flexibility_days = 0
        db.flush()
        return trip
    trip = QuoteGroupTripDetail(
        group_id=group.id,
        travel_type="one_way",
        departure_date=None,
        return_date=None,
        segments_json="[]",
        variants_json="[]",
        flexibility_days=0,
    )
    db.add(trip)
    group.trip = trip
    db.flush()
    return trip


def _recover_group_route_from_options(db: Session, user: WebUser, group: QuoteGroup, options: list[WebQuote] | None = None) -> bool:
    """Recupera apenas rotas vazias usando uma opção já calculada.

    Não substitui dados existentes e não remove nenhuma informação. Serve para
    cotações antigas que ficaram com origem/destino em branco.
    """
    current_origin = _required_iata_code(group.origin)
    current_destination = _required_iata_code(group.destination)
    if current_origin and current_destination:
        return False
    candidates = options if options is not None else _load_options(db, user, group.id)
    for quote in candidates:
        origin = _required_iata_code(getattr(quote, "origin", ""))
        destination = _required_iata_code(getattr(quote, "destination", ""))
        if not (origin and destination):
            continue
        if not current_origin:
            group.origin = origin
        if not current_destination:
            group.destination = destination
        trip = _ensure_group_trip_detail(db, group)
        if not trip.travel_type:
            trip.travel_type = "one_way"
        db.flush()
        return True
    return False


def _base_from_group(group: QuoteGroup, variant_key: str | None = None) -> dict[str, Any]:
    trip = group.trip
    variants = _group_variant_cards(group)
    wanted = str(variant_key or "primary").strip() or "primary"
    selected = next((item for item in variants if item.get("key") == wanted), variants[0] if variants else None)
    selected = selected or {
        "key": "primary", "name": "Cotação principal", "origin": group.origin or "",
        "destination": group.destination or "", "travel_type": "round_trip",
        "departure_date": "", "return_date": "", "flexibility_days": 0, "segments": [], "is_primary": True,
    }
    selected_segments = selected.get("segments") if isinstance(selected.get("segments"), list) else []
    selected_origin = selected.get("origin") or group.origin or ""
    selected_destination = selected.get("destination") or group.destination or ""
    selected_travel_type = _normalize_travel_type(
        selected.get("travel_type"),
        segments=selected_segments,
        return_date=selected.get("return_date"),
    )
    return {
        "group_id": group.id,
        "quote_name": group.quote_name,
        "origin": selected_origin,
        "destination": selected_destination,
        "passengers": max(1, int(selected.get("passengers") if selected.get("passengers") is not None else (group.passengers or 1))),
        "babies": max(0, int(selected.get("babies") if selected.get("babies") is not None else (group.babies or 0))),
        "bags": group.bags,
        "travel_type": selected_travel_type,
        "departure_date": selected.get("departure_date") or "",
        "return_date": selected.get("return_date") or "",
        "flexibility_days": max(0, int(selected.get("flexibility_days") or 0)),
        "segments": selected_segments,
        "client_person_id": trip.client_person_id if trip else None,
        "client_name": trip.client_name if trip else "",
        "client_email": trip.client_email if trip else "",
        "client_phone": trip.client_phone if trip else "",
        "notes": trip.notes if trip else "",
        "source_request_id": group.source_request_id,
        "mode": "group",
        "variant_key": selected.get("key") or "primary",
        "variant_name": selected.get("name") or "Cotação principal",
        "is_primary_variant": bool(selected.get("is_primary")),
        "variants": variants,
    }


def _base_from_quote(quote: WebQuote) -> dict[str, Any]:
    trip = quote.trip
    return {
        "group_id": None,
        "quote_name": quote.quote_name,
        "origin": quote.origin or "",
        "destination": quote.destination or "",
        "passengers": quote.passengers,
        "babies": quote.babies,
        "bags": quote.bags,
        "travel_type": _normalize_travel_type(
            trip.travel_type if trip else "round_trip",
            segments=_safe_json(trip.segments_json, []) if trip else [],
            return_date=trip.return_date if trip else None,
        ),
        "departure_date": trip.departure_date if trip else "",
        "return_date": trip.return_date if trip else "",
        "segments": _safe_json(trip.segments_json, []) if trip else [],
        "client_person_id": trip.client_person_id if trip else None,
        "client_name": trip.client_name if trip else "",
        "client_email": trip.client_email if trip else "",
        "client_phone": trip.client_phone if trip else "",
        "notes": trip.notes if trip else "",
        "source_request_id": None,
        "mode": "from_quote",
    }




# ============================================================
# V5.9.3 - Escopos de cálculo por trecho dentro da mesma cotação
# ============================================================

def _clean_code(value: Any) -> str:
    return str(value or "").strip().upper()


def _iata_code(value: Any) -> str:
    """Normaliza código ou sugestão como ``FOR — Fortaleza`` para ``FOR``."""
    text = _clean_code(value)
    match = re.search(r"\b([A-Z]{3})\b", text)
    if match:
        return match.group(1)
    # Também aceita busca digitada pelo nome exato da cidade/aeroporto.
    lowered = str(value or "").strip().casefold()
    for code, name in BR_AIRPORTS.items():
        if lowered and lowered == str(name).casefold():
            return code
    return text[:80]


def _iata_value_valid(value: Any) -> bool:
    raw = " ".join(str(value or "").strip().split())
    if not raw:
        return True
    upper = raw.upper()
    if re.fullmatch(r"[A-Z]{3}", upper):
        return True
    if re.match(r"^[A-Z]{3}\s*(?:[-—|/]|$)", upper):
        return True
    lowered = raw.casefold()
    return any(lowered == str(name).casefold() for name in BR_AIRPORTS.values())


def _iata_codes(value: Any) -> list[str]:
    """Normaliza um ou vários IATAs separados por vírgula, /, ; ou |."""
    raw = str(value or "").strip()
    if not raw:
        return []
    parts = [part.strip() for part in re.split(r"[,;/|]+", raw) if part.strip()]
    if len(parts) <= 1:
        parts = [raw]
    codes: list[str] = []
    for part in parts:
        if not _iata_value_valid(part):
            return []
        code = _iata_code(part).strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", code):
            return []
        if code not in codes:
            codes.append(code)
    return codes


def _iata_list_value(value: Any) -> str:
    return ", ".join(_iata_codes(value))


def _required_iata_code(value: Any) -> str:
    """Retorna o primeiro IATA válido. Bases podem ter vários aeroportos."""
    codes = _iata_codes(value)
    return codes[0] if codes else ""


def _route_from_base(base: dict[str, Any]) -> tuple[str, str]:
    """Recupera a rota principal inclusive de bases antigas ou subcotações."""
    origin = _required_iata_code(base.get("origin"))
    destination = _required_iata_code(base.get("destination"))
    raw_segments = base.get("segments") or []
    if isinstance(raw_segments, str):
        raw_segments = _safe_json(raw_segments, [])
    if isinstance(raw_segments, list):
        for segment in raw_segments:
            if not isinstance(segment, dict):
                continue
            seg_origin = _required_iata_code(segment.get("origin"))
            seg_destination = _required_iata_code(segment.get("destination"))
            origin = origin or seg_origin
            destination = destination or seg_destination
            if origin and destination:
                break
    return origin, destination


def _segment_label(origin: str | None, destination: str | None) -> str:
    o = _clean_code(origin) or "?"
    d = _clean_code(destination) or "?"
    return f"{o} → {d}"


def _base_segments(base: dict[str, Any]) -> list[dict[str, Any]]:
    """Monta trechos operacionais a partir da base da cotação.

    Para ida e volta, o usuário informa só origem/destino; aqui o sistema já
    entende que a volta é o inverso da ida. Para multitrecho, usa os segmentos
    digitados no construtor.
    """
    raw_segments_for_type = base.get("segments") or []
    travel_type = _normalize_travel_type(
        base.get("travel_type"), segments=raw_segments_for_type, return_date=base.get("return_date")
    )
    origin, destination = _route_from_base(base)
    dep_date = str(base.get("departure_date") or "")
    ret_date = str(base.get("return_date") or "")
    segments: list[dict[str, Any]] = []

    if travel_type == "multi_city":
        raw_segments = base.get("segments") or []
        if isinstance(raw_segments, str):
            raw_segments = _safe_json(raw_segments, [])
        for idx, seg in enumerate(raw_segments if isinstance(raw_segments, list) else []):
            if not isinstance(seg, dict):
                continue
            o = _iata_list_value(seg.get("origin")) or _clean_code(seg.get("origin"))
            d = _iata_list_value(seg.get("destination")) or _clean_code(seg.get("destination"))
            dt = str(seg.get("date") or "")
            if o or d or dt:
                segments.append({"key": f"segment_{idx+1}", "origin": o, "destination": d, "date": dt, "label": f"Trecho {idx+1} • {_segment_label(o, d)}"})
        return segments

    if origin or destination:
        segments.append({"key": "outbound", "origin": origin, "destination": destination, "date": dep_date, "label": f"Só ida • {_segment_label(origin, destination)}"})
    if travel_type == "round_trip" and (origin or destination):
        segments.append({"key": "return", "origin": destination, "destination": origin, "date": ret_date, "label": f"Só volta • {_segment_label(destination, origin)}"})
    return segments


def _calculation_scopes(base: dict[str, Any]) -> list[dict[str, Any]]:
    segments = _base_segments(base)
    travel_type = _normalize_travel_type(
        base.get("travel_type"), segments=base.get("segments"), return_date=base.get("return_date")
    )
    scopes: list[dict[str, Any]] = []

    def scope_payload(
        key: str,
        label: str,
        hint: str,
        selected_segments: list[dict[str, Any]],
        *,
        departure_date: str = "",
        return_date: str = "",
        requires_skip_airport: bool = False,
        skip_mode: str = "",
        flown_segment: int | None = None,
    ) -> dict[str, Any]:
        return {
            "key": key,
            "label": label,
            "hint": hint,
            "segments": [dict(segment) for segment in selected_segments],
            "departure_date": departure_date or "",
            "return_date": return_date or "",
            "requires_skip_airport": requires_skip_airport,
            "skip_mode": skip_mode,
            "flown_segment": flown_segment,
            "scope_family": "skip" if skip_mode else "standard",
            "available_for": "one_way_and_round_trip" if skip_mode else travel_type,
        }

    if travel_type == "round_trip" and len(segments) >= 2:
        outbound_date = str(segments[0].get("date") or "")
        return_date = str(segments[1].get("date") or "")
        scopes.append(scope_payload(
            "round_trip",
            "Ida e volta",
            f"{_segment_label(segments[0]['origin'], segments[0]['destination'])} + {_segment_label(segments[1]['origin'], segments[1]['destination'])}",
            segments[:2],
            departure_date=outbound_date,
            return_date=return_date,
        ))
        scopes.append(scope_payload(
            "outbound",
            "Só ida",
            _segment_label(segments[0]["origin"], segments[0]["destination"]),
            [segments[0]],
            departure_date=outbound_date,
        ))
        scopes.append(scope_payload(
            "return",
            "Só volta",
            _segment_label(segments[1]["origin"], segments[1]["destination"]),
            [segments[1]],
            return_date=return_date,
        ))
    elif travel_type == "multi_city" and segments:
        scopes.append(scope_payload(
            "multi_city",
            "Todos os trechos",
            f"{len(segments)} trecho(s) na mesma cotação",
            segments,
            departure_date=str(segments[0].get("date") or ""),
            return_date=str(segments[-1].get("date") or "") if len(segments) > 1 else "",
        ))
        for idx, seg in enumerate(segments, start=1):
            scopes.append(scope_payload(
                f"segment_{idx}",
                f"Trecho {idx}",
                _segment_label(seg.get("origin"), seg.get("destination")),
                [seg],
                departure_date=str(seg.get("date") or ""),
            ))
    else:
        segs = segments or [{
            "key": "outbound",
            "origin": _clean_code(base.get("origin")),
            "destination": _clean_code(base.get("destination")),
            "date": str(base.get("departure_date") or ""),
            "label": "Somente ida",
        }]
        scopes.append(scope_payload(
            "one_way",
            "Somente ida",
            _segment_label(segs[0].get("origin"), segs[0].get("destination")),
            [segs[0]],
            departure_date=str(segs[0].get("date") or ""),
        ))

    # V5.10.24 - Skip Normal e Skip Inverso sempre visíveis em Só ida
    # e Ida e volta. Mesmo quando um registro antigo perdeu a rota principal,
    # os cards continuam aparecendo e orientam o usuário a corrigir a base.
    route_origin, route_destination = _route_from_base(base)
    if (not route_origin or not route_destination) and segments:
        route_origin = route_origin or _required_iata_code(segments[0].get("origin"))
        route_destination = route_destination or _required_iata_code(segments[0].get("destination"))
    route_ready = bool(route_origin and route_destination)
    shown_origin = route_origin or "?"
    shown_destination = route_destination or "?"
    base_date = str(base.get("departure_date") or (segments[0].get("date") if segments else "") or "")

    if travel_type in {"one_way", "round_trip"}:
        scopes.append(scope_payload(
            "skip_normal",
            "Skip normal",
            f"Trecho 1: {shown_origin} → {shown_destination} • Trecho 2: {shown_destination} → ?",
            [
                {"key": "skip_normal_1", "origin": route_origin, "destination": route_destination, "date": base_date, "label": f"Trecho 1 • {shown_origin} → {shown_destination}"},
                {"key": "skip_normal_2", "origin": route_destination, "destination": "", "date": "", "label": f"Trecho 2 • {shown_destination} → ?"},
            ],
            departure_date=base_date,
            requires_skip_airport=True,
            skip_mode="normal",
            flown_segment=1,
        ))
        scopes[-1]["route_ready"] = route_ready
        scopes.append(scope_payload(
            "skip_inverse",
            "Skip inverso",
            f"Trecho 1: ? → {shown_origin} • Trecho 2: {shown_origin} → {shown_destination}",
            [
                {"key": "skip_inverse_1", "origin": "", "destination": route_origin, "date": "", "label": f"Trecho 1 • ? → {shown_origin}"},
                {"key": "skip_inverse_2", "origin": route_origin, "destination": route_destination, "date": base_date, "label": f"Trecho 2 • {shown_origin} → {shown_destination}"},
            ],
            return_date=base_date,
            requires_skip_airport=True,
            skip_mode="inverse",
            flown_segment=2,
        ))
        scopes[-1]["route_ready"] = route_ready
    return scopes


def _scope_from_key(base: dict[str, Any], key: str | None) -> dict[str, Any]:
    scopes = _calculation_scopes(base)
    wanted = str(key or "").strip()
    return next((scope for scope in scopes if scope["key"] == wanted), scopes[0] if scopes else {"key": "one_way", "label": "Somente ida", "hint": "", "segments": []})


def _scope_label_from_quote(quote: WebQuote | None) -> str:
    if quote is None:
        return "Cálculo"
    data = _safe_json(getattr(quote, "input_json", None), {})
    scope = data.get("_scope") if isinstance(data, dict) else None
    if isinstance(scope, dict) and scope.get("label"):
        return str(scope.get("label"))
    if quote.trip:
        travel_type = _normalize_travel_type(
            quote.trip.travel_type, segments=quote.trip.segments_json, return_date=quote.trip.return_date
        )
        if travel_type == "multi_city":
            return "Multitrecho"
        if travel_type == "round_trip":
            return "Ida e volta"
        return "Somente ida"
    return "Cálculo"


def _decorate_quote_scope(quote: WebQuote, group: QuoteGroup | None = None, partner_logo_map: dict[str, str] | None = None) -> WebQuote:
    # Defina todos os atributos antes de ler o JSON. Assim, um registro antigo,
    # incompleto ou corrompido nunca derruba o histórico inteiro.
    quote.scope_label = "Cálculo"
    quote.scope_data = {}
    quote.scope_departure_date = ""
    quote.scope_return_date = ""
    quote.fare_brand = ""
    quote.cabin_class = ""
    quote.option_description = ""
    quote.extra_name_saved = ""
    quote.extra_value_saved = ""
    quote.method_label = "Cálculo"
    quote.flight_details = []
    quote.flight_detail_chips = []
    quote.has_flexible_schedule = False
    quote.variant_key = "primary"
    quote.variant_name = "Cotação principal"
    quote.skip_mode = ""
    quote.flown_segment = None
    quote.scope_segments = []
    quote.scope_route_chips = []
    quote.scope_route_items = []
    quote.skip_commission_value = 0.0
    quote.skip_record_value = 0.0
    quote.is_skip_record = False
    quote.operation_scope = ""
    quote.operation_scope_label = ""
    quote.partner_airline = ""
    quote.partner_airline_logo_path = ""
    quote.segment_partner_airlines = []
    quote.segment_rows = []
    quote.is_combined = False
    quote.combined_components = []
    quote.combined_airlines = []
    quote.combined_logo_items = []
    quote.display_airline_name = quote.airline.name if getattr(quote, "airline", None) else "Companhia"
    quote.combine_scope_key = ""
    quote.combine_eligible = False

    try:
        quote.scope_label = _scope_label_from_quote(quote)
        data = _quote_input_data(quote)
        quote.scope_data = _fallback_scope_data(quote, data, group)
        scope_data = quote.scope_data

        combined_meta = data.get("_combined") if isinstance(data.get("_combined"), dict) else {}
        quote.is_combined = bool(combined_meta)
        quote.combined_components = [
            item for item in (combined_meta.get("components") or [])
            if isinstance(item, dict)
        ][:12]
        quote.combined_airlines = [
            str(item).strip() for item in (combined_meta.get("airlines") or [])
            if str(item).strip()
        ][:12]

        partner_logo_map = partner_logo_map or {}
        quote.combined_logo_items = []
        for component in quote.combined_components[:6]:
            airline_name = str(component.get("airline") or "").strip()
            if not airline_name:
                continue
            logo_path = str(
                component.get("logo_path")
                or component.get("airline_logo_path")
                or partner_logo_map.get(_normalized_token(airline_name), "")
                or ""
            ).strip()
            quote.combined_logo_items.append({
                "name": airline_name,
                "logo_path": logo_path,
                "initial": (airline_name[:1] or "C").upper(),
            })

        if quote.is_combined:
            quote.display_airline_name = str(
                combined_meta.get("display_name")
                or (" + ".join(quote.combined_airlines) if quote.combined_airlines else "Opção combinada")
            ).strip()[:220]
        else:
            quote.display_airline_name = quote.airline.name if quote.airline else "Companhia"

        raw_combine_scope = str(scope_data.get("key") or "").strip().lower()
        label_bucket = _scope_bucket_key(getattr(quote, "scope_label", ""))

        if raw_combine_scope in {"outbound", "return"}:
            quote.combine_scope_key = raw_combine_scope
        elif re.fullmatch(r"segment_\d+", raw_combine_scope):
            quote.combine_scope_key = raw_combine_scope

        # Compatibilidade com opções já salvas: algumas versões gravaram
        # "one_way" no JSON, mas o card do Histórico é corretamente classificado
        # como SÓ IDA ou SÓ VOLTA pelo label.
        elif label_bucket in {"outbound", "return"}:
            quote.combine_scope_key = label_bucket

        else:
            # Trecho N também pode vir somente no label ou no único segmento.
            label_match = re.search(r"trecho\s*(\d+)", str(getattr(quote, "scope_label", "") or ""), re.I)
            if label_match:
                quote.combine_scope_key = f"segment_{int(label_match.group(1))}"
            else:
                raw_segments_for_combine = scope_data.get("segments") if isinstance(scope_data.get("segments"), list) else []
                if len(raw_segments_for_combine) == 1 and isinstance(raw_segments_for_combine[0], dict):
                    segment_key = str(raw_segments_for_combine[0].get("key") or "").strip().lower()
                    if re.fullmatch(r"segment_\d+", segment_key):
                        quote.combine_scope_key = segment_key
                    else:
                        quote.combine_scope_key = ""
                else:
                    quote.combine_scope_key = ""

        quote.combine_eligible = bool(quote.combine_scope_key and not quote.is_combined)
        variant_data = data.get("_variant") if isinstance(data.get("_variant"), dict) else {}
        quote.variant_key = str(variant_data.get("key") or "primary")
        quote.variant_name = str(variant_data.get("name") or "Cotação principal")
        quote.skip_mode = str(scope_data.get("skip_mode") or "")
        try:
            quote.flown_segment = int(scope_data.get("flown_segment") or 0) or None
        except (TypeError, ValueError):
            quote.flown_segment = None
        if quote.skip_mode and not quote.flown_segment:
            quote.flown_segment = 1 if quote.skip_mode == "normal" else 2
        raw_scope_segments = scope_data.get("segments") if isinstance(scope_data.get("segments"), list) else []
        quote.scope_segments = [dict(item) for item in raw_scope_segments if isinstance(item, dict)]
        quote.scope_route_chips = []
        quote.scope_route_items = []
        for idx, segment in enumerate(quote.scope_segments[:12], start=1):
            origin = _clean_code(segment.get("origin")) or "?"
            destination = _clean_code(segment.get("destination")) or "?"
            label = f"Trecho {idx} • {origin} → {destination}"
            quote.scope_route_chips.append(label)
            status = "neutral"
            if quote.skip_mode:
                status = "flown" if quote.flown_segment == idx else "not_flown"
            quote.scope_route_items.append({"label": label, "status": status, "segment": idx})

        skip_financial = data.get("_skip_financial") if isinstance(data.get("_skip_financial"), dict) else {}
        try:
            quote.skip_record_value = max(0.0, float(skip_financial.get("value") or quote.total or 0))
        except (TypeError, ValueError):
            quote.skip_record_value = max(0.0, float(quote.total or 0))
        try:
            quote.skip_commission_value = max(0.0, float(skip_financial.get("commission") or 0))
        except (TypeError, ValueError):
            quote.skip_commission_value = 0.0
        quote.is_skip_record = bool(quote.skip_mode)
        partnership = data.get("_partnership") if isinstance(data.get("_partnership"), dict) else {}
        quote.operation_scope = str(partnership.get("operation_scope") or "").strip().lower()
        quote.operation_scope_label = {"national": "Nacional", "international": "Internacional"}.get(quote.operation_scope, "")
        quote.partner_airline = str(partnership.get("partner_airline") or "").strip()[:180]
        partner_logo_map = partner_logo_map or {}
        quote.partner_airline_logo_path = partner_logo_map.get(_normalized_token(quote.partner_airline), "")
        raw_segment_partners = partnership.get("segment_partners") if isinstance(partnership.get("segment_partners"), list) else []
        quote.segment_partner_airlines = []
        for item in raw_segment_partners[:12]:
            if not isinstance(item, dict):
                continue
            try:
                segment_number = int(item.get("segment") or 0)
            except (TypeError, ValueError):
                continue
            partner_name = str(item.get("partner_airline") or item.get("name") or "").strip()[:180]
            if segment_number < 1 or not partner_name:
                continue
            quote.segment_partner_airlines.append({
                "segment": segment_number,
                "name": partner_name,
                "logo_path": partner_logo_map.get(_normalized_token(partner_name), ""),
            })
        if not quote.segment_partner_airlines and quote.partner_airline:
            quote.segment_partner_airlines = [{
                "segment": 1,
                "name": quote.partner_airline,
                "logo_path": quote.partner_airline_logo_path,
            }]
        trip = getattr(quote, "trip", None)
        quote.scope_departure_date = str(scope_data.get("departure_date") or (trip.departure_date if trip else "") or "")
        quote.scope_return_date = str(scope_data.get("return_date") or (trip.return_date if trip else "") or "")
        meta = _quote_meta(quote)
        airline = getattr(quote, "airline", None)
        quote.fare_brand = meta.get("fare_brand") or _default_fare_for_airline(airline.name if airline else "")
        quote.cabin_class = meta.get("cabin_class") or ""
        quote.option_description = meta.get("description") or ""
        quote.extra_name_saved = meta.get("extra_name") or ""
        quote.extra_value_saved = meta.get("extra_value") if meta.get("extra_value") not in (None, "") else ""
        quote.method_label = "Registro Skip" if quote.skip_mode else _calculation_method_label(quote)
        if quote.is_combined:
            quote.method_label = "Combinação de opções"
            quote.fare_brand = quote.fare_brand or "Combinada"

        quote.flight_details = _quote_flight_details(quote, data, scope_data)
        quote.flight_detail_chips = _flight_detail_chips(quote.flight_details)
        quote.segment_rows = _history_segment_rows(
            quote.scope_segments,
            quote.flight_details,
            quote.scope_departure_date,
            quote.scope_return_date,
            quote.skip_mode,
            quote.flown_segment,
        )
        partner_by_segment = {int(item.get("segment") or 0): item for item in quote.segment_partner_airlines}
        for row in quote.segment_rows:
            partner_info = partner_by_segment.get(int(row.get("segment") or 0))
            row["partner_airline"] = partner_info.get("name") if partner_info else ""
            row["partner_logo_path"] = partner_info.get("logo_path") if partner_info else ""
        if not quote.scope_departure_date and quote.flight_details:
            quote.scope_departure_date = str(quote.flight_details[0].get("departure_date") or "")
        if not quote.scope_return_date and len(quote.scope_segments) > 1:
            last_key = str(quote.scope_segments[-1].get("key") or "")
            quote.scope_return_date = next((
                str(item.get("departure_date") or "") for item in quote.flight_details
                if str(item.get("segment_key") or "") == last_key and item.get("departure_date")
            ), "")

        detail_counts: dict[str, int] = {}
        for detail in quote.flight_details[:20]:
            if isinstance(detail, dict):
                detail_key = str(detail.get("segment_key") or detail.get("label") or "voo")
                detail_counts[detail_key] = detail_counts.get(detail_key, 0) + 1
        quote.has_flexible_schedule = any(count > 1 for count in detail_counts.values())
    except Exception as exc:
        # A cotação continua visível mesmo que apenas os detalhes opcionais
        # estejam inválidos. O erro fica no log para diagnóstico.
        logger.warning("Não foi possível decorar a cotação %s no histórico: %s", getattr(quote, "id", "?"), exc)
    return quote



# ============================================================
# V5.10.6 - metadados visuais da opção (escopo, tarifa, classe e descrição)
# ============================================================

def _quote_input_data(quote: WebQuote | None) -> dict[str, Any]:
    if quote is None:
        return {}
    data = _safe_json(getattr(quote, "input_json", None), {})
    return data if isinstance(data, dict) else {}


def _nested_value(payload: Any, aliases: set[str], *, depth: int = 0) -> Any:
    if depth > 5:
        return None
    normalized_aliases = {_normalized_token(alias) for alias in aliases}
    if isinstance(payload, dict):
        for key, value in payload.items():
            if _normalized_token(key) in normalized_aliases and value not in (None, "", [], {}):
                return value
        for value in payload.values():
            found = _nested_value(value, aliases, depth=depth + 1)
            if found not in (None, "", [], {}):
                return found
    elif isinstance(payload, list):
        for value in payload[:30]:
            found = _nested_value(value, aliases, depth=depth + 1)
            if found not in (None, "", [], {}):
                return found
    return None


def _quote_meta(quote: WebQuote | None) -> dict[str, Any]:
    data = _quote_input_data(quote)
    meta = data.get("_meta") if isinstance(data.get("_meta"), dict) else {}
    breakdown = _safe_json(getattr(quote, "breakdown_json", None), {}) if quote is not None else {}
    sources = [meta, data, breakdown]

    def pick(aliases: set[str], default: Any = "") -> Any:
        for source in sources:
            value = _nested_value(source, aliases)
            if value not in (None, "", [], {}):
                return value
        return default

    return {
        "fare_brand": str(pick({"fare_brand", "fare", "tarifa", "nome_tarifa", "familia_tarifaria", "fare_family"})).strip(),
        "cabin_class": str(pick({"cabin_class", "classe_cabine", "classe", "cabine", "booking_class", "classe_voo"})).strip(),
        "description": str(pick({"description", "option_description", "descricao", "observacao", "notes"})).strip(),
        "extra_name": str(pick({"extra_name", "nome_adicional", "adicional_nome"})).strip(),
        "extra_value": pick({"extra_value", "valor_adicional", "adicional_valor"}, ""),
    }


def _fallback_scope_data(quote: WebQuote, data: dict[str, Any], group: QuoteGroup | None = None) -> dict[str, Any]:
    """Reconstrói rota, trechos e datas sem apagar o que já foi salvo.

    A rotina usa, nesta ordem: dados da própria opção, viagem da opção e base da
    cotação/subcotação. Isso corrige opções antigas que ficaram com rota vazia
    depois de uma edição de tarifa ou de um formulário carregado sem JavaScript.
    """
    current = data.get("_scope") if isinstance(data.get("_scope"), dict) else {}
    trip = getattr(quote, "trip", None)
    quote_segments = _safe_json(getattr(trip, "segments_json", None), []) if trip else []
    if not isinstance(quote_segments, list):
        quote_segments = []

    travel_type = _normalize_travel_type(
        getattr(trip, "travel_type", None),
        segments=quote_segments,
        return_date=getattr(trip, "return_date", None),
    )
    fallback_segments = [dict(item) for item in quote_segments if isinstance(item, dict)]

    if not fallback_segments and (getattr(quote, "origin", None) or getattr(quote, "destination", None)):
        fallback_segments = [{
            "key": "outbound",
            "origin": _clean_code(getattr(quote, "origin", "")),
            "destination": _clean_code(getattr(quote, "destination", "")),
            "date": getattr(trip, "departure_date", "") if trip else "",
        }]
        if travel_type == "round_trip":
            fallback_segments.append({
                "key": "return",
                "origin": _clean_code(getattr(quote, "destination", "")),
                "destination": _clean_code(getattr(quote, "origin", "")),
                "date": getattr(trip, "return_date", "") if trip else "",
            })

    current_key = str(current.get("key") or "").strip()
    variant_data = data.get("_variant") if isinstance(data.get("_variant"), dict) else {}
    variant_key = str(variant_data.get("key") or "primary")
    group_scope: dict[str, Any] = {}
    if group is not None:
        try:
            group_base = _base_from_group(group, variant_key)
            wanted_key = current_key or ({"one_way": "one_way", "round_trip": "round_trip", "multi_city": "multi_city"}.get(travel_type, "one_way"))
            group_scope = _scope_from_key(group_base, wanted_key)
            recovered = [dict(item) for item in (group_scope.get("segments") or []) if isinstance(item, dict)]
            if recovered:
                extra_airport = _clean_code(current.get("extra_airport"))
                if wanted_key == "skip_normal" and len(recovered) > 1 and extra_airport:
                    recovered[1]["destination"] = extra_airport
                elif wanted_key == "skip_inverse" and recovered and extra_airport:
                    recovered[0]["origin"] = extra_airport
                if not fallback_segments:
                    fallback_segments = recovered
                else:
                    merged_segments = []
                    for idx in range(max(len(fallback_segments), len(recovered))):
                        own = dict(fallback_segments[idx]) if idx < len(fallback_segments) else {}
                        base_seg = dict(recovered[idx]) if idx < len(recovered) else {}
                        for key in ("key", "origin", "destination", "date", "label"):
                            if own.get(key) in (None, "") and base_seg.get(key) not in (None, ""):
                                own[key] = base_seg.get(key)
                        merged_segments.append(own)
                    fallback_segments = merged_segments
        except Exception as exc:
            logger.warning("Não foi possível recuperar a rota da cotação %s pelo grupo: %s", getattr(quote, "id", "?"), exc)

    label = {"one_way": "Somente ida", "round_trip": "Ida e volta", "multi_city": "Multitrecho"}.get(travel_type, "Cálculo")
    key = {"one_way": "one_way", "round_trip": "round_trip", "multi_city": "multi_city"}.get(travel_type, "one_way")
    fallback = {
        "key": current_key or str(group_scope.get("key") or key),
        "label": str(current.get("label") or group_scope.get("label") or label),
        "segments": fallback_segments,
        "departure_date": str((getattr(trip, "departure_date", "") if trip else "") or group_scope.get("departure_date") or ""),
        "return_date": str((getattr(trip, "return_date", "") if trip else "") or group_scope.get("return_date") or ""),
        "skip_mode": str(current.get("skip_mode") or group_scope.get("skip_mode") or ""),
        "flown_segment": current.get("flown_segment") or group_scope.get("flown_segment"),
    }

    merged = dict(fallback)
    if current:
        merged.update({k: v for k, v in current.items() if v not in (None, "", [], {})})
        current_segments = current.get("segments") if isinstance(current.get("segments"), list) else []
        if current_segments:
            fixed_segments = []
            for idx in range(max(len(current_segments), len(fallback_segments))):
                own = dict(current_segments[idx]) if idx < len(current_segments) and isinstance(current_segments[idx], dict) else {}
                base_seg = dict(fallback_segments[idx]) if idx < len(fallback_segments) else {}
                for field in ("key", "origin", "destination", "date", "label"):
                    if own.get(field) in (None, "") and base_seg.get(field) not in (None, ""):
                        own[field] = base_seg.get(field)
                fixed_segments.append(own)
            merged["segments"] = fixed_segments
        else:
            merged["segments"] = fallback_segments
    merged["departure_date"] = str(current.get("departure_date") or fallback["departure_date"] or "")
    merged["return_date"] = str(current.get("return_date") or fallback["return_date"] or "")
    return merged

def _quote_flight_details(quote: WebQuote, data: dict[str, Any], scope_data: dict[str, Any]) -> list[dict[str, Any]]:
    raw = data.get("_flight_details")
    if raw in (None, "", []):
        raw = _nested_value(data, {"flight_details", "flight_options", "horarios_voo", "possibilidades_voo", "schedule_options"})
    selected_segments = scope_data.get("segments") if isinstance(scope_data.get("segments"), list) else []
    scope_key = str(scope_data.get("key") or "one_way")
    normalized = _normalize_flight_details(raw or [], selected_segments, scope_key)
    if normalized:
        return normalized

    trip = getattr(quote, "trip", None)
    trip_segments = _safe_json(getattr(trip, "segments_json", None), []) if trip else []
    source_segments = selected_segments or (trip_segments if isinstance(trip_segments, list) else [])
    details: list[dict[str, Any]] = []
    for idx, segment in enumerate(source_segments[:12]):
        if not isinstance(segment, dict):
            continue
        key = str(segment.get("key") or ("outbound" if idx == 0 else ("return" if idx == 1 and scope_key == "round_trip" else f"segment_{idx+1}")))
        dep_date = _clean_date_value(segment.get("departure_date") or segment.get("date"))
        dep_time = _clean_time_value(segment.get("departure_time") or segment.get("time") or segment.get("hora_saida"))
        arr_date = _clean_date_value(segment.get("arrival_date") or segment.get("date_arrival") or segment.get("data_chegada"))
        arr_time = _clean_time_value(segment.get("arrival_time") or segment.get("hora_chegada"))
        if not any([dep_date, dep_time, arr_date, arr_time]):
            continue
        details.append({
            "segment_key": key, "label": _flight_segment_label(key, idx),
            "origin": _clean_code(segment.get("origin")), "destination": _clean_code(segment.get("destination")),
            "departure_date": dep_date, "departure_time": dep_time,
            "arrival_date": arr_date, "arrival_time": arr_time,
        })

    if details:
        return details

    dep_date = _clean_date_value(scope_data.get("departure_date") or (getattr(trip, "departure_date", "") if trip else ""))
    ret_date = _clean_date_value(scope_data.get("return_date") or (getattr(trip, "return_date", "") if trip else ""))
    dep_time = _clean_time_value(_nested_value(data, {"departure_time", "hora_embarque", "horario_ida", "hora_saida"}))
    arr_time = _clean_time_value(_nested_value(data, {"arrival_time", "hora_desembarque", "hora_chegada"}))
    if dep_date or dep_time or arr_time:
        details.append({
            "segment_key": "outbound", "label": "Ida",
            "origin": _clean_code(getattr(quote, "origin", "")), "destination": _clean_code(getattr(quote, "destination", "")),
            "departure_date": dep_date, "departure_time": dep_time,
            "arrival_date": dep_date if arr_time else "", "arrival_time": arr_time,
        })
    if ret_date:
        details.append({
            "segment_key": "return", "label": "Volta",
            "origin": _clean_code(getattr(quote, "destination", "")), "destination": _clean_code(getattr(quote, "origin", "")),
            "departure_date": ret_date, "departure_time": "", "arrival_date": "", "arrival_time": "",
        })
    return details


def _format_saved_calculation_value(value: Any, field: CalculationField | Any) -> str:
    """Formata SOMENTE a exibição de valores já salvos na tela de edição.

    Não altera o banco nem o cálculo. Corrige formatos quebrados por versões
    antigas, por exemplo ``2,40747`` / ``2.40747`` -> ``2.407,47``.
    Campos de pontos/milhas (ex.: ``556.500``) ficam intactos.
    """
    raw = str(value if value is not None else "").strip()
    if not raw:
        return raw

    field_type = str(getattr(field, "field_type", "") or "").strip().lower()
    if field_type in {"select", "text", "integer", "percent"}:
        return raw

    key = _normalized_token(getattr(field, "key", ""))
    label = _normalized_token(getattr(field, "label", ""))

    # Pontos/milhas são grandezas, não dinheiro. O ponto pode ser parte da
    # forma como o usuário prefere visualizar (ex.: 556.500), então preserva.
    non_money_keys = {
        "milhas", "milha", "pontos", "ponto", "numero_trechos",
        "passageiros", "bebes", "bagagens", "quantidade",
        "desconto", "desconto_taxa", "juros",
    }
    if key in non_money_keys or any(token in label for token in ("milhas", "pontos", "percentual", "porcentagem")):
        return raw

    try:
        step = float(getattr(field, "step", 0) or 0)
    except (TypeError, ValueError):
        step = 0.0

    money_hints = (
        "taxa", "valor", "preco", "custo", "dinheiro", "milheiro",
        "bagagem", "comissao", "tarifa", "adicional", "imposto",
    )
    is_money = (0 < step <= 0.01) or any(token in key or token in label for token in money_hints)
    if not is_money:
        return raw

    compact = raw.replace("R$", "").replace(" ", "")
    if not compact:
        return raw

    sign = "-" if compact.startswith("-") else ""
    unsigned = compact[1:] if sign else compact

    def grouped(integer_digits: str) -> str:
        digits = re.sub(r"\\D", "", str(integer_digits or ""))
        if not digits:
            return "0"
        digits = digits.lstrip("0") or "0"
        parts: list[str] = []
        while len(digits) > 3:
            parts.append(digits[-3:])
            digits = digits[:-3]
        parts.append(digits)
        return ".".join(reversed(parts))

    # Já está correto com separador de milhar e centavos: 2.407,47.
    br_grouped = re.fullmatch(r"(\\d{1,3}(?:\\.\\d{3})*),(\\d{1,2})", unsigned)
    if br_grouped:
        return f"{sign}{br_grouped.group(1)},{br_grouped.group(2)}"

    # Brasileiro sem separador de milhar: 2407,47 -> 2.407,47.
    br_plain = re.fullmatch(r"(\\d+),(\\d{1,2})", unsigned)
    if br_plain:
        return f"{sign}{grouped(br_plain.group(1))},{br_plain.group(2)}"

    # Bug observado: 2,40747 -> 2.407,47.
    broken_comma = re.fullmatch(r"(\\d{1,3}),(\\d{3,})", unsigned)
    if broken_comma:
        digits = broken_comma.group(1) + broken_comma.group(2)
        if len(digits) > 2:
            return f"{sign}{grouped(digits[:-2])},{digits[-2:]}"

    # Outro formato de versões anteriores: 2,407,47.
    if unsigned.count(",") > 1 and re.fullmatch(r"[\\d,]+", unsigned):
        digits = re.sub(r"\\D", "", unsigned)
        if len(digits) > 2:
            return f"{sign}{grouped(digits[:-2])},{digits[-2:]}"

    # Decimal americano: 2407.47 -> 2.407,47.
    american = re.fullmatch(r"(\\d+)\\.(\\d{1,2})", unsigned)
    if american:
        return f"{sign}{grouped(american.group(1))},{american.group(2).ljust(2, '0')}"

    # Bug também pode aparecer como 2.40747 (ponto deslocado e 4+ dígitos
    # depois dele). Junta os dígitos e usa as duas últimas casas como centavos.
    broken_dot = re.fullmatch(r"(\\d{1,3})\\.(\\d{4,})", unsigned)
    if broken_dot:
        digits = broken_dot.group(1) + broken_dot.group(2)
        if len(digits) > 2:
            return f"{sign}{grouped(digits[:-2])},{digits[-2:]}"

    return raw


def _parse_amount(value: Any, *, field_name: str = "valor") -> float:
    """Converte valores monetários digitados com ponto ou vírgula."""
    text = str(value or "").strip().replace("R$", "").replace(" ", "")
    if not text:
        return 0.0
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        parsed = float(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} inválido") from exc
    if parsed < 0:
        raise ValueError(f"{field_name} não pode ser negativo")
    return round(parsed, 2)




# ============================================================
# V5.10.12 - horários e múltiplas possibilidades de voo por opção
# ============================================================

def _clean_date_value(value: Any) -> str:
    text = str(value or "").strip()[:10]
    if not text:
        return ""
    try:
        datetime.strptime(text, "%Y-%m-%d")
        return text
    except ValueError:
        return ""


def _clean_time_value(value: Any) -> str:
    text = str(value or "").strip()[:5]
    if not re.fullmatch(r"\d{2}:\d{2}", text):
        return ""
    try:
        hour, minute = (int(part) for part in text.split(":", 1))
    except (TypeError, ValueError):
        return ""
    return text if 0 <= hour <= 23 and 0 <= minute <= 59 else ""


def _flight_segment_label(segment_key: str, index: int = 0) -> str:
    key = str(segment_key or "").strip().lower()
    if key in {"outbound", "one_way", "ida"}:
        return "Ida"
    if key in {"return", "volta"}:
        return "Volta"
    match = re.search(r"(\d+)$", key)
    if match:
        return f"Trecho {match.group(1)}"
    return f"Trecho {index + 1}" if index >= 0 else "Voo"


def _normalize_flight_details(raw: Any, selected_segments: list[dict[str, Any]], scope_key: str) -> list[dict[str, Any]]:
    """Normaliza datas e horários opcionais sem exigir migração de banco.

    Os detalhes ficam dentro de ``WebQuote.input_json``. Assim, instalações
    existentes recebem a função sem alterar tabelas e cada opção calculada pode
    manter diversas possibilidades para o mesmo trecho.
    """
    if isinstance(raw, str):
        items = _safe_json(raw, [])
    else:
        items = raw
    if not isinstance(items, list):
        return []

    segments: list[dict[str, Any]] = []
    for idx, segment in enumerate(selected_segments or []):
        if not isinstance(segment, dict):
            continue
        key = str(segment.get("key") or f"segment_{idx + 1}").strip()
        segments.append({
            "key": key,
            "origin": _clean_code(segment.get("origin")),
            "destination": _clean_code(segment.get("destination")),
            "label": _flight_segment_label(key, idx),
        })

    if not segments:
        fallback_key = "return" if str(scope_key) == "return" else ("outbound" if str(scope_key) in {"outbound", "one_way", "round_trip"} else str(scope_key or "outbound"))
        segments = [{"key": fallback_key, "origin": "", "destination": "", "label": _flight_segment_label(fallback_key, 0)}]

    by_key = {segment["key"]: segment for segment in segments}
    default_key = segments[0]["key"]
    normalized: list[dict[str, Any]] = []

    for item in items[:20]:
        if not isinstance(item, dict):
            continue
        segment_key = str(item.get("segment_key") or item.get("kind") or default_key).strip()
        if segment_key not in by_key:
            segment_key = default_key
        segment = by_key[segment_key]
        departure_date = _clean_date_value(item.get("departure_date") or item.get("date"))
        departure_time = _clean_time_value(item.get("departure_time"))
        arrival_date = _clean_date_value(item.get("arrival_date"))
        arrival_time = _clean_time_value(item.get("arrival_time"))

        # Todos os campos são opcionais; uma linha totalmente vazia não é salva.
        if not any([departure_date, departure_time, arrival_date, arrival_time]):
            continue
        if not arrival_date and departure_date and arrival_time:
            arrival_date = departure_date

        normalized.append({
            "segment_key": segment_key,
            "kind": "ida" if segment_key in {"outbound", "one_way"} else ("volta" if segment_key == "return" else "trecho"),
            "label": segment["label"],
            "origin": segment["origin"],
            "destination": segment["destination"],
            "departure_date": departure_date,
            "departure_time": departure_time,
            "arrival_date": arrival_date,
            "arrival_time": arrival_time,
        })
    return normalized


def _display_short_date(value: Any) -> str:
    text = _clean_date_value(value)
    if not text:
        return ""
    try:
        return datetime.strptime(text, "%Y-%m-%d").strftime("%d/%m")
    except ValueError:
        return text


def _flight_detail_chips(details: Any) -> list[str]:
    if not isinstance(details, list):
        return []
    totals: dict[str, int] = {}
    for item in details:
        if isinstance(item, dict):
            key = str(item.get("segment_key") or item.get("label") or "voo")
            totals[key] = totals.get(key, 0) + 1

    positions: dict[str, int] = {}
    chips: list[str] = []
    for item in details[:20]:
        if not isinstance(item, dict):
            continue
        key = str(item.get("segment_key") or item.get("label") or "voo")
        positions[key] = positions.get(key, 0) + 1
        label = str(item.get("label") or _flight_segment_label(key)).strip() or "Voo"
        if totals.get(key, 0) > 1:
            label = f"{label} {positions[key]}"

        dep_date = _display_short_date(item.get("departure_date"))
        dep_time = _clean_time_value(item.get("departure_time"))
        arr_date = _display_short_date(item.get("arrival_date"))
        arr_time = _clean_time_value(item.get("arrival_time"))
        departure = " - ".join(part for part in [dep_date, dep_time] if part)
        if arr_date and arr_date == dep_date:
            arrival = arr_time
        else:
            arrival = " - ".join(part for part in [arr_date, arr_time] if part)

        schedule = departure
        if arrival:
            schedule = f"{departure} → {arrival}" if departure else f"Chegada {arrival}"
        chips.append(f"{label} • {schedule}" if schedule else label)
    return chips


def _display_full_date(value: Any) -> str:
    text = _clean_date_value(value)
    if not text:
        return ""
    try:
        return datetime.strptime(text, "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return text


def _detail_schedule_text(item: dict[str, Any]) -> str:
    dep_date = _display_full_date(item.get("departure_date"))
    dep_time = _clean_time_value(item.get("departure_time"))
    arr_date = _display_full_date(item.get("arrival_date"))
    arr_time = _clean_time_value(item.get("arrival_time"))
    departure = " - ".join(part for part in [dep_date, dep_time] if part)
    if arr_date and arr_date == dep_date:
        arrival = arr_time
    else:
        arrival = " - ".join(part for part in [arr_date, arr_time] if part)
    if departure and arrival:
        return f"{departure} → {arrival}"
    if departure:
        return departure
    if arrival:
        return f"Chegada {arrival}"
    return ""


def _history_segment_rows(
    segments: Any,
    details: Any,
    departure_date: str = "",
    return_date: str = "",
    skip_mode: str = "",
    flown_segment: int | None = None,
) -> list[dict[str, Any]]:
    raw_segments = segments if isinstance(segments, list) else []
    raw_details = details if isinstance(details, list) else []
    rows: list[dict[str, Any]] = []
    for idx, segment in enumerate(raw_segments[:12], start=1):
        if not isinstance(segment, dict):
            continue
        key = str(segment.get("key") or f"segment_{idx}")
        origin = _clean_code(segment.get("origin")) or "?"
        destination = _clean_code(segment.get("destination")) or "?"
        status = "neutral"
        if skip_mode:
            status = "flown" if int(flown_segment or 0) == idx else "not_flown"
        key_norm = str(key).strip().lower()
        aliases = {key_norm, f"segment_{idx}", f"trecho_{idx}", str(idx)}
        if idx == 1:
            aliases.update({"outbound", "one_way", "ida", "skip_normal_1", "skip_inverse_1"})
        if idx == 2:
            aliases.update({"return", "volta", "skip_normal_2", "skip_inverse_2"})
        matched = []
        for detail_index, item in enumerate(raw_details, start=1):
            if not isinstance(item, dict):
                continue
            detail_key = str(item.get("segment_key") or item.get("key") or "").strip().lower()
            if detail_key in aliases or (not detail_key and detail_index == idx):
                matched.append(item)
        # Em Skip, horário pertence apenas ao trecho efetivamente utilizado.
        if skip_mode and status != "flown":
            matched = []
        schedules = [text for text in (_detail_schedule_text(item) for item in matched) if text]
        fallback_date = _clean_date_value(segment.get("date"))
        if not fallback_date:
            fallback_date = _clean_date_value(departure_date if idx == 1 else return_date)
        if not schedules and fallback_date and (not skip_mode or status == "flown"):
            schedules = [_display_full_date(fallback_date)]
        rows.append({
            "segment": idx,
            "key": key,
            "origin": origin,
            "destination": destination,
            "route": f"{origin} → {destination}",
            "status": status,
            "status_label": "VOADO" if status == "flown" else ("NÃO VOADO" if status == "not_flown" else "TRECHO"),
            "schedules": schedules,
        })
    if not rows and raw_details:
        for idx, item in enumerate(raw_details[:12], start=1):
            if not isinstance(item, dict):
                continue
            rows.append({
                "segment": idx,
                "key": str(item.get("segment_key") or f"segment_{idx}"),
                "origin": _clean_code(item.get("origin")) or "?",
                "destination": _clean_code(item.get("destination")) or "?",
                "route": f"{_clean_code(item.get('origin')) or '?'} → {_clean_code(item.get('destination')) or '?'}",
                "status": "neutral",
                "status_label": "TRECHO",
                "schedules": [text for text in [_detail_schedule_text(item)] if text],
            })
    return rows


def _default_fare_for_airline(airline_name: str | None) -> str:
    name = (airline_name or "").lower()
    if "latam" in name:
        return "Standard"
    if "smiles" in name or "gol" in name:
        return "Light"
    if "azul" in name or "tudoazul" in name or "tudo azul" in name:
        return "Azul"
    return "Com bagagem"


def _calculation_method_label(quote: WebQuote | None) -> str:
    if quote is None:
        return "Cálculo"
    airline = (quote.airline.name if quote.airline else "") or ""
    calc = (quote.calculation_type.name if quote.calculation_type else "") or "Cálculo"
    airline_lower = airline.lower()
    calc_lower = calc.lower()
    if "azul" in airline_lower:
        if "dinheiro" in calc_lower:
            return "Azul Pontos + Dinheiro"
        return "Azul Pontos"
    if "latam" in airline_lower:
        return "LATAM Pass"
    if "smiles" in airline_lower or "gol" in airline_lower:
        return "Smiles"
    return calc


def _scope_bucket_key(label: str | None) -> str:
    text = (label or "").strip().lower()
    if "skip" in text and ("inv" in text or "invers" in text):
        return "skip_inverse"
    if "skip" in text:
        return "skip_normal"
    if text in {"só ida", "so ida", "somente ida", "ida"}:
        return "outbound"
    if text in {"só volta", "so volta", "somente volta", "volta"}:
        return "return"
    if "trecho" in text or "multi" in text:
        return "multi_city"
    if "ida" in text and "volta" in text:
        return "round_trip"
    return "other"


def _scope_bucket_label(key: str) -> str:
    return {
        "outbound": "SÓ IDA",
        "return": "SÓ VOLTA",
        "round_trip": "IDA E VOLTA",
        "multi_city": "TRECHOS / MULTITRECHO",
        "skip_normal": "SKIP NORMAL",
        "skip_inverse": "SKIP INVERSO",
    }.get(key, "OUTROS CÁLCULOS")


def _quote_total_sort_key(quote: WebQuote) -> tuple[float, int]:
    """Ordena opções do menor valor para o maior sem quebrar dados antigos."""
    try:
        total = float(getattr(quote, "total", 0) or 0)
    except (TypeError, ValueError):
        total = float("inf")
    try:
        quote_id = int(getattr(quote, "id", 0) or 0)
    except (TypeError, ValueError):
        quote_id = 0
    return total, quote_id


def _group_options_by_scope(options: list[WebQuote]) -> list[dict[str, Any]]:
    order = ["outbound", "return", "round_trip", "multi_city", "skip_normal", "skip_inverse", "other"]
    grouped: dict[str, list[WebQuote]] = {key: [] for key in order}
    for quote in options:
        try:
            bucket = _scope_bucket_key(getattr(quote, "scope_label", ""))
        except Exception:
            bucket = "other"
        if bucket not in grouped:
            bucket = "other"
        grouped[bucket].append(quote)
    result: list[dict[str, Any]] = []
    for key in order:
        items = grouped.get(key) or []
        if items:
            items = sorted(items, key=_quote_total_sort_key)
            result.append({"key": key, "label": _scope_bucket_label(key), "items": items})
    if not result and options:
        result.append({"key": "other", "label": _scope_bucket_label("other"), "items": list(options)})
    return result


def _group_options_by_variant(options: list[WebQuote], group: QuoteGroup | None = None) -> list[dict[str, Any]]:
    """Separa claramente a cotação principal e cada subcotação.

    Todas as subcotações cadastradas são mantidas no histórico, inclusive quando
    ainda não possuem cálculo. Dentro de cada subcotação, as opções continuam
    agrupadas pelo tipo de trecho e ordenadas do menor valor para o maior.
    """
    cards = _group_variant_cards(group) if group is not None else []
    card_map = {str(item.get("key") or "primary"): item for item in cards}
    order = [str(item.get("key") or "primary") for item in cards]
    labels = {str(item.get("key") or "primary"): str(item.get("name") or "Subcotação") for item in cards}

    if "primary" not in order:
        order.insert(0, "primary")
        labels.setdefault("primary", "Cotação principal")

    grouped: dict[str, list[WebQuote]] = {}
    for quote in options:
        key = str(getattr(quote, "variant_key", "primary") or "primary")
        grouped.setdefault(key, []).append(quote)
        if key not in order:
            order.append(key)
        labels.setdefault(key, str(getattr(quote, "variant_name", "Subcotação") or "Subcotação"))

    result: list[dict[str, Any]] = []
    subquote_number = 0

    for position, key in enumerate(order, start=1):
        items = grouped.get(key) or []
        card = card_map.get(key) or {}

        # Chaves encontradas somente em opções antigas também continuam visíveis.
        if not card and not items:
            continue

        is_primary = key == "primary"
        if not is_primary:
            subquote_number += 1

        first_quote = items[0] if items else None
        travel_type = str(card.get("travel_type") or "one_way")
        travel_type_label = {
            "one_way": "Somente ida",
            "round_trip": "Ida e volta",
            "multi_city": "Multitrecho",
        }.get(travel_type, "Viagem")

        result.append({
            "key": key,
            "label": labels.get(key, "Subcotação"),
            "is_primary": is_primary,
            "position": position,
            "subquote_number": subquote_number if not is_primary else 0,
            "origin": str(card.get("origin") or getattr(first_quote, "origin", "") or ""),
            "destination": str(card.get("destination") or getattr(first_quote, "destination", "") or ""),
            "travel_type": travel_type,
            "travel_type_label": travel_type_label,
            "departure_date": card.get("departure_date") or "",
            "return_date": card.get("return_date") or "",
            "flexibility_days": max(0, int(card.get("flexibility_days") or 0)),
            "passengers": int(card.get("passengers") or (getattr(first_quote, "passengers", 1) if first_quote else 1) or 1),
            "babies": int(card.get("babies") if card.get("babies") is not None else (getattr(first_quote, "babies", 0) if first_quote else 0) or 0),
            "items": items,
            "scope_groups": _group_options_by_scope(items),
        })

    if not result and options:
        result.append({
            "key": "primary",
            "label": "Cotação principal",
            "is_primary": True,
            "position": 1,
            "subquote_number": 0,
            "origin": str(getattr(options[0], "origin", "") or ""),
            "destination": str(getattr(options[0], "destination", "") or ""),
            "travel_type": "one_way",
            "travel_type_label": "Viagem",
            "departure_date": "",
            "return_date": "",
            "flexibility_days": 0,
            "passengers": int(getattr(options[0], "passengers", 1) or 1),
            "babies": int(getattr(options[0], "babies", 0) or 0),
            "items": list(options),
            "scope_groups": _group_options_by_scope(list(options)),
        })

    return result


def _is_priority_national_airline(airline_name: str | None) -> bool:
    token = _normalized_token(airline_name)
    if "azul_pelo_mundo" in token or token == "azulpelomundo":
        return False
    return (
        token == "azul" or token.startswith("azul_linhas")
        or token == "gol" or token.startswith("gol_") or "smiles_gol" in token
        or token == "latam" or token.startswith("latam_")
    )


def _airline_sort_key(airline: Airline) -> tuple[int, str]:
    """Azul, GOL e LATAM ficam fixadas no topo; Azul Pelo Mundo logo depois."""
    token = _normalized_token(getattr(airline, "name", ""))
    if token == "azul" or (token.startswith("azul_linhas") and "mundo" not in token):
        return (0, token)
    if token == "gol" or token.startswith("gol_") or "smiles_gol" in token:
        return (1, token)
    if token == "latam" or token.startswith("latam_"):
        return (2, token)
    if "azul_pelo_mundo" in token or token == "azulpelomundo":
        return (3, token)
    return (10, token)


def _configured_partner_names(airline: Airline | None) -> list[str]:
    if airline is None:
        return []
    try:
        raw = json.loads(str(getattr(airline, "partner_airlines_json", "[]") or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        raw = []
    if not isinstance(raw, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in raw:
        name = " ".join(str(item or "").split()).strip()[:180]
        key = _normalized_token(name)
        if name and key and key not in seen:
            seen.add(key)
            result.append(name)
    return result[:100]


def _partner_airline_choices(airlines: list[Airline], selected_airline: Airline | None = None) -> list[str]:
    """Todas as companhias visíveis podem ser parceiras, sem limitar por mercado.

    As parceiras configuradas no cadastro da companhia aparecem primeiro. Nomes
    manuais salvos no perfil também são mantidos, mesmo que ainda não tenham um
    cadastro próprio no sistema.
    """
    configured = _configured_partner_names(selected_airline)
    configured_tokens = {_normalized_token(name) for name in configured}
    available = [
        str(item.name or "").strip()
        for item in airlines
        if item.active
        and (selected_airline is None or item.id != selected_airline.id)
        and str(item.name or "").strip()
    ]
    all_names = configured + sorted(
        [name for name in available if _normalized_token(name) not in configured_tokens],
        key=_normalized_token,
    )
    result: list[str] = []
    seen: set[str] = set()
    for name in all_names:
        token = _normalized_token(name)
        if token and token not in seen:
            seen.add(token)
            result.append(name)
    return result



def _partner_airline_options(airlines: list[Airline], selected_airline: Airline | None = None) -> list[dict[str, Any]]:
    """Opções prontas para a interface de parceria.

    Importante: esta função devolve APENAS dicionários com strings/inteiros.
    Nenhum objeto SQLAlchemy ``Airline`` é enviado para o JavaScript/template,
    evitando textos como ``<app.models.Airline object at 0x...>``.
    """
    configured = _configured_partner_names(selected_airline)
    by_token: dict[str, dict[str, Any]] = {}

    for airline in airlines:
        if not getattr(airline, "active", True):
            continue
        if selected_airline is not None and int(getattr(airline, "id", 0) or 0) == int(getattr(selected_airline, "id", 0) or 0):
            continue

        name = " ".join(str(getattr(airline, "name", "") or "").split()).strip()[:180]
        if not name:
            continue

        token = _normalized_token(name)
        if not token:
            continue

        scope = str(getattr(airline, "market_scope", "") or "").strip().lower()
        if scope not in {"national", "international", "both"}:
            scope = str(_airline_operation_profile(airline).get("market_scope") or "both")

        by_token[token] = {
            "id": int(getattr(airline, "id", 0) or 0),
            "name": name,
            "logo_path": str(getattr(airline, "logo_path", "") or ""),
            "color": str(getattr(airline, "color", "") or ""),
            "market_scope": scope,
            "market_label": {
                "national": "Nacional",
                "international": "Internacional",
                "both": "Nacional + internacional",
            }.get(scope, "Nacional + internacional"),
            "builtin": bool(getattr(airline, "builtin", False)),
            "configured": token in {_normalized_token(item) for item in configured},
        }

    # Parceiras digitadas no cadastro que ainda não possuem companhia criada
    # continuam disponíveis como opção manual.
    for configured_name in configured:
        token = _normalized_token(configured_name)
        if not token or token in by_token:
            if token in by_token:
                by_token[token]["configured"] = True
            continue
        by_token[token] = {
            "id": 0,
            "name": configured_name,
            "logo_path": "",
            "color": "",
            "market_scope": "both",
            "market_label": "Parceira cadastrada",
            "builtin": False,
            "configured": True,
        }

    rows = list(by_token.values())
    rows.sort(key=lambda item: (
        0 if item.get("configured") else 1,
        _normalized_token(item.get("name")),
    ))
    return rows


def _team_users(db: Session, user: WebUser) -> list[WebUser]:
    if user.company_id:
        return list(db.scalars(
            select(WebUser)
            .where(WebUser.company_id == user.company_id, WebUser.active.is_(True))
            .order_by(WebUser.name)
        ).all())
    return [user]


def _airline_operation_profile(airline_or_name: Airline | str | None) -> dict[str, Any]:
    airline = airline_or_name if isinstance(airline_or_name, Airline) else None
    airline_name = airline.name if airline is not None else airline_or_name
    token = _normalized_token(airline_name)

    stored_scope = str(getattr(airline, "market_scope", "") or "").strip().lower() if airline is not None else ""
    if stored_scope not in {"national", "international", "both"}:
        # Compatibilidade com bancos antigos que ainda não tinham o campo.
        is_azul_world = "azul_pelo_mundo" in token or token == "azulpelomundo" or ("azul" in token and "mundo" in token)
        is_azul_domestic = not is_azul_world and (token == "azul" or token.startswith("azul_linhas"))
        if is_azul_world:
            stored_scope = "international"
        elif is_azul_domestic:
            stored_scope = "national"
        elif token == "voepass" or token.startswith("voepass_"):
            stored_scope = "national"
        else:
            stored_scope = "both"

    selectable_market = stored_scope == "both"
    fixed_market = stored_scope if stored_scope in {"national", "international"} else ""

    return {
        "token": token,
        "market_scope": stored_scope,
        "selectable_market": selectable_market,
        "fixed_market": fixed_market,
        # Parceria é sempre opcional e pode ser usada tanto em operação
        # nacional quanto internacional.
        "partner_allowed": True,
        "configured_partners": _configured_partner_names(airline),
    }

def _selected_airline_and_type(
    db: Session,
    user,
    airline_id: int | None,
    type_id: int | None,
    *,
    auto_select: bool = True,
):
    """Carrega a lista de companhias de forma leve e os campos só da selecionada.

    Antes, a tela trazia todos os tipos + todos os campos das 40+ companhias em
    cada abertura. Em banco remoto isso aumenta bastante o payload e o tempo de
    hidratação do ORM. A lista lateral precisa somente dos dados da companhia;
    relacionamentos completos são carregados apenas para a companhia ativa.
    """
    airlines = list(db.scalars(
        _visible_airlines_query(user)
        .order_by(Airline.builtin.desc(), Airline.name)
    ).all())
    airlines.sort(key=_airline_sort_key)

    selected_stub = next((item for item in airlines if item.id == airline_id), None)
    if selected_stub is None and auto_select and airlines:
        selected_stub = airlines[0]

    selected_airline = None
    if selected_stub is not None:
        selected_airline = db.scalar(
            select(Airline)
            .where(Airline.id == selected_stub.id)
            .options(selectinload(Airline.calculation_types).selectinload(CalculationType.fields))
            .execution_options(populate_existing=True)
        ) or selected_stub

    selected_type = None
    if selected_airline:
        selected_type = next((item for item in selected_airline.calculation_types if item.id == type_id and item.active), None)
        if selected_type is None:
            selected_type = next((item for item in selected_airline.calculation_types if item.is_default and item.active), None)
        if selected_type is None:
            selected_type = next((item for item in selected_airline.calculation_types if item.active), None)
    return airlines, selected_airline, selected_type


def _load_options(db: Session, user, group_id: int) -> list[WebQuote]:
    access_filter = WebQuote.company_id == user.company_id if user.company_id else WebQuote.user_id == user.id
    links = db.scalars(
        select(QuoteOptionIndex)
        .where(QuoteOptionIndex.group_id == group_id)
        .order_by(QuoteOptionIndex.position, QuoteOptionIndex.created_at)
    ).all()
    if not links:
        return []
    ids = [link.quote_id for link in links]
    quotes = db.scalars(
        select(WebQuote)
        .where(WebQuote.id.in_(ids), access_filter)
        .options(
            selectinload(WebQuote.airline),
            selectinload(WebQuote.calculation_type),
            selectinload(WebQuote.trip),
            selectinload(WebQuote.commercial),
            selectinload(WebQuote.user),
        )
    ).all()
    group = db.scalar(
        select(QuoteGroup)
        .where(QuoteGroup.id == group_id)
        .options(selectinload(QuoteGroup.trip))
    )
    by_id = {item.id: item for item in quotes}
    partner_airlines = list(db.scalars(_visible_airlines_query(user).where(Airline.active.is_(True))).all())
    partner_logo_map = {
        _normalized_token(item.name): str(item.logo_path or "")
        for item in partner_airlines
        if item.name
    }
    decorated: list[WebQuote] = []
    for item_id in ids:
        quote = by_id.get(item_id)
        if quote is None:
            continue
        decorated.append(_decorate_quote_scope(quote, group, partner_logo_map))
    return decorated

def _load_group_activities(db: Session, group_id: int) -> list[QuoteActivity]:
    """Carrega a linha do tempo sem impedir a abertura do histórico."""
    global _ACTIVITY_TABLE_AVAILABLE
    if _ACTIVITY_TABLE_AVAILABLE is None:
        try:
            _ACTIVITY_TABLE_AVAILABLE = inspect(db.get_bind()).has_table("web_quote_activities")
        except Exception:
            _ACTIVITY_TABLE_AVAILABLE = False
    if not _ACTIVITY_TABLE_AVAILABLE:
        return []
    try:
        return list(db.scalars(
            select(QuoteActivity)
            .where(QuoteActivity.group_id == group_id)
            .options(selectinload(QuoteActivity.actor))
            .order_by(desc(QuoteActivity.created_at))
            .limit(6)
        ).all())
    except Exception as exc:
        logger.warning("Linha do tempo indisponível para o grupo %s: %s", group_id, exc)
        _ACTIVITY_TABLE_AVAILABLE = False
        try:
            db.rollback()
        except Exception:
            pass
        return []


def _group_card(db: Session, user, group: QuoteGroup) -> dict[str, Any]:
    options = sorted(_load_options(db, user, group.id), key=_quote_total_sort_key)
    activities = _load_group_activities(db, group.id)
    try:
        option_groups = _group_options_by_scope(options)
        option_variant_groups = _group_options_by_variant(options, group)
    except Exception as exc:
        logger.exception("Falha ao organizar opções do grupo %s: %s", group.id, exc)
        option_groups = _group_options_by_scope(options)
        option_variant_groups = [{
            "key": "primary",
            "label": "Cotação principal",
            "is_primary": True,
            "items": options,
            "scope_groups": option_groups,
        }] if options else []
    return {
        "group": group,
        "base": _base_from_group(group),
        "options": options,
        "option_groups": option_groups,
        "option_variant_groups": option_variant_groups,
        "variants": _group_variant_cards(group),
        "activities": activities,
        "load_error": False,
    }



def _history_group_cards_batch(
    db: Session,
    user,
    groups: list[QuoteGroup],
) -> dict[int, dict[str, Any]]:
    """Carrega uma página inteira do Histórico com poucas consultas.

    Antes, cada grupo chamava ``_load_options`` separadamente — e a versão
    segura chegava a chamar duas vezes — gerando dezenas de consultas para uma
    única página. Aqui vínculos, opções, companhias parceiras e atividades são
    carregados em lote.
    """
    group_ids = [int(group.id) for group in groups if getattr(group, "id", None)]
    if not group_ids:
        return {}

    access_filter = WebQuote.company_id == user.company_id if user.company_id else WebQuote.user_id == user.id

    links = list(
        db.scalars(
            select(QuoteOptionIndex)
            .where(QuoteOptionIndex.group_id.in_(group_ids))
            .order_by(QuoteOptionIndex.group_id, QuoteOptionIndex.position, QuoteOptionIndex.created_at)
        ).all()
    )
    links_by_group: dict[int, list[QuoteOptionIndex]] = {gid: [] for gid in group_ids}
    quote_ids: list[int] = []
    for link in links:
        links_by_group.setdefault(int(link.group_id), []).append(link)
        quote_ids.append(int(link.quote_id))

    quotes_by_id: dict[int, WebQuote] = {}
    if quote_ids:
        rows = list(
            db.scalars(
                select(WebQuote)
                .where(WebQuote.id.in_(quote_ids), access_filter)
                .options(
                    selectinload(WebQuote.airline),
                    selectinload(WebQuote.calculation_type),
                    selectinload(WebQuote.trip),
                    selectinload(WebQuote.commercial),
                    selectinload(WebQuote.user),
                )
            ).all()
        )
        quotes_by_id = {int(item.id): item for item in rows}

    partner_airlines = list(
        db.scalars(_visible_airlines_query(user).where(Airline.active.is_(True))).all()
    )
    partner_logo_map = {
        _normalized_token(item.name): str(item.logo_path or "")
        for item in partner_airlines
        if item.name
    }

    activities_by_group: dict[int, list[QuoteActivity]] = {gid: [] for gid in group_ids}
    global _ACTIVITY_TABLE_AVAILABLE
    if _ACTIVITY_TABLE_AVAILABLE is None:
        try:
            _ACTIVITY_TABLE_AVAILABLE = inspect(db.get_bind()).has_table("web_quote_activities")
        except Exception:
            _ACTIVITY_TABLE_AVAILABLE = False
    if _ACTIVITY_TABLE_AVAILABLE:
        try:
            activity_rows = list(
                db.scalars(
                    select(QuoteActivity)
                    .where(QuoteActivity.group_id.in_(group_ids))
                    .options(selectinload(QuoteActivity.actor))
                    .order_by(desc(QuoteActivity.created_at))
                    .limit(max(120, len(group_ids) * 12))
                ).all()
            )
            for activity in activity_rows:
                bucket = activities_by_group.setdefault(int(activity.group_id), [])
                if len(bucket) < 6:
                    bucket.append(activity)
        except Exception as exc:
            logger.warning("Linha do tempo em lote indisponível: %s", exc)
            _ACTIVITY_TABLE_AVAILABLE = False
            try:
                db.rollback()
            except Exception:
                pass

    cards: dict[int, dict[str, Any]] = {}
    for group in groups:
        gid = int(group.id)
        try:
            options: list[WebQuote] = []
            for link in links_by_group.get(gid, []):
                quote = quotes_by_id.get(int(link.quote_id))
                if quote is None:
                    continue
                options.append(_decorate_quote_scope(quote, group, partner_logo_map))
            options.sort(key=_quote_total_sort_key)

            option_groups = _group_options_by_scope(options)
            try:
                option_variant_groups = _group_options_by_variant(options, group)
            except Exception as exc:
                logger.warning("Falha ao separar variantes do grupo %s: %s", gid, exc)
                option_variant_groups = [{
                    "key": "primary",
                    "label": "Cotação principal",
                    "is_primary": True,
                    "items": options,
                    "scope_groups": option_groups,
                }] if options else []

            cards[gid] = {
                "group": group,
                "base": _base_from_group(group),
                "options": options,
                "option_groups": option_groups,
                "option_variant_groups": option_variant_groups,
                "variants": _group_variant_cards(group),
                "activities": activities_by_group.get(gid, []),
                "load_error": False,
            }
        except Exception as exc:
            logger.exception("Falha ao montar grupo %s em lote: %s", gid, exc)
            cards[gid] = _safe_history_group_card(db, user, group)
            cards[gid]["load_error"] = True

    return cards


def _safe_history_group_card(db: Session, user, group: QuoteGroup) -> dict[str, Any]:
    """Impede que uma cotação problemática tire o histórico inteiro do ar."""
    options: list[WebQuote] = []
    try:
        return _group_card(db, user, group)
    except Exception as exc:
        try:
            options = sorted(_load_options(db, user, group.id), key=_quote_total_sort_key)
        except Exception:
            options = []
        logger.exception("Falha ao carregar o grupo %s no histórico: %s", getattr(group, "id", "?"), exc)
        try:
            base = _base_from_group(group)
        except Exception:
            base = _blank_base()
            base.update({
                "quote_name": getattr(group, "quote_name", "Cotação"),
                "origin": getattr(group, "origin", "") or "",
                "destination": getattr(group, "destination", "") or "",
                "passengers": int(getattr(group, "passengers", 1) or 1),
            })
        option_groups = _group_options_by_scope(options) if options else []
        option_variant_groups = [{
            "key": "primary", "label": "Cotação principal", "is_primary": True,
            "items": options, "scope_groups": option_groups,
        }] if options else []
        return {
            "group": group, "base": base, "options": options,
            "option_groups": option_groups, "option_variant_groups": option_variant_groups,
            "variants": _group_variant_cards(group),
            "activities": _load_group_activities(db, group.id),
            "load_error": True,
        }


@router.get("/new")
def new_calculation(request: Request, db: Session = Depends(get_db)):
    """Abre a calculadora com uma tentativa automática de recuperação.

    Bancos preservados de versões antigas podem estar alguns segundos atrás da
    estrutura atual, especialmente quando o OneDrive ainda está sincronizando.
    A primeira falha aciona a migração compatível e repete a abertura uma vez.
    """
    def int_query(name: str) -> int | None:
        value = request.query_params.get(name)
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    params = {
        "group_id": int_query("group_id"),
        "airline_id": int_query("airline_id"),
        "type_id": int_query("type_id"),
        "request_id": int_query("request_id"),
        "person_id": int_query("person_id"),
        "edit_id": int_query("edit_id"),
        "clone_id": int_query("clone_id"),
        "edit_base": int_query("edit_base"),
        "calc": int_query("calc"),
        "clean": int_query("clean"),
        "variant_key": request.query_params.get("variant_key"),
        "db": db,
    }
    try:
        return _new_calculation_impl(request, **params)
    except Exception as first_exc:
        logger.exception("Falha inicial ao abrir a calculadora; tentando reparar o esquema: %s", first_exc)
        try:
            db.rollback()
        except Exception:
            pass
        try:
            ensure_runtime_schema(engine)
            db.expire_all()
            return _new_calculation_impl(request, **params)
        except Exception as second_exc:
            try:
                db.rollback()
            except Exception:
                pass
            reference = datetime.utcnow().strftime("CALC-%Y%m%d-%H%M%S-%f")
            logger.exception("Falha definitiva %s ao abrir a calculadora: %s", reference, second_exc)
            user = current_user(request, db)
            if user is None:
                return RedirectResponse("/login", status_code=303)
            target_group = params.get("group_id") or request.session.get("active_quote_group_id")
            back_url = f"/calculations/group/{target_group}" if target_group else "/calculations/history"
            return templates.TemplateResponse(
                request,
                "calculations/recovery.html",
                context(request, user=user, reference=reference, back_url=back_url),
                status_code=200,
            )


def _new_calculation_impl(
    request: Request,
    group_id: int | None = None,
    airline_id: int | None = None,
    type_id: int | None = None,
    request_id: int | None = None,
    person_id: int | None = None,
    edit_id: int | None = None,
    clone_id: int | None = None,
    edit_base: int | None = None,
    calc: int | None = None,
    clean: int | None = None,
    variant_key: str | None = None,
    db: Session | None = None,
):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)

    base = _blank_base()
    group = None
    options: list[WebQuote] = []
    edit_option: WebQuote | None = None
    field_values: dict[str, Any] = {}
    option_id = None
    option_bags = 0

    if clean:
        request.session.pop("active_quote_group_id", None)
        return templates.TemplateResponse(request, "calculations/new.html", context(request, user=user, base=base, group=None, options=[], airlines=[], selected_airline=None, selected_type=None, field_values={}, calculation_fields=[], option_id=None, option_bags=0, option_flight_details=[], route_scopes=[], skip_scopes=[], edit_base=True, airport_map=BR_AIRPORTS))

    if group_id is None and not (edit_id or clone_id):
        session_group_id = request.session.get("active_quote_group_id")
        if session_group_id:
            try:
                group_id = int(session_group_id)
            except (TypeError, ValueError):
                group_id = None

    # V5.5.8: fallback de segurança. Se o navegador voltou para a tela de
    # cálculo sem group_id na URL, usa a última cotação principal do usuário
    # apenas quando a página está explicitamente em modo de cálculo.
    if group_id is None and (calc or str(request.query_params.get("calc") or "") in {"1", "true", "sim", "yes"}):
        access_group = QuoteGroup.company_id == user.company_id if user.company_id else QuoteGroup.user_id == user.id
        latest_group = db.scalar(select(QuoteGroup).where(access_group).order_by(desc(QuoteGroup.updated_at), desc(QuoteGroup.id)))
        if latest_group is not None:
            group_id = latest_group.id

    if group_id:
        group = db.scalar(select(QuoteGroup).where(QuoteGroup.id == group_id).options(selectinload(QuoteGroup.trip), selectinload(QuoteGroup.user).selectinload(WebUser.profile), selectinload(QuoteGroup.assigned_user).selectinload(WebUser.profile)))
        if _group_allowed(user, group):
            request.session["active_quote_group_id"] = group.id
            base = _base_from_group(group, variant_key)
            # A lista completa de opções não é usada nesta tela. Só a buscamos
            # para reparar cotações antigas cuja rota esteja realmente vazia.
            # Isso elimina várias consultas e relacionamentos em cada abertura.
            route_missing = not (_required_iata_code(group.origin) and _required_iata_code(group.destination))
            if str(variant_key or "primary") in {"", "primary"} and route_missing:
                options = _load_options(db, user, group.id)
                if _recover_group_route_from_options(db, user, group, options):
                    db.commit()
                    base = _base_from_group(group, variant_key)
        else:
            group = None
            request.session.pop("active_quote_group_id", None)

    # V5.5.10: quando a URL traz uma cotação principal existente, o padrão
    # agora é abrir diretamente a tela antiga de cálculo. A tela de editar
    # dados da base só aparece quando o usuário pede explicitamente
    # edit_base=1. Isso corrige Alterar/Duplicar ficando presos na tela de
    # base mesmo depois de a cotação já existir.
    session_force_calc_group = request.session.pop("force_calc_group_id", None)

    if request_id and group is None:
        item = db.get(QuoteRequest, request_id)
        if _request_allowed(user, item):
            base.update(
                {
                    "quote_name": f"Cotação para {item.client_name}",
                    "origin": item.origin,
                    "destination": item.destination,
                    "passengers": max(1, item.adults + item.children),
                    "babies": item.babies,
                    "bags": item.bags,
                    "travel_type": item.travel_type,
                    "departure_date": item.departure_date or "",
                    "return_date": item.return_date or "",
                    "segments": _safe_json(item.segments_json, []),
                    "client_name": item.client_name,
                    "client_email": item.email or "",
                    "client_phone": item.phone,
                    "notes": item.notes or "",
                    "source_request_id": item.id,
                    "mode": "request_base",
                }
            )

    if person_id and group is None:
        person = db.get(Person, person_id)
        if _person_allowed(user, person):
            base.update(
                {
                    "quote_name": f"Cotação para {person.name}",
                    "client_person_id": person.id,
                    "client_name": person.name,
                    "client_email": person.email or "",
                    "client_phone": person.phone or person.mobile or "",
                    "mode": "person_base",
                }
            )

    source_quote_id = edit_id or clone_id
    if source_quote_id and group is None:
        source_quote = db.scalar(
            select(WebQuote)
            .where(WebQuote.id == source_quote_id)
            .options(selectinload(WebQuote.trip), selectinload(WebQuote.airline), selectinload(WebQuote.calculation_type))
        )
        if _quote_allowed(user, source_quote):
            # V5.5.10: duplicar cotação antiga também deve se comportar
            # como uma nova criação já salva: cria a cotação principal
            # imediatamente e manda para a tela de cálculo, em vez de ficar
            # parado na tela de base.
            if clone_id:
                cloned_base = _base_from_quote(source_quote)
                new_group = QuoteGroup(
                    user_id=user.id,
                    company_id=user.company_id,
                    quote_name=f"Cópia de {cloned_base['quote_name']}",
                    origin=cloned_base.get("origin") or None,
                    destination=cloned_base.get("destination") or None,
                    passengers=max(1, int(cloned_base.get("passengers") or 1)),
                    babies=max(0, int(cloned_base.get("babies") or 0)),
                    bags=0,
                    source_request_id=cloned_base.get("source_request_id"),
                    assigned_user_id=user.id,
                )
                db.add(new_group)
                db.flush()
                db.add(
                    QuoteGroupTripDetail(
                        group_id=new_group.id,
                        travel_type=cloned_base.get("travel_type") or "round_trip",
                        departure_date=cloned_base.get("departure_date") or None,
                        return_date=cloned_base.get("return_date") or None,
                        segments_json=json.dumps(cloned_base.get("segments") or [], ensure_ascii=False),
                        client_person_id=cloned_base.get("client_person_id") or None,
                        client_name=cloned_base.get("client_name") or None,
                        client_email=cloned_base.get("client_email") or None,
                        client_phone=cloned_base.get("client_phone") or None,
                        notes=cloned_base.get("notes") or None,
                    )
                )
                db.commit()
                request.session["active_quote_group_id"] = new_group.id
                request.session["force_calc_group_id"] = new_group.id
                redirect_url = f"/calculations/new?group_id={new_group.id}&calc=1&mode=calc"
                if source_quote.airline_id:
                    redirect_url += f"&airline_id={source_quote.airline_id}"
                if source_quote.calculation_type_id:
                    redirect_url += f"&type_id={source_quote.calculation_type_id}"
                flash(request, "Cotação duplicada. A base já está salva; escolha a companhia e calcule as opções.", "success")
                return RedirectResponse(redirect_url, status_code=303)

            base = _base_from_quote(source_quote)
            airline_id = airline_id or source_quote.airline_id
            type_id = type_id or source_quote.calculation_type_id
            field_values = _safe_json(source_quote.input_json, {})
            if edit_id:
                owning_link = db.get(QuoteOptionIndex, source_quote.id)
                owning_group = (
                    db.scalar(
                        select(QuoteGroup)
                        .where(QuoteGroup.id == owning_link.group_id)
                        .options(selectinload(QuoteGroup.trip))
                    )
                    if owning_link
                    else None
                )
                if owning_group is not None and _group_allowed(user, owning_group):
                    group = owning_group
                    request.session["active_quote_group_id"] = group.id
                    saved_variant = field_values.get("_variant") if isinstance(field_values.get("_variant"), dict) else {}
                    variant_key = str(saved_variant.get("key") or variant_key or "primary")
                    base = _base_from_group(group, variant_key)
                    options = _load_options(db, user, group.id)
                edit_option = source_quote
                option_id = source_quote.id
                option_bags = max(0, int(source_quote.bags or 0))

    if edit_id and group:
        edit_option = db.scalar(select(WebQuote).where(WebQuote.id == edit_id).options(selectinload(WebQuote.trip)))
        if _quote_allowed(user, edit_option):
            option_id = edit_option.id
            option_bags = max(0, int(edit_option.bags or 0))
            airline_id = airline_id or edit_option.airline_id
            type_id = type_id or edit_option.calculation_type_id
            field_values = _safe_json(edit_option.input_json, {})
            saved_variant = field_values.get("_variant") if isinstance(field_values.get("_variant"), dict) else {}
            variant_key = str(saved_variant.get("key") or variant_key or "primary")
            base = _base_from_group(group, variant_key)

    user_agent = str(request.headers.get("user-agent") or "").lower()
    mobile_request = any(token in user_agent for token in ("android", "iphone", "ipod", "mobile", "windows phone"))
    auto_select_airline = not (mobile_request and airline_id is None and edit_id is None and clone_id is None)
    airlines, selected_airline, selected_type = _selected_airline_and_type(
        db, user, airline_id, type_id, auto_select=auto_select_airline
    )
    calculation_fields = _effective_calculation_fields(db, selected_type)
    if selected_type is not None and calculation_fields and not selected_type.fields:
        db.commit()

    # Valores usados APENAS para exibição ao editar. O JSON original permanece
    # intacto até o usuário salvar novamente.
    field_display_values: dict[str, str] = {}
    for _field in calculation_fields:
        _raw_saved = field_values.get(_field.key, _field.default_value or "0")
        field_display_values[_field.key] = _format_saved_calculation_value(_raw_saved, _field)

    # V5.5.10: comportamento final aprovado.
    # - Grupo existente + calc/mode=calc/session force => tela de cálculo.
    # - Grupo existente sem edit_base explícito => tela de cálculo.
    # - edit_base=1 => tela de alteração dos dados da base.
    # - Sem grupo => nova cotação limpa/base.
    query_edit_base = str(request.query_params.get("edit_base") or "").lower()
    query_calc = str(request.query_params.get("calc") or "").lower()
    query_mode = str(request.query_params.get("mode") or "").lower()
    force_edit_base = query_edit_base in {"1", "true", "sim", "yes"}
    force_calc_mode = bool(calc) or query_calc in {"1", "true", "sim", "yes"} or query_mode in {"calc", "calculo", "calcular"}
    try:
        session_force_calc = group is not None and int(session_force_calc_group or 0) == int(group.id)
    except (TypeError, ValueError):
        session_force_calc = False

    if group is None:
        edit_base_mode = True
    elif force_edit_base:
        # A edição explícita da base sempre vence flags antigas de sessão ou
        # parâmetros de cálculo. Isso garante que “Alterar cotação principal”
        # abra realmente o formulário de dados da cotação.
        edit_base_mode = True
    elif force_calc_mode or session_force_calc:
        edit_base_mode = False
    else:
        edit_base_mode = False

    route_scopes = _calculation_scopes(base) if group else []
    saved_scope = field_values.get("_scope", {}) if isinstance(field_values.get("_scope"), dict) else {}
    selected_scope_key = str(saved_scope.get("key") or "")
    selected_scope = next((scope for scope in route_scopes if scope.get("key") == selected_scope_key), route_scopes[0] if route_scopes else {})
    option_departure_date = str(saved_scope.get("departure_date") or (edit_option.trip.departure_date if edit_option and edit_option.trip else "") or selected_scope.get("departure_date") or "")
    option_return_date = str(saved_scope.get("return_date") or (edit_option.trip.return_date if edit_option and edit_option.trip else "") or selected_scope.get("return_date") or "")

    partnership_meta = field_values.get("_partnership", {}) if isinstance(field_values.get("_partnership"), dict) else {}
    saved_segment_partners = partnership_meta.get("segment_partners") if isinstance(partnership_meta.get("segment_partners"), list) else []
    saved_partner_by_segment: dict[int, str] = {}
    for item in saved_segment_partners:
        if not isinstance(item, dict):
            continue
        try:
            number = int(item.get("segment") or 0)
        except (TypeError, ValueError):
            continue
        name = str(item.get("partner_airline") or item.get("name") or "").strip()
        if number > 0 and name:
            saved_partner_by_segment[number] = name
    max_partner_segments = max([len(scope.get("segments") or []) for scope in route_scopes] or [1])
    partner_segment_rows = []
    for segment_number in range(1, min(max_partner_segments, 12) + 1):
        segment_data = None
        for scope in ([selected_scope] + route_scopes):
            parts = scope.get("segments") if isinstance(scope, dict) and isinstance(scope.get("segments"), list) else []
            if len(parts) >= segment_number and isinstance(parts[segment_number - 1], dict):
                segment_data = parts[segment_number - 1]
                break
        segment_data = segment_data or {}
        route_label = f"{_clean_code(segment_data.get('origin')) or '?'} → {_clean_code(segment_data.get('destination')) or '?'}"
        partner_segment_rows.append({
            "segment": segment_number,
            "route": route_label,
            "partner_airline": saved_partner_by_segment.get(segment_number, partnership_meta.get("partner_airline", "") if segment_number == 1 else ""),
        })

    return templates.TemplateResponse(
        request,
        "calculations/new.html",
        context(
            request,
            user=user,
            base=base,
            group=group,
            options=options,
            airlines=airlines,
            selected_airline=selected_airline,
            selected_type=selected_type,
            field_values=field_values,
            field_display_values=field_display_values,
            calculation_fields=calculation_fields,
            option_id=option_id,
            option_bags=option_bags,
            option_meta=(field_values.get("_meta", {}) if isinstance(field_values.get("_meta"), dict) else {}),
            route_scopes=route_scopes,
            skip_scopes=[scope for scope in route_scopes if scope.get("key") in {"skip_normal", "skip_inverse"}],
            selected_scope_key=selected_scope_key,
            option_departure_date=option_departure_date,
            option_return_date=option_return_date,
            option_flight_details=(field_values.get("_flight_details", []) if isinstance(field_values.get("_flight_details"), list) else []),
            selected_variant_key=str(base.get("variant_key") or "primary"),
            selected_variant_name=str(base.get("variant_name") or "Cotação principal"),
            group_variants=(base.get("variants") or (_group_variant_cards(group) if group else [])),
            saved_skip_airport=str(saved_scope.get("extra_airport") or ""),
            saved_skip_origin=str(saved_scope.get("editable_origin") or ""),
            saved_skip_destination=str(saved_scope.get("editable_destination") or saved_scope.get("extra_airport") or ""),
            saved_skip_date=str(saved_scope.get("editable_date") or ""),
            saved_skip_value=str((field_values.get("_skip_financial", {}) if isinstance(field_values.get("_skip_financial"), dict) else {}).get("value") or (edit_option.total if edit_option and selected_scope_key in {"skip_normal", "skip_inverse"} else "")),
            saved_skip_commission=str((field_values.get("_skip_financial", {}) if isinstance(field_values.get("_skip_financial"), dict) else {}).get("commission") or ""),
            operation_profile=_airline_operation_profile(selected_airline),
            partnership_meta=partnership_meta,
            partner_segment_rows=partner_segment_rows,
            # V2.21: somente o seletor de parceira POR TRECHO volta para a tela.
            # A lista é montada a partir das companhias já carregadas, sem nova consulta ao banco.
            partner_airline_choices=_partner_airline_choices(airlines, selected_airline),
            partner_airline_options=_partner_airline_options(airlines, selected_airline),
            national_airlines=[item for item in airlines if _is_priority_national_airline(item.name)],
            other_airlines=[item for item in airlines if not _is_priority_national_airline(item.name)],
            edit_base=edit_base_mode,
            airport_map=BR_AIRPORTS,
        ),
    )


def _sync_primary_options_with_group(db: Session, group: QuoteGroup, trip: QuoteGroupTripDetail) -> int:
    """Mantém as opções da cotação principal alinhadas à base editada.

    Horários, valores, tarifa e classe permanecem intactos. Apenas rota, datas,
    passageiros e cliente da variante principal são atualizados. Subcotações
    continuam independentes.
    """
    links = list(db.scalars(select(QuoteOptionIndex).where(QuoteOptionIndex.group_id == group.id)).all())
    if not links:
        return 0
    option_ids = [item.quote_id for item in links]
    options = list(db.scalars(
        select(WebQuote)
        .where(WebQuote.id.in_(option_ids))
        .options(selectinload(WebQuote.trip))
    ).all())
    base = _base_from_group(group)
    updated = 0
    for quote in options:
        data = _safe_json(quote.input_json, {})
        if not isinstance(data, dict):
            data = {}
        variant = data.get("_variant") if isinstance(data.get("_variant"), dict) else {}
        if str(variant.get("key") or "primary") != "primary":
            continue

        old_scope = data.get("_scope") if isinstance(data.get("_scope"), dict) else {}
        default_scope = {"one_way": "one_way", "round_trip": "round_trip", "multi_city": "multi_city"}.get(trip.travel_type, "one_way")
        scope_key = str(old_scope.get("key") or default_scope)
        try:
            new_scope = _scope_from_key(base, scope_key)
        except Exception:
            new_scope = {
                "key": default_scope,
                "label": "Somente ida" if trip.travel_type == "one_way" else ("Ida e volta" if trip.travel_type == "round_trip" else "Multitrecho"),
                "segments": _safe_json(trip.segments_json, []) if trip.travel_type == "multi_city" else [],
                "departure_date": trip.departure_date or "",
                "return_date": trip.return_date or "",
            }

        # Skip mantém o aeroporto adicional digitado pelo usuário.
        extra_airport = _clean_code(old_scope.get("extra_airport"))
        new_scope = dict(new_scope or {})
        if extra_airport:
            new_scope["extra_airport"] = extra_airport
            segments = [dict(item) for item in (new_scope.get("segments") or []) if isinstance(item, dict)]
            if scope_key == "skip_normal" and len(segments) > 1:
                segments[1]["destination"] = extra_airport
            elif scope_key == "skip_inverse" and segments:
                segments[0]["origin"] = extra_airport
            new_scope["segments"] = segments
        for keep in ("skip_mode", "flown_segment"):
            if old_scope.get(keep) not in (None, ""):
                new_scope[keep] = old_scope.get(keep)
        data["_scope"] = new_scope

        new_segments = [dict(item) for item in (new_scope.get("segments") or []) if isinstance(item, dict)]
        by_key = {str(item.get("key") or ""): item for item in new_segments if item.get("key")}
        details = data.get("_flight_details") if isinstance(data.get("_flight_details"), list) else []
        for idx, detail in enumerate(details):
            if not isinstance(detail, dict):
                continue
            key = str(detail.get("segment_key") or "")
            segment = by_key.get(key) or (new_segments[idx] if idx < len(new_segments) else None)
            if not segment:
                continue
            detail["origin"] = _clean_code(segment.get("origin"))
            detail["destination"] = _clean_code(segment.get("destination"))
            if segment.get("date"):
                detail["departure_date"] = str(segment.get("date"))[:10]
        data["_flight_details"] = details

        quote.quote_name = group.quote_name
        quote.origin = group.origin
        quote.destination = group.destination
        quote.passengers = group.passengers
        quote.babies = group.babies
        quote.input_json = json.dumps(data, ensure_ascii=False)

        option_trip = quote.trip
        if option_trip is not None:
            scope_segments = new_segments
            option_trip.travel_type = (
                "round_trip" if scope_key == "round_trip"
                else ("multi_city" if scope_key in {"multi_city", "skip_normal", "skip_inverse"} or len(scope_segments) > 1 else "one_way")
            )
            option_trip.departure_date = str(new_scope.get("departure_date") or trip.departure_date or "")[:20] or None
            option_trip.return_date = str(new_scope.get("return_date") or "")[:20] or None
            option_trip.segments_json = json.dumps(scope_segments, ensure_ascii=False)
            option_trip.client_person_id = trip.client_person_id
            option_trip.client_name = trip.client_name
            option_trip.client_email = trip.client_email
            option_trip.client_phone = trip.client_phone
            option_trip.notes = trip.notes
        updated += 1
    return updated


@router.post("/base/save")
@router.post("/base/save/")
async def save_base(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada. Tente novamente.", "error")
        return RedirectResponse("/calculations/new?clean=1", status_code=303)

    try:
        group_id = int(form.get("group_id") or 0) or None
        passengers = max(1, int(form.get("passengers") or 1))
        babies = max(0, int(form.get("babies") or 0))
        option_id = int(form.get("option_id") or 0) or None
    except ValueError:
        flash(request, "Passageiros ou bebês inválidos.", "error")
        return RedirectResponse("/calculations/new?clean=1", status_code=303)

    travel_type = _normalize_travel_type(
        form.get("travel_type"), segments=form.get("segments_json"), return_date=form.get("return_date")
    )
    try:
        submitted_segments = json.loads(str(form.get("segments_json") or "[]"))
        if not isinstance(submitted_segments, list):
            submitted_segments = []
    except json.JSONDecodeError:
        submitted_segments = []

    normalized_segments: list[dict[str, Any]] = []
    for segment in submitted_segments[:12]:
        if not isinstance(segment, dict):
            continue
        segment_origin = _iata_list_value(segment.get("origin"))
        segment_destination = _iata_list_value(segment.get("destination"))
        if not segment_origin or not segment_destination:
            flash(request, "Há um trecho com origem ou destino inválido. Use um ou vários IATAs de 3 letras; códigos manuais também são aceitos.", "error")
            target = f"/calculations/new?group_id={group_id}&edit_base=1" if group_id else "/calculations/new?clean=1"
            return RedirectResponse(target, status_code=303)
        normalized_segments.append({
            "origin": segment_origin,
            "destination": segment_destination,
            "date": _clean_date_value(segment.get("date")),
        })

    if travel_type == "multi_city":
        if not normalized_segments:
            flash(request, "Adicione pelo menos um trecho no multitrecho.", "error")
            target = f"/calculations/new?group_id={group_id}&edit_base=1" if group_id else "/calculations/new?clean=1"
            return RedirectResponse(target, status_code=303)
        # No multitrecho, a rota principal é derivada dos segmentos.
        origin_code = normalized_segments[0]["origin"]
        destination_code = normalized_segments[-1]["destination"]
    else:
        normalized_segments = []
        origin_code = _iata_list_value(form.get("origin"))
        destination_code = _iata_list_value(form.get("destination"))
        if not origin_code or not destination_code:
            flash(request, "Origem e destino são obrigatórios. Você pode informar um ou vários IATAs separados por vírgula, por exemplo GRU, CGH, VCP.", "error")
            target = f"/calculations/new?group_id={group_id}&edit_base=1" if group_id else "/calculations/new?clean=1"
            return RedirectResponse(target, status_code=303)
        if set(_iata_codes(origin_code)) == set(_iata_codes(destination_code)):
            flash(request, "Origem e destino precisam ter aeroportos diferentes.", "error")
            target = f"/calculations/new?group_id={group_id}&edit_base=1" if group_id else "/calculations/new?clean=1"
            return RedirectResponse(target, status_code=303)

    group = db.get(QuoteGroup, group_id) if group_id else None
    if group_id and not _group_allowed(user, group):
        flash(request, "Você não pode alterar essa cotação principal.", "error")
        return RedirectResponse("/calculations/history", status_code=303)

    is_new_group = group is None
    old_trip = group.trip if group is not None else None
    old_state = {
        "quote_name": str(group.quote_name or "") if group is not None else "",
        "origin": str(group.origin or "") if group is not None else "",
        "destination": str(group.destination or "") if group is not None else "",
        "passengers": int(group.passengers or 1) if group is not None else 1,
        "babies": int(group.babies or 0) if group is not None else 0,
        "travel_type": str(old_trip.travel_type or "") if old_trip is not None else "",
        "departure_date": str(old_trip.departure_date or "") if old_trip is not None else "",
        "return_date": str(old_trip.return_date or "") if old_trip is not None else "",
        "client_name": str(old_trip.client_name or "") if old_trip is not None else "",
    }

    if group is None:
        group = QuoteGroup(
            user_id=user.id,
            company_id=user.company_id,
            assigned_user_id=user.id,
        )
        db.add(group)
    elif not group.assigned_user_id:
        # Registros antigos sem responsável passam a usar o próprio criador.
        group.assigned_user_id = group.user_id or user.id

    group.quote_name = str(form.get("quote_name") or "Nova cotação").strip()[:180] or "Nova cotação"
    group.origin = origin_code
    group.destination = destination_code
    group.passengers = passengers
    group.babies = babies
    # Bagagens não fazem parte da base fixa.
    # Elas são alteráveis apenas durante o cálculo de cada companhia/opção.
    group.bags = 0
    group.source_request_id = int(form.get("source_request_id") or 0) or None
    group.updated_at = datetime.utcnow()
    db.flush()

    trip = group.trip or QuoteGroupTripDetail(group_id=group.id)
    if group.trip is None:
        db.add(trip)
    trip.travel_type = travel_type
    trip.departure_date = (normalized_segments[0].get("date") if travel_type == "multi_city" and normalized_segments else str(form.get("departure_date") or "")[:20]) or None
    trip.return_date = (normalized_segments[-1].get("date") if travel_type == "multi_city" and len(normalized_segments) > 1 else (None if travel_type == "one_way" else (str(form.get("return_date") or "")[:20] or None)))
    try:
        trip.flexibility_days = max(0, min(30, int(form.get("flexibility_days") or 0)))
    except (TypeError, ValueError):
        trip.flexibility_days = 0
    trip.segments_json = json.dumps(normalized_segments, ensure_ascii=False)

    client_name_typed = str(form.get("client_name") or "").strip()[:180]
    try:
        client_person_id = int(form.get("client_person_id") or 0) or None
    except (TypeError, ValueError):
        client_person_id = None
    client_person = db.get(Person, client_person_id) if client_person_id else None
    if client_person is not None and client_person.person_type not in {"cliente", "passageiro"}:
        client_person = None
    if client_name_typed and not _person_allowed(user, client_person):
        flash(request, "Selecione um cliente já cadastrado. Se ele não existir, use o botão Cadastrar cliente.", "error")
        target = f"/calculations/new?group_id={group.id}&edit_base=1" if group.id else "/calculations/new?clean=1"
        return RedirectResponse(target, status_code=303)
    if client_person is not None:
        trip.client_person_id = client_person.id
        trip.client_name = client_person.name
        trip.client_email = str(form.get("client_email") or client_person.email or "").strip()[:180] or None
        trip.client_phone = str(form.get("client_phone") or client_person.phone or client_person.mobile or "").strip()[:60] or None
    else:
        trip.client_person_id = None
        trip.client_name = None
        trip.client_email = str(form.get("client_email") or "").strip()[:180] or None
        trip.client_phone = str(form.get("client_phone") or "").strip()[:60] or None
    trip.notes = str(form.get("notes") or "").strip()[:4000] or None

    if group.source_request_id:
        item = db.get(QuoteRequest, group.source_request_id)
        if _request_allowed(user, item):
            item.read = True

    # Atualiza somente as opções da cotação principal. Subcotações permanecem
    # independentes, mas o histórico da principal passa a refletir a edição.
    _sync_primary_options_with_group(db, group, trip)

    if is_new_group:
        _message, payload = record_quote_activity(
            db, user, group,
            f"Cotação {group.quote_name} criada por {user.name}.",
            event="quote_created",
        )
    else:
        changes: list[str] = []
        old_route = f"{old_state['origin'] or '—'} → {old_state['destination'] or '—'}"
        new_route = f"{group.origin or '—'} → {group.destination or '—'}"
        if old_route != new_route:
            changes.append(f"rota alterada de {old_route} para {new_route}")
        if old_state["quote_name"] != group.quote_name:
            changes.append(f"nome alterado de {old_state['quote_name'] or 'Sem nome'} para {group.quote_name}")
        if old_state["travel_type"] != trip.travel_type:
            changes.append(f"tipo de viagem alterado para {trip.travel_type}")
        if old_state["departure_date"] != str(trip.departure_date or ""):
            changes.append(f"data de ida alterada de {old_state['departure_date'] or 'não informada'} para {trip.departure_date or 'não informada'}")
        if old_state["return_date"] != str(trip.return_date or ""):
            changes.append(f"data de volta alterada de {old_state['return_date'] or 'não informada'} para {trip.return_date or 'não informada'}")
        if old_state["client_name"] != str(trip.client_name or ""):
            changes.append(f"cliente alterado de {old_state['client_name'] or 'não informado'} para {trip.client_name or 'não informado'}")
        if old_state["passengers"] != group.passengers or old_state["babies"] != group.babies:
            changes.append(f"passageiros atualizados para {group.passengers} pagante(s) e {group.babies} bebê(s)")
        audit_text = f"Cotação {group.quote_name}: " + ("; ".join(changes) if changes else "dados confirmados sem alteração de rota ou datas") + "."
        _message, payload = record_quote_activity(
            db, user, group, audit_text, event="quote_base_updated", send_to_chat=False
        )
    db.commit()
    await publish_quote_activity(user.company_id, payload)
    request.session["active_quote_group_id"] = group.id

    # V5.5.6: depois de salvar a base, ir direto para a tela de cálculo
    # da própria cotação, com os dados fixos já carregados. Se houver
    # companhia disponível, a primeira já fica selecionada e o usuário só
    # troca o card da companhia quando quiser calcular outra opção.
    redirect_url = f"/calculations/new?group_id={group.id}&calc=1"
    if option_id:
        link = db.get(QuoteOptionIndex, option_id)
        if link is not None and link.group_id == group.id:
            # A opção já pertence a este grupo: reabre ela com os valores preenchidos.
            redirect_url = f"/calculations/new?edit_id={option_id}&calc=1"
        else:
            # Cotação antiga/legada sem grupo: manda para o mesmo grupo novo,
            # já na companhia certa, sem tentar reabrir a opção antiga
            # (evita ficar voltando pra mesma tela de edição).
            source_option = db.get(WebQuote, option_id)
            if source_option and source_option.airline_id:
                redirect_url += f"&airline_id={source_option.airline_id}"
                if source_option.calculation_type_id:
                    redirect_url += f"&type_id={source_option.calculation_type_id}"
    if "&airline_id=" not in redirect_url and "edit_id=" not in redirect_url:
        airlines, first_airline, _first_type = _selected_airline_and_type(db, user, None, None)
        if first_airline is not None:
            redirect_url += f"&airline_id={first_airline.id}"

    flash(request, "Cotação salva com sucesso. Rota, datas, cliente e opções da cotação principal foram atualizados.", "success")
    return RedirectResponse(redirect_url, status_code=303)


def _sync_variant_passenger_counts(db: Session, group: QuoteGroup, variant_key: str, passengers: int, babies: int) -> int:
    """Atualiza o cadastro de passageiros nas opções já salvas da subcotação.

    Os valores financeiros existentes são preservados. Ao editar/recalcular uma
    opção, a fórmula passa a usar imediatamente a nova quantidade da subcotação.
    """
    links = list(db.scalars(select(QuoteOptionIndex).where(QuoteOptionIndex.group_id == group.id)).all())
    if not links:
        return 0
    quote_ids = [link.quote_id for link in links]
    quotes = list(db.scalars(select(WebQuote).where(WebQuote.id.in_(quote_ids))).all())
    updated = 0
    for quote in quotes:
        data = _quote_input_data(quote)
        variant_data = data.get("_variant") if isinstance(data.get("_variant"), dict) else {}
        if str(variant_data.get("key") or "primary") != variant_key:
            continue
        quote.passengers = passengers
        quote.babies = babies
        variant_data["passengers"] = passengers
        variant_data["babies"] = babies
        data["_variant"] = variant_data
        quote.input_json = json.dumps(data, ensure_ascii=False)
        updated += 1
    return updated


@router.get("/group/{group_id}/variant/new")
def new_group_variant(group_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    group = db.scalar(select(QuoteGroup).where(QuoteGroup.id == group_id).options(selectinload(QuoteGroup.trip)))
    if not _group_allowed(user, group):
        flash(request, "Cotação principal não encontrada.", "error")
        return RedirectResponse("/calculations/history", status_code=303)
    try:
        trip = _ensure_group_trip_detail(db, group)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("Falha ao preparar subcotação do grupo %s: %s", group.id, exc)
        flash(request, "Não foi possível preparar a subcotação. Seus dados foram preservados.", "error")
        return RedirectResponse(f"/calculations/new?group_id={group.id}&calc=1", status_code=303)
    variant = {
        "key": "", "name": f"Subcotação {len(_stored_group_variants(group)) + 1}",
        "origin": group.origin or "", "destination": group.destination or "",
        "passengers": max(1, int(group.passengers or 1)), "babies": max(0, int(group.babies or 0)),
        "travel_type": _normalize_travel_type(
            trip.travel_type, segments=trip.segments_json, return_date=trip.return_date
        ),
        "departure_date": trip.departure_date or "",
        "return_date": trip.return_date or "",
        "flexibility_days": max(0, int(getattr(trip, "flexibility_days", 0) or 0)),
        "segments": _safe_json(trip.segments_json, []),
    }
    return templates.TemplateResponse(request, "calculations/variant_form.html", context(request, user=user, group=group, variant=variant, is_new=True, airport_map=BR_AIRPORTS))


@router.get("/group/{group_id}/variant/{variant_key}/edit")
def edit_group_variant(group_id: int, variant_key: str, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    group = db.scalar(select(QuoteGroup).where(QuoteGroup.id == group_id).options(selectinload(QuoteGroup.trip)))
    if not _group_allowed(user, group):
        flash(request, "Cotação principal não encontrada.", "error")
        return RedirectResponse("/calculations/history", status_code=303)
    try:
        _ensure_group_trip_detail(db, group)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("Falha ao abrir subcotação do grupo %s: %s", group.id, exc)
        flash(request, "Não foi possível abrir a subcotação. Seus dados foram preservados.", "error")
        return RedirectResponse(f"/calculations/new?group_id={group.id}&calc=1", status_code=303)
    variant = next((item for item in _stored_group_variants(group) if item.get("key") == variant_key), None)
    if variant is None:
        flash(request, "Subcotação não encontrada.", "error")
        return RedirectResponse(f"/calculations/new?group_id={group.id}&calc=1", status_code=303)
    return templates.TemplateResponse(request, "calculations/variant_form.html", context(request, user=user, group=group, variant=variant, is_new=False, airport_map=BR_AIRPORTS))


@router.post("/group/{group_id}/variant/save")
async def save_group_variant(group_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse(f"/calculations/group/{group_id}", status_code=303)
    group = db.scalar(select(QuoteGroup).where(QuoteGroup.id == group_id).options(selectinload(QuoteGroup.trip)))
    if not _group_allowed(user, group):
        flash(request, "Cotação principal não encontrada.", "error")
        return RedirectResponse("/calculations/history", status_code=303)
    try:
        trip = _ensure_group_trip_detail(db, group)
    except Exception as exc:
        db.rollback()
        logger.exception("Falha ao iniciar salvamento da subcotação do grupo %s: %s", group.id, exc)
        flash(request, "Não foi possível preparar o banco para a subcotação. Nenhum dado foi perdido.", "error")
        return RedirectResponse(f"/calculations/new?group_id={group.id}&calc=1", status_code=303)

    variants = _stored_group_variants(group)
    variant_key = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(form.get("variant_key") or "")).strip("-")[:60]
    existing = next((item for item in variants if item.get("key") == variant_key), None) if variant_key else None
    if not variant_key:
        if len(variants) >= 20:
            flash(request, "Esta cotação já possui o limite de 20 subcotações.", "error")
            return RedirectResponse(f"/calculations/new?group_id={group.id}&calc=1", status_code=303)
        variant_key = f"sub-{uuid.uuid4().hex[:10]}"

    name = str(form.get("variant_name") or "Subcotação").strip()[:120] or "Subcotação"
    try:
        passengers = max(1, min(100, int(form.get("passengers") or group.passengers or 1)))
        babies = max(0, min(100, int(form.get("babies") or 0)))
    except (TypeError, ValueError):
        flash(request, "Informe uma quantidade válida de passageiros e bebês.", "error")
        target = f"/calculations/group/{group.id}/variant/{variant_key}/edit" if existing else f"/calculations/group/{group.id}/variant/new"
        return RedirectResponse(target, status_code=303)
    travel_type = _normalize_travel_type(
        form.get("travel_type"), segments=form.get("segments_json"), return_date=form.get("return_date")
    )
    try:
        raw_segments = json.loads(str(form.get("segments_json") or "[]"))
    except json.JSONDecodeError:
        raw_segments = []
    if not isinstance(raw_segments, list):
        raw_segments = []
    normalized_segments: list[dict[str, Any]] = []
    for segment in raw_segments[:12]:
        if not isinstance(segment, dict):
            continue
        segment_origin = _iata_list_value(segment.get("origin"))
        segment_destination = _iata_list_value(segment.get("destination"))
        if not segment_origin or not segment_destination:
            flash(request, "Há um trecho da subcotação com origem ou destino inválido. Use um ou vários IATAs de 3 letras.", "error")
            target = f"/calculations/group/{group.id}/variant/{variant_key}/edit" if existing else f"/calculations/group/{group.id}/variant/new"
            return RedirectResponse(target, status_code=303)
        normalized_segments.append({
            "origin": segment_origin,
            "destination": segment_destination,
            "date": _clean_date_value(segment.get("date")),
        })
    if travel_type == "multi_city":
        if not normalized_segments:
            flash(request, "Adicione pelo menos um trecho na subcotação multitrecho.", "error")
            target = f"/calculations/group/{group.id}/variant/{variant_key}/edit" if existing else f"/calculations/group/{group.id}/variant/new"
            return RedirectResponse(target, status_code=303)
        origin_code = normalized_segments[0]["origin"]
        destination_code = normalized_segments[-1]["destination"]
    else:
        normalized_segments = []
        origin_code = _iata_list_value(form.get("origin"))
        destination_code = _iata_list_value(form.get("destination"))
        if not origin_code or not destination_code:
            flash(request, "Origem e destino da subcotação são obrigatórios. Você pode informar vários IATAs separados por vírgula.", "error")
            target = f"/calculations/group/{group.id}/variant/{variant_key}/edit" if existing else f"/calculations/group/{group.id}/variant/new"
            return RedirectResponse(target, status_code=303)

    payload = {
        "key": variant_key,
        "name": name,
        "origin": origin_code,
        "destination": destination_code,
        "passengers": passengers,
        "babies": babies,
        "travel_type": travel_type,
        "departure_date": _clean_date_value(form.get("departure_date")),
        "return_date": "" if travel_type == "one_way" else _clean_date_value(form.get("return_date")),
        "flexibility_days": max(0, min(30, int(form.get("flexibility_days") or 0))) if str(form.get("flexibility_days") or "0").lstrip("-").isdigit() else 0,
        "segments": normalized_segments,
    }
    if existing is None:
        variants.append(payload)
    else:
        variants = [payload if item.get("key") == variant_key else item for item in variants]
    try:
        trip.variants_json = json.dumps(variants, ensure_ascii=False)
        synced_options = _sync_variant_passenger_counts(db, group, variant_key, passengers, babies)
        group.updated_at = datetime.utcnow()
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("Falha ao salvar subcotação do grupo %s: %s", group.id, exc)
        flash(request, "Não foi possível salvar a subcotação. O banco foi preservado e nenhuma informação foi perdida.", "error")
        return RedirectResponse(f"/calculations/new?group_id={group.id}&calc=1", status_code=303)
    message = f"Subcotação salva com {passengers} passageiro(s) pagante(s) e {babies} bebê(s)."
    if synced_options:
        message += f" O cadastro de passageiros foi atualizado em {synced_options} opção(ões) existente(s); os valores antigos foram preservados até você recalcular."
    flash(request, message, "success")
    return RedirectResponse(f"/calculations/new?group_id={group.id}&variant_key={variant_key}&calc=1", status_code=303)


@router.post("/group/{group_id}/variant/{variant_key}/delete")
async def delete_group_variant(group_id: int, variant_key: str, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse(f"/calculations/group/{group_id}", status_code=303)
    group = db.scalar(select(QuoteGroup).where(QuoteGroup.id == group_id).options(selectinload(QuoteGroup.trip)))
    if not _group_allowed(user, group) or variant_key == "primary":
        flash(request, "Subcotação não encontrada.", "error")
        return RedirectResponse(f"/calculations/group/{group_id}", status_code=303)
    try:
        trip = _ensure_group_trip_detail(db, group)
    except Exception as exc:
        db.rollback()
        logger.exception("Falha ao preparar exclusão da subcotação do grupo %s: %s", group.id, exc)
        flash(request, "Não foi possível preparar a exclusão. Seus dados foram preservados.", "error")
        return RedirectResponse(f"/calculations/new?group_id={group.id}&calc=1", status_code=303)
    variants = _stored_group_variants(group)
    if not any(item.get("key") == variant_key for item in variants):
        flash(request, "Subcotação não encontrada.", "error")
        return RedirectResponse(f"/calculations/group/{group_id}", status_code=303)

    # Exclui também as opções calculadas exclusivamente para esta subcotação.
    for quote in _load_options(db, user, group.id):
        if str(getattr(quote, "variant_key", "primary")) == variant_key:
            link = db.get(QuoteOptionIndex, quote.id)
            if link is not None:
                db.delete(link)
            db.delete(quote)
    try:
        trip.variants_json = json.dumps([item for item in variants if item.get("key") != variant_key], ensure_ascii=False)
        group.updated_at = datetime.utcnow()
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("Falha ao excluir subcotação do grupo %s: %s", group.id, exc)
        flash(request, "Não foi possível excluir a subcotação. O banco foi preservado.", "error")
        return RedirectResponse(f"/calculations/new?group_id={group.id}&calc=1", status_code=303)
    flash(request, "Subcotação e suas opções foram excluídas.", "success")
    return RedirectResponse(f"/calculations/new?group_id={group.id}&calc=1", status_code=303)


@router.post("/calculate")
async def calculate_route(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)

    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada. Tente novamente.", "error")
        return RedirectResponse("/calculations/new", status_code=303)

    try:
        group_id = int(form.get("group_id") or 0)
        airline_id = int(form.get("airline_id") or 0)
        type_id = int(form.get("calculation_type_id") or 0)
        option_id = int(form.get("option_id") or 0) or None
    except ValueError:
        flash(request, "Cotação, companhia ou tipo de cálculo inválido.", "error")
        return RedirectResponse("/calculations/new", status_code=303)

    group = db.scalar(select(QuoteGroup).where(QuoteGroup.id == group_id).options(selectinload(QuoteGroup.trip), selectinload(QuoteGroup.user).selectinload(WebUser.profile), selectinload(QuoteGroup.assigned_user).selectinload(WebUser.profile)))
    if not _group_allowed(user, group):
        flash(request, "Crie ou abra uma cotação principal antes de calcular uma companhia.", "error")
        return RedirectResponse("/calculations/new?clean=1", status_code=303)

    existing_option = db.scalar(
        select(WebQuote)
        .where(WebQuote.id == option_id)
        .options(selectinload(WebQuote.trip))
    ) if option_id else None
    if option_id and not _quote_allowed(user, existing_option):
        flash(request, "Você não pode alterar essa opção.", "error")
        return RedirectResponse(f"/calculations/group/{group.id}", status_code=303)
    existing_input = _quote_input_data(existing_option)
    existing_scope = existing_input.get("_scope") if isinstance(existing_input.get("_scope"), dict) else {}

    variant_key = str(form.get("variant_key") or "primary").strip() or "primary"
    if variant_key == "primary" and _recover_group_route_from_options(db, user, group):
        db.commit()
    base_for_scope = _base_from_group(group, variant_key)
    selected_scope = _scope_from_key(base_for_scope, str(form.get("scope_key") or ""))
    selected_segments = [dict(segment) for segment in (selected_scope.get("segments") or [])]
    scope_key = str(selected_scope.get("key") or "one_way")
    is_skip_record = scope_key in {"skip_normal", "skip_inverse"}
    option_departure_date = str(form.get("option_departure_date") or "").strip()
    option_return_date = str(form.get("option_return_date") or "").strip()
    dates_touched = str(form.get("option_dates_touched") or "0") == "1"
    if existing_option is not None and not dates_touched:
        option_departure_date = option_departure_date or str(existing_scope.get("departure_date") or "")
        option_return_date = option_return_date or str(existing_scope.get("return_date") or "")
    skip_airport = ""

    if is_skip_record:
        route_origin = _required_iata_code(base_for_scope.get("origin"))
        route_destination = _required_iata_code(base_for_scope.get("destination"))
        if not route_origin or not route_destination:
            flash(request, "Para usar Skip, altere a cotação e informe origem e destino válidos.", "error")
            return RedirectResponse(f"/calculations/new?group_id={group.id}&variant_key={variant_key}&edit_base=1", status_code=303)

    skip_edit_origin = ""
    skip_edit_destination = ""
    skip_edit_date = ""
    if selected_scope.get("requires_skip_airport"):
        # Somente o trecho NÃO VOADO é editável. O trecho voado permanece
        # exatamente como foi definido na cotação principal.
        skip_edit_origin = _iata_list_value(form.get("skip_edit_origin"))
        skip_edit_destination = _iata_list_value(form.get("skip_edit_destination"))
        skip_edit_date = _clean_date_value(form.get("skip_edit_date"))
        if not skip_edit_origin or not skip_edit_destination:
            flash(request, "Informe origem e destino do trecho não voado do Skip. Você pode usar um ou vários IATAs.", "error")
            return RedirectResponse(f"/calculations/new?group_id={group.id}&variant_key={variant_key}&calc=1", status_code=303)
        if set(_iata_codes(skip_edit_origin)) == set(_iata_codes(skip_edit_destination)):
            flash(request, "Origem e destino do trecho não voado precisam ser diferentes.", "error")
            return RedirectResponse(f"/calculations/new?group_id={group.id}&variant_key={variant_key}&calc=1", status_code=303)
        if scope_key == "skip_normal" and len(selected_segments) > 1:
            selected_segments[1]["origin"] = skip_edit_origin
            selected_segments[1]["destination"] = skip_edit_destination
            selected_segments[1]["date"] = skip_edit_date
            selected_segments[1]["label"] = f"Trecho 2 • {skip_edit_origin} → {skip_edit_destination}"
        elif scope_key == "skip_inverse" and selected_segments:
            selected_segments[0]["origin"] = skip_edit_origin
            selected_segments[0]["destination"] = skip_edit_destination
            selected_segments[0]["date"] = skip_edit_date
            selected_segments[0]["label"] = f"Trecho 1 • {skip_edit_origin} → {skip_edit_destination}"
        skip_airport = skip_edit_destination if scope_key == "skip_normal" else skip_edit_origin

    if scope_key == "round_trip":
        if selected_segments:
            selected_segments[0]["date"] = option_departure_date
        if len(selected_segments) > 1:
            selected_segments[-1]["date"] = option_return_date
    elif scope_key == "return":
        selected_date = option_return_date or option_departure_date
        if selected_segments:
            selected_segments[0]["date"] = selected_date
        option_departure_date = ""
        option_return_date = selected_date
    elif scope_key == "multi_city":
        if selected_segments and option_departure_date:
            selected_segments[0]["date"] = option_departure_date
        if len(selected_segments) > 1 and option_return_date:
            selected_segments[-1]["date"] = option_return_date
    elif scope_key == "skip_normal":
        if selected_segments and option_departure_date:
            selected_segments[0]["date"] = option_departure_date
    elif scope_key == "skip_inverse":
        if len(selected_segments) > 1 and option_return_date:
            selected_segments[1]["date"] = option_return_date
    else:
        if selected_segments:
            selected_segments[0]["date"] = option_departure_date
        option_return_date = ""

    submitted_flight_details = form.get("flight_details_json") or "[]"
    flight_details = _normalize_flight_details(
        submitted_flight_details,
        selected_segments,
        scope_key,
    )
    details_touched = str(form.get("flight_details_touched") or "0") == "1"
    # Uma edição de tarifa/classe não pode apagar horários já registrados só
    # porque o navegador não executou o JavaScript ou enviou o campo oculto vazio.
    if existing_option is not None and not details_touched and not flight_details:
        previous_details = existing_input.get("_flight_details")
        flight_details = _normalize_flight_details(previous_details or [], selected_segments, scope_key)

    # Quando o usuário informa datas somente nos detalhes de voo, a primeira
    # possibilidade alimenta também a data-resumo da opção. As demais continuam
    # salvas como flexibilidade e aparecem em selos no histórico.
    if scope_key == "return":
        if not option_return_date:
            option_return_date = next((str(item.get("departure_date") or "") for item in flight_details if item.get("segment_key") == "return" and item.get("departure_date")), "")
        if selected_segments and option_return_date:
            selected_segments[0]["date"] = option_return_date
    else:
        if not option_departure_date:
            option_departure_date = next((str(item.get("departure_date") or "") for item in flight_details if item.get("segment_key") != "return" and item.get("departure_date")), "")
        if scope_key == "round_trip" and not option_return_date:
            option_return_date = next((str(item.get("departure_date") or "") for item in flight_details if item.get("segment_key") == "return" and item.get("departure_date")), "")
        if scope_key in {"multi_city", "skip_normal", "skip_inverse"} and len(selected_segments) > 1 and not option_return_date:
            last_key = str(selected_segments[-1].get("key") or "")
            option_return_date = next((str(item.get("departure_date") or "") for item in flight_details if item.get("segment_key") == last_key and item.get("departure_date")), "")
        if selected_segments and option_departure_date:
            selected_segments[0]["date"] = option_departure_date
        if scope_key in {"round_trip", "multi_city", "skip_normal", "skip_inverse"} and len(selected_segments) > 1 and option_return_date:
            selected_segments[-1]["date"] = option_return_date

    airline = db.scalar(
        _visible_airlines_query(user)
        .where(Airline.id == airline_id)
        .options(selectinload(Airline.calculation_types).selectinload(CalculationType.fields))
    )
    if airline is None:
        flash(request, "Companhia não encontrada.", "error")
        return RedirectResponse(f"/calculations/new?group_id={group.id}&variant_key={variant_key}", status_code=303)

    calc_type = next((item for item in airline.calculation_types if item.id == type_id and item.active), None)
    if calc_type is None:
        flash(request, "Tipo de cálculo não encontrado.", "error")
        return RedirectResponse(f"/calculations/new?group_id={group.id}&variant_key={variant_key}&airline_id={airline.id}", status_code=303)

    try:
        extra_value = 0.0 if is_skip_record else _parse_amount(form.get("extra_value") or 0, field_name="custo adicional")
        skip_value = _parse_amount(form.get("skip_value") or 0, field_name="valor do Skip") if is_skip_record else 0.0
        skip_commission = _parse_amount(form.get("skip_commission") or 0, field_name="comissão") if is_skip_record else 0.0
    except ValueError as exc:
        flash(request, str(exc).capitalize() + ".", "error")
        return RedirectResponse(f"/calculations/new?group_id={group.id}&variant_key={variant_key}&airline_id={airline.id}&type_id={calc_type.id}", status_code=303)

    if is_skip_record and skip_value <= 0:
        flash(request, "Informe o valor da opção Skip.", "error")
        return RedirectResponse(f"/calculations/new?group_id={group.id}&variant_key={variant_key}&airline_id={airline.id}&type_id={calc_type.id}", status_code=303)

    values: dict[str, Any] = {}
    fields = _effective_calculation_fields(db, calc_type)

    if not is_skip_record:
        for field in fields:
            value = form.get(f"field_{field.key}")
            if field.required and (value is None or str(value).strip() == ""):
                flash(request, f"Preencha o campo: {field.label}.", "error")
                return RedirectResponse(f"/calculations/new?group_id={group.id}&variant_key={variant_key}&airline_id={airline.id}&type_id={calc_type.id}", status_code=303)
            values[field.key] = str(value or field.default_value or "0")

    if not is_skip_record and (calc_type.legacy_key == "american_milhas" or (airline.slug == "american" and any(field.key == "rota_american" for field in fields))):
        route_fees = {
            "Brasil ↔ EUA": 100.0,
            "EUA / Canadá / Caribe / México": 90.0,
            "América do Sul ↔ EUA": 95.0,
            "EUA ↔ Panamá / Colômbia / Peru / Equador": 85.0,
        }
        values["bagagem_unitaria"] = str(route_fees.get(values.get("rota_american"), 100.0))

    values["_scope"] = {
        "key": selected_scope.get("key"),
        "label": selected_scope.get("label"),
        "hint": selected_scope.get("hint"),
        "segments": selected_segments,
        "departure_date": option_departure_date,
        "return_date": option_return_date,
        "requires_skip_airport": bool(selected_scope.get("requires_skip_airport")),
        "skip_mode": str(selected_scope.get("skip_mode") or ""),
        "extra_airport": skip_airport,
        "editable_origin": skip_edit_origin,
        "editable_destination": skip_edit_destination,
        "editable_date": skip_edit_date,
        "flown_segment": selected_scope.get("flown_segment"),
    }
    calculation_passengers = max(1, int(base_for_scope.get("passengers") or group.passengers or 1))
    calculation_babies = max(0, int(base_for_scope.get("babies") if base_for_scope.get("babies") is not None else (group.babies or 0)))
    values["_variant"] = {
        "key": str(base_for_scope.get("variant_key") or "primary"),
        "name": str(base_for_scope.get("variant_name") or "Cotação principal"),
        "passengers": calculation_passengers,
        "babies": calculation_babies,
        "flexibility_days": max(0, int(base_for_scope.get("flexibility_days") or 0)),
    }
    values["_flight_details"] = flight_details
    values["_skip_financial"] = {
        "value": skip_value if is_skip_record else 0.0,
        "commission": skip_commission if is_skip_record else 0.0,
        "record_only": bool(is_skip_record),
    }
    operation_profile = _airline_operation_profile(airline)
    raw_operation_scope = str(form.get("operation_scope") or operation_profile.get("fixed_market") or "national").strip().lower()
    if raw_operation_scope not in {"national", "international"}:
        raw_operation_scope = str(operation_profile.get("fixed_market") or "national")
    raw_partner_values = [str(form.get("partner_airline") or "").strip()]
    raw_partner_values.extend(str(form.get(f"partner_segment_{number}") or "").strip() for number in range(1, 13))
    allowed_partner_map: dict[str, str] = {}
    if any(raw_partner_values):
        visible_partner_airlines = list(db.scalars(_visible_airlines_query(user).where(Airline.active.is_(True))).all())
        allowed_partners = _partner_airline_choices(visible_partner_airlines, airline)
        allowed_partner_map = {_normalized_token(name): name for name in allowed_partners}

    def normalized_partner(raw_value: Any) -> str:
        raw_name = " ".join(str(raw_value or "").split()).strip()[:180]
        if not raw_name:
            return ""
        # Se já existe no cadastro, usa a grafia canônica. Se ainda não existe,
        # aceita o nome manualmente para não bloquear nenhuma companhia.
        return str(allowed_partner_map.get(_normalized_token(raw_name)) or raw_name)

    partner_airline = normalized_partner(form.get("partner_airline"))
    segment_partners: list[dict[str, Any]] = []
    for segment_number in range(1, 13):
        partner_name = normalized_partner(form.get(f"partner_segment_{segment_number}"))
        if partner_name:
            segment_partners.append({"segment": segment_number, "partner_airline": partner_name})
    if segment_partners and not partner_airline:
        partner_airline = str(segment_partners[0].get("partner_airline") or "")
    if not operation_profile.get("partner_allowed"):
        partner_airline = ""
        segment_partners = []
    values["_partnership"] = {
        "operation_scope": raw_operation_scope,
        "partner_airline": partner_airline,
        "segment_partners": segment_partners,
    }
    values["_meta"] = {
        "fare_brand": str(form.get("fare_brand") or "").strip(),
        "cabin_class": str(form.get("cabin_class") or "").strip(),
        "description": str(form.get("option_description") or "").strip(),
        "extra_name": str(form.get("extra_name") or "").strip(),
        "extra_value": str(form.get("extra_value") or "0").strip(),
    }

    try:
        option_bags_count = 0 if is_skip_record else max(0, int(form.get("bags_override") or 0))
    except ValueError:
        flash(request, "Quantidade de bagagens inválida.", "error")
        return RedirectResponse(f"/calculations/new?group_id={group.id}&variant_key={variant_key}&airline_id={airline.id}&type_id={calc_type.id}", status_code=303)

    try:
        if is_skip_record:
            result = CalculationResult(
                base=skip_value,
                baggage_total=0.0,
                extra_total=0.0,
                total=skip_value,
                breakdown={
                    "modo": "registro_skip",
                    "valor_registrado": skip_value,
                    "comissao_registrada": skip_commission,
                    "trecho_voado": selected_scope.get("flown_segment"),
                    "observacao": "Valor informado manualmente apenas para registro da opção Skip.",
                },
            )
        else:
            result = calculate(
                airline=airline,
                calculation_type=calc_type,
                values=values,
                passengers=calculation_passengers,
                babies=calculation_babies,
                bags=option_bags_count,
                extra_name=str(form.get("extra_name") or "").strip(),
                extra_value=extra_value,
            )
    except Exception as exc:
        flash(request, f"Não foi possível calcular: {exc}", "error")
        return RedirectResponse(f"/calculations/new?group_id={group.id}&variant_key={variant_key}&airline_id={airline.id}&type_id={calc_type.id}", status_code=303)

    quote = existing_option
    if quote is None:
        quote = WebQuote(user_id=user.id, company_id=user.company_id)
        db.add(quote)

    quote.airline_id = airline.id
    quote.calculation_type_id = calc_type.id
    quote.quote_name = group.quote_name
    if selected_segments:
        quote.origin = selected_segments[0].get("origin") or base_for_scope.get("origin") or group.origin
        quote.destination = selected_segments[-1].get("destination") or base_for_scope.get("destination") or group.destination
    else:
        quote.origin = base_for_scope.get("origin") or group.origin
        quote.destination = base_for_scope.get("destination") or group.destination
    quote.passengers = calculation_passengers
    quote.babies = calculation_babies
    quote.bags = option_bags_count
    quote.currency = "BRL"
    quote.input_json = json.dumps(values, ensure_ascii=False)
    quote.breakdown_json = json.dumps(result.breakdown, ensure_ascii=False)
    quote.total = result.total
    db.flush()

    trip = quote.trip or QuoteTripDetail(quote_id=quote.id)
    if quote.trip is None:
        db.add(trip)
    base_trip = group.trip
    if scope_key == "round_trip":
        trip.travel_type = "round_trip"
    elif scope_key in {"multi_city", "skip_normal", "skip_inverse"} or (scope_key.startswith("segment_") and len(selected_segments) > 1):
        trip.travel_type = "multi_city"
    else:
        trip.travel_type = "one_way"

    first_segment_date = selected_segments[0].get("date") if selected_segments else None
    last_segment_date = selected_segments[-1].get("date") if len(selected_segments) > 1 else None
    trip.departure_date = first_segment_date or (option_return_date if scope_key == "return" else option_departure_date) or None
    trip.return_date = (option_return_date or last_segment_date or None) if scope_key in {"round_trip", "multi_city", "skip_normal", "skip_inverse"} else None
    trip.segments_json = json.dumps(selected_segments, ensure_ascii=False) if selected_segments else (base_trip.segments_json if base_trip else "[]")
    trip.client_name = base_trip.client_name if base_trip else None
    trip.client_email = base_trip.client_email if base_trip else None
    trip.client_phone = base_trip.client_phone if base_trip else None
    trip.notes = base_trip.notes if base_trip else None

    link = db.get(QuoteOptionIndex, quote.id)
    if link is None:
        current_count = db.scalar(select(QuoteOptionIndex).where(QuoteOptionIndex.group_id == group.id).count()) if False else None
        max_position = 0
        existing = db.scalars(select(QuoteOptionIndex).where(QuoteOptionIndex.group_id == group.id)).all()
        if existing:
            max_position = max(item.position for item in existing)
        link = QuoteOptionIndex(quote_id=quote.id, group_id=group.id, position=max_position + 1)
        db.add(link)
    else:
        link.group_id = group.id

    group.updated_at = datetime.utcnow()
    # Cálculos continuam registrados dentro da cotação, mas não geram mensagens
    # automáticas no chat nem poluem a linha do tempo de alterações.
    _message, payload = record_quote_activity(
        db, user, group,
        f"Cálculo de {airline.name} salvo na cotação {group.quote_name}.",
        event="quote_calculation_saved",
        send_to_chat=False,
        record_audit=False,
    )
    db.commit()
    await publish_quote_activity(user.company_id, payload)
    request.session["active_quote_group_id"] = group.id
    flash(request, "Opção atualizada dentro da cotação principal." if option_id else "Opção calculada e adicionada à cotação principal. Você pode trocar o card da companhia e calcular outra opção.", "success")
    return RedirectResponse(f"/calculations/new?group_id={group.id}&variant_key={variant_key}&airline_id={airline.id}&type_id={calc_type.id}", status_code=303)


@router.get("/group/{group_id}")
def group_detail(group_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    group = db.scalar(select(QuoteGroup).where(QuoteGroup.id == group_id).options(selectinload(QuoteGroup.trip), selectinload(QuoteGroup.user).selectinload(WebUser.profile), selectinload(QuoteGroup.assigned_user).selectinload(WebUser.profile)))
    if not _group_allowed(user, group):
        flash(request, "Cotação principal não encontrada.", "error")
        return RedirectResponse("/calculations/history", status_code=303)
    request.session["active_quote_group_id"] = group.id
    options = _load_options(db, user, group.id)
    return templates.TemplateResponse(
        request,
        "calculations/group.html",
        context(
            request,
            user=user,
            group=group,
            base=_base_from_group(group),
            options=options,
            option_groups=_group_options_by_scope(options),
            option_variant_groups=_group_options_by_variant(options, group),
            group_variants=_group_variant_cards(group),
            team_users=_team_users(db, user),
        ),
    )


@router.post("/group/{group_id}/client")
async def update_group_client(group_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse(f"/calculations/group/{group_id}", status_code=303)
    group = db.scalar(select(QuoteGroup).where(QuoteGroup.id == group_id).options(selectinload(QuoteGroup.trip)))
    if not _group_allowed(user, group):
        flash(request, "Cotação não encontrada.", "error")
        return RedirectResponse("/calculations/history", status_code=303)
    typed_name = str(form.get("client_name") or "").strip()
    try:
        person_id = int(form.get("client_person_id") or 0) or None
    except (TypeError, ValueError):
        person_id = None
    person = db.get(Person, person_id) if person_id else None
    if typed_name and (person is None or not _person_allowed(user, person) or person.person_type not in {"cliente", "passageiro"}):
        flash(request, "Selecione um cliente cadastrado. Se ele ainda não existir, use o botão Cadastrar cliente.", "error")
        return RedirectResponse(f"/calculations/group/{group.id}", status_code=303)
    trip = _ensure_group_trip_detail(db, group)
    old_name = str(trip.client_name or "Não informado")
    if person is None:
        trip.client_person_id = None
        trip.client_name = None
        trip.client_email = None
        trip.client_phone = None
        new_name = "Não informado"
    else:
        trip.client_person_id = person.id
        trip.client_name = person.name
        trip.client_email = person.email or None
        trip.client_phone = person.mobile or person.phone or None
        new_name = person.name
    group.updated_at = datetime.utcnow()
    _sync_primary_options_with_group(db, group, trip)
    _message, payload = record_quote_activity(
        db, user, group,
        f"Cliente da cotação {group.quote_name} alterado de {old_name} para {new_name}.",
        event="quote_client_changed",
        send_to_chat=False,
    )
    db.commit()
    await publish_quote_activity(user.company_id, payload)
    flash(request, "Cliente atualizado na cotação.", "success")
    return RedirectResponse(f"/calculations/group/{group.id}", status_code=303)


@router.post("/group/{group_id}/assign")
async def assign_group_user(group_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    form = await request.form()
    return_to = str(form.get("return_to") or f"/calculations/group/{group_id}").strip()
    if not return_to.startswith("/") or return_to.startswith("//"):
        return_to = f"/calculations/group/{group_id}"
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse(return_to, status_code=303)
    group = db.scalar(select(QuoteGroup).where(QuoteGroup.id == group_id).options(selectinload(QuoteGroup.assigned_user)))
    if not _group_allowed(user, group):
        flash(request, "Cotação não encontrada.", "error")
        return RedirectResponse("/calculations/history", status_code=303)
    try:
        assigned_user_id = int(form.get("assigned_user_id") or 0) or None
    except (TypeError, ValueError):
        assigned_user_id = None
    # Sem seleção explícita, mantém o criador como responsável padrão.
    assigned_user_id = assigned_user_id or group.user_id
    assigned = db.scalar(select(WebUser).where(WebUser.id == assigned_user_id, WebUser.active.is_(True)))
    if assigned is None or (user.company_id and assigned.company_id != user.company_id) or (not user.company_id and assigned.id != user.id):
        flash(request, "Usuário da empresa não encontrado.", "error")
        return RedirectResponse(return_to, status_code=303)
    old_id = group.assigned_user_id or group.user_id
    old_name = group.assigned_user.name if group.assigned_user else (group.user.name if getattr(group, "user", None) else "Criador")
    group.assigned_user_id = assigned.id
    group.updated_at = datetime.utcnow()
    new_name = assigned.name
    payload = None
    if old_id != assigned.id:
        _message, payload = record_quote_activity(
            db, user, group,
            f"Cotação {group.quote_name} transferida para {new_name}.",
            event="quote_assigned",
        )
    db.commit()
    await publish_quote_activity(user.company_id, payload)
    flash(request, f"Responsável atualizado: {new_name}.", "success")
    return RedirectResponse(return_to, status_code=303)


@router.get("/result/{quote_id}")
def result_page(quote_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)

    quote = db.scalar(
        select(WebQuote)
        .where(WebQuote.id == quote_id)
        .options(selectinload(WebQuote.airline), selectinload(WebQuote.calculation_type), selectinload(WebQuote.trip), selectinload(WebQuote.commercial), selectinload(WebQuote.user).selectinload(WebUser.profile))
    )
    if not _quote_allowed(user, quote):
        flash(request, "Cotação não encontrada.", "error")
        return RedirectResponse("/calculations/history", status_code=303)

    quote = _decorate_quote_scope(quote)
    link = db.get(QuoteOptionIndex, quote.id)
    inputs = _safe_json(quote.input_json, {})
    breakdown = _safe_json(quote.breakdown_json, {})
    segments = _safe_json(quote.trip.segments_json, []) if quote.trip else []
    return templates.TemplateResponse(request, "calculations/result.html", context(request, user=user, quote=quote, group_id=link.group_id if link else None, inputs=inputs, breakdown=breakdown, segments=segments))


@router.get("/history")
def history(request: Request, q: str = "", page: int = 1, db: Session = Depends(get_db)):
    """Histórico paginado no PostgreSQL.

    Não baixa mais todos os IDs do histórico para ordenar em Python. O banco
    une grupos + cotações legadas, ordena e devolve somente a página atual.
    """
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)

    page_size = 24
    try:
        page = max(1, int(page or 1))
    except (TypeError, ValueError):
        page = 1
    q = q.strip()

    group_filter = (
        or_(QuoteGroup.company_id == user.company_id, QuoteGroup.user_id == user.id)
        if user.company_id
        else QuoteGroup.user_id == user.id
    )
    group_conditions = [group_filter]
    if q:
        pattern = f"%{q}%"
        group_conditions.append(
            or_(
                QuoteGroup.quote_name.ilike(pattern),
                QuoteGroup.origin.ilike(pattern),
                QuoteGroup.destination.ilike(pattern),
            )
        )

    linked_ids = select(QuoteOptionIndex.quote_id)
    access_filter = (
        or_(WebQuote.company_id == user.company_id, WebQuote.user_id == user.id)
        if user.company_id
        else WebQuote.user_id == user.id
    )
    legacy_conditions = [access_filter, WebQuote.id.notin_(linked_ids)]
    if q:
        pattern = f"%{q}%"
        legacy_conditions.append(
            or_(
                WebQuote.quote_name.ilike(pattern),
                WebQuote.origin.ilike(pattern),
                WebQuote.destination.ilike(pattern),
            )
        )

    group_timeline = select(
        QuoteGroup.created_at.label("sort_at"),
        QuoteGroup.id.label("sort_id"),
        literal("group").label("kind"),
        QuoteGroup.id.label("item_id"),
    ).where(*group_conditions)
    legacy_timeline = select(
        WebQuote.created_at.label("sort_at"),
        WebQuote.id.label("sort_id"),
        literal("legacy").label("kind"),
        WebQuote.id.label("item_id"),
    ).where(*legacy_conditions)

    timeline_sq = union_all(group_timeline, legacy_timeline).subquery("history_timeline")
    total_items = int(db.scalar(select(func.count()).select_from(timeline_sq)) or 0)
    total_pages = max(1, (total_items + page_size - 1) // page_size)
    page = min(page, total_pages)
    offset = (page - 1) * page_size

    page_rows = db.execute(
        select(
            timeline_sq.c.sort_at,
            timeline_sq.c.sort_id,
            timeline_sq.c.kind,
            timeline_sq.c.item_id,
        )
        .order_by(timeline_sq.c.sort_at.desc(), timeline_sq.c.sort_id.desc())
        .offset(offset)
        .limit(page_size)
    ).all()
    page_entries = [
        (row.sort_at or datetime.min, int(row.sort_id or 0), str(row.kind), int(row.item_id))
        for row in page_rows
    ]

    selected_group_ids = [item[3] for item in page_entries if item[2] == "group"]
    selected_legacy_ids = [item[3] for item in page_entries if item[2] == "legacy"]

    groups_by_id: dict[int, QuoteGroup] = {}
    if selected_group_ids:
        loaded_groups = db.scalars(
            select(QuoteGroup)
            .where(QuoteGroup.id.in_(selected_group_ids), group_filter)
            .options(
                selectinload(QuoteGroup.trip),
                selectinload(QuoteGroup.user).selectinload(WebUser.profile),
                selectinload(QuoteGroup.assigned_user).selectinload(WebUser.profile),
            )
        ).all()
        groups_by_id = {item.id: item for item in loaded_groups}

    legacy_by_id: dict[int, WebQuote] = {}
    if selected_legacy_ids:
        loaded_legacy = db.scalars(
            select(WebQuote)
            .where(WebQuote.id.in_(selected_legacy_ids), access_filter)
            .options(
                selectinload(WebQuote.airline),
                selectinload(WebQuote.calculation_type),
                selectinload(WebQuote.trip),
                selectinload(WebQuote.commercial),
                selectinload(WebQuote.user),
            )
        ).all()
        legacy_by_id = {item.id: item for item in loaded_legacy}

    page_groups = [groups_by_id[gid] for gid in selected_group_ids if gid in groups_by_id]
    group_cards_batch = _history_group_cards_batch(db, user, page_groups)

    history_entries: list[dict[str, Any]] = []
    history_load_errors = 0
    for _sort_at, _sort_id, kind, item_id in page_entries:
        if kind == "group":
            card = group_cards_batch.get(item_id)
            if card is None:
                continue
            history_load_errors += 1 if card.get("load_error") else 0
            history_entries.append({"kind": "group", "card": card})
        else:
            quote = legacy_by_id.get(item_id)
            if quote is None:
                continue
            history_entries.append({"kind": "legacy", "quote": _decorate_quote_scope(quote)})

    group_cards = [item["card"] for item in history_entries if item["kind"] == "group"]
    legacy_quotes = [item["quote"] for item in history_entries if item["kind"] == "legacy"]

    return templates.TemplateResponse(
        request,
        "calculations/history.html",
        context(
            request,
            user=user,
            history_entries=history_entries,
            group_cards=group_cards,
            legacy_quotes=legacy_quotes,
            search_query=q,
            history_load_errors=history_load_errors,
            team_users=_team_users(db, user),
            page=page,
            page_size=page_size,
            total_items=total_items,
            total_pages=total_pages,
            has_previous=page > 1,
            has_next=page < total_pages,
        ),
    )


@router.post("/option/{quote_id}/delete")
async def delete_option(quote_id: int, request: Request, db: Session = Depends(get_db)):
    """Exclui somente uma opção/voo calculado, preservando a cotação principal."""
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/calculations/history", status_code=303)

    quote = db.get(WebQuote, quote_id)
    link = db.get(QuoteOptionIndex, quote_id)
    if not _quote_allowed(user, quote) or link is None:
        flash(request, "Opção calculada não encontrada.", "error")
        return RedirectResponse("/calculations/history", status_code=303)
    group = db.get(QuoteGroup, link.group_id)
    if not _group_allowed(user, group):
        flash(request, "Cotação principal não encontrada.", "error")
        return RedirectResponse("/calculations/history", status_code=303)

    # Se a opção já virou reserva/voo operacional, preserva a reserva e apenas
    # solta a referência para que o histórico aceito não seja apagado junto.
    accepted = db.get(AcceptedQuote, group.id)
    if accepted is not None and accepted.quote_id == quote_id:
        accepted.quote_id = None
    flight = db.get(FlightRegistry, group.id)
    if flight is not None and flight.quote_id == quote_id:
        flight.quote_id = None

    db.delete(link)
    db.delete(quote)
    group.updated_at = datetime.utcnow()
    try:
        record_quote_activity(
            db,
            actor=user,
            group=group,
            message_text=f"Opção/voo calculado #{quote_id} excluído sem apagar a cotação principal.",
            event="option_deleted",
        )
    except Exception:
        pass
    db.commit()
    flash(request, "Opção de voo/cálculo excluída. A cotação principal e as demais opções foram preservadas.", "success")
    return RedirectResponse("/calculations/history", status_code=303)


def _commercial_number(raw: Any) -> float:
    text_value = str(raw or "").strip().replace("R$", "").replace(" ", "")
    if not text_value:
        return 0.0
    if "," in text_value and "." in text_value:
        if text_value.rfind(",") > text_value.rfind("."):
            text_value = text_value.replace(".", "").replace(",", ".")
        else:
            text_value = text_value.replace(",", "")
    elif "," in text_value:
        text_value = text_value.replace(",", ".")
    try:
        return float(text_value)
    except (TypeError, ValueError):
        return 0.0


@router.post("/option/{quote_id}/profit")
async def save_option_profit(
    quote_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Salva custo, lucro, margem e condição de pagamento.

    Regras:
    - venda à vista = custo + lucro
    - lucro em R$ gera a margem %
    - margem % gera o lucro em R$
    - total cartão = venda à vista + juros
    - alterar total calcula juros
    - alterar juros calcula total
    - remover lucro equivale a zerar tudo
    """

    user = current_user(request, db)

    if user is None:
        return RedirectResponse("/login", status_code=303)

    form = await request.form()

    wants_json = (
        str(request.headers.get("x-requested-with") or "").lower()
        == "xmlhttprequest"
    )

    return_to = str(
        form.get("return_to") or "/calculations/history"
    ).strip()

    if not return_to.startswith("/") or return_to.startswith("//"):
        return_to = "/calculations/history"

    # ---------------------------------------------------------
    # CSRF
    # ---------------------------------------------------------

    if not validate_csrf_token(
        request.session,
        str(form.get("csrf_token") or ""),
    ):
        if wants_json:
            return JSONResponse(
                {
                    "ok": False,
                    "message": "Sessão expirada. Atualize a página e tente novamente.",
                },
                status_code=400,
            )

        flash(request, "Sessão expirada.", "error")

        return RedirectResponse(
            return_to,
            status_code=303,
        )

    try:

        # -----------------------------------------------------
        # COTAÇÃO
        # -----------------------------------------------------

        quote = db.scalar(
            select(WebQuote)
            .where(WebQuote.id == quote_id)
            .options(
                selectinload(WebQuote.commercial)
            )
        )

        if not _quote_allowed(user, quote):

            if wants_json:
                return JSONResponse(
                    {
                        "ok": False,
                        "message": "Cotação não encontrada.",
                    },
                    status_code=404,
                )

            flash(
                request,
                "Cotação não encontrada.",
                "error",
            )

            return RedirectResponse(
                "/calculations/history",
                status_code=303,
            )

        # -----------------------------------------------------
        # CUSTO
        # -----------------------------------------------------

        cost = round(
            max(
                0.0,
                float(quote.total or 0.0),
            ),
            2,
        )

        # -----------------------------------------------------
        # LUCRO
        # -----------------------------------------------------

        raw_profit_value = str(
            form.get("profit_value") or ""
        ).strip()

        raw_profit_percent = str(
            form.get("profit_percent") or ""
        ).strip()

        action = str(
            form.get("commercial_action") or "save"
        ).strip().lower()

        profit_value = max(
            0.0,
            _commercial_number(raw_profit_value),
        )

        profit_percent = max(
            0.0,
            _commercial_number(raw_profit_percent),
        )

        profit_source = str(
            form.get("profit_source") or "value"
        ).strip().lower()

        if profit_source == "percent":

            profit_value = (
                cost * profit_percent / 100
                if cost > 0
                else 0
            )

        else:

            profit_percent = (
                profit_value / cost * 100
                if cost > 0
                else 0
            )

        profit_value = round(
            profit_value,
            2,
        )

        profit_percent = round(
            profit_percent,
            4,
        )

        # REMOVER = exatamente o mesmo que lucro zero

        remove_commercial = (
            action == "remove"
            or (
                profit_value <= 0
                and profit_percent <= 0
            )
        )

        # -----------------------------------------------------
        # CARTÃO
        # -----------------------------------------------------

        try:
            installments = int(
                _commercial_number(
                    form.get("card_installments")
                )
                or 1
            )
        except Exception:
            installments = 1

        installments = max(
            1,
            min(
                24,
                installments,
            ),
        )

        card_mode = str(
            form.get("card_interest_mode")
            or "cash"
        ).strip().lower()

        if card_mode not in {
            "cash",
            "no_interest",
            "with_interest",
        }:
            card_mode = "cash"

        cash_sale = round(
            cost + profit_value,
            2,
        )

        entered_total = max(
            0.0,
            _commercial_number(
                form.get("card_total_value")
            ),
        )

        entered_difference = max(
            0.0,
            _commercial_number(
                form.get("card_difference_value")
            ),
        )

        card_value_source = str(
            form.get("card_value_source")
            or "total"
        ).strip().lower()

        # Inicializamos SEMPRE.
        # Isso evita variável inexistente ao remover lucro.

        card_total = cash_sale
        difference = 0.0

        # -----------------------------------------------------
        # RELAÇÃO:
        #
        # TOTAL CARTÃO = VENDA À VISTA + JUROS
        # -----------------------------------------------------

        if remove_commercial:

            installments = 1
            card_mode = "cash"
            card_total = cost
            difference = 0.0

        elif card_mode == "cash":

            installments = 1
            card_total = cash_sale
            difference = 0.0

        elif card_value_source == "difference":

            difference = round(
                entered_difference,
                2,
            )

            card_total = round(
                cash_sale + difference,
                2,
            )

            card_mode = (
                "with_interest"
                if difference > 0
                else "no_interest"
            )

        else:

            card_total = round(
                max(
                    cash_sale,
                    entered_total or cash_sale,
                ),
                2,
            )

            difference = round(
                max(
                    0,
                    card_total - cash_sale,
                ),
                2,
            )

            card_mode = (
                "with_interest"
                if difference > 0
                else "no_interest"
            )

        difference_percent = (
            difference / cash_sale * 100
            if cash_sale > 0
            else 0
        )

        difference_percent = round(
            difference_percent,
            4,
        )

        # -----------------------------------------------------
        # ENVIADA AO CLIENTE
        # -----------------------------------------------------

        sent_to_client = str(
            form.get("sent_to_client") or ""
        ).lower() in {
            "1",
            "true",
            "on",
            "yes",
        }

        apply_all = str(
            form.get("apply_all") or ""
        ).lower() in {
            "1",
            "true",
            "on",
            "yes",
        }

        # -----------------------------------------------------
        # OPÇÕES QUE RECEBERÃO A MARGEM
        # -----------------------------------------------------

        targets = [quote]

        link = db.get(
            QuoteOptionIndex,
            quote.id,
        )

        if apply_all and link is not None:

            links = list(
                db.scalars(
                    select(QuoteOptionIndex)
                    .where(
                        QuoteOptionIndex.group_id
                        == link.group_id
                    )
                    .order_by(
                        QuoteOptionIndex.position
                    )
                ).all()
            )

            quote_ids = [
                item.quote_id
                for item in links
            ]

            if user.company_id:

                access_filter = (
                    WebQuote.company_id
                    == user.company_id
                )

            else:

                access_filter = (
                    WebQuote.user_id
                    == user.id
                )

            targets = list(
                db.scalars(
                    select(WebQuote)
                    .where(
                        WebQuote.id.in_(
                            quote_ids
                        ),
                        access_filter,
                    )
                    .options(
                        selectinload(
                            WebQuote.commercial
                        )
                    )
                ).all()
            )

        response_items = []

        now = datetime.utcnow()

        # -----------------------------------------------------
        # SALVAR
        # -----------------------------------------------------

        for target in targets:

            target_cost = round(
                max(
                    0.0,
                    float(
                        target.total or 0.0
                    ),
                ),
                2,
            )

            # SEMPRE inicializados

            target_profit = 0.0
            target_sale = target_cost
            target_difference = 0.0
            target_card_total = target_cost

            commercial = (
                target.commercial
                or QuoteCommercial(
                    quote_id=target.id
                )
            )

            if target.commercial is None:
                db.add(commercial)

            # -------------------------------------------------
            # REMOVER
            # -------------------------------------------------

            if remove_commercial:

                commercial.cost_basis = None
                commercial.profit_value = None
                commercial.profit_percent = None
                commercial.sale_value = None

                commercial.sent_to_client_at = None

                commercial.card_installments = 1
                commercial.card_interest_mode = "cash"

                commercial.card_total_value = None
                commercial.card_installment_value = None
                commercial.card_difference_value = None

            # -------------------------------------------------
            # SALVAR
            # -------------------------------------------------

            else:

                if apply_all:

                    target_profit = round(
                        target_cost
                        * profit_percent
                        / 100,
                        2,
                    )

                else:

                    target_profit = (
                        profit_value
                    )

                target_sale = round(
                    target_cost
                    + target_profit,
                    2,
                )

                # juros proporcionais no "aplicar todos"

                if apply_all:

                    target_difference = round(
                        target_sale
                        * difference_percent
                        / 100,
                        2,
                    )

                    target_card_total = round(
                        target_sale
                        + target_difference,
                        2,
                    )

                else:

                    target_difference = round(
                        difference,
                        2,
                    )

                    target_card_total = round(
                        target_sale
                        + target_difference,
                        2,
                    )

                commercial.cost_basis = (
                    target_cost
                )

                commercial.profit_value = (
                    target_profit
                )

                commercial.profit_percent = (
                    profit_percent
                )

                commercial.sale_value = (
                    target_sale
                )

                commercial.sent_to_client_at = (
                    now
                    if sent_to_client
                    else None
                )

                commercial.card_installments = (
                    installments
                )

                commercial.card_interest_mode = (
                    "with_interest"
                    if target_difference > 0
                    else (
                        "no_interest"
                        if installments > 1
                        else "cash"
                    )
                )

                commercial.card_total_value = (
                    target_card_total
                )

                commercial.card_installment_value = round(
                    target_card_total
                    / max(
                        1,
                        installments,
                    ),
                    2,
                )

                commercial.card_difference_value = (
                    target_difference
                )

            # -------------------------------------------------
            # COTAÇÃO ACEITA
            # -------------------------------------------------

            accepted = db.scalar(
                select(AcceptedQuote)
                .where(
                    AcceptedQuote.quote_id
                    == target.id
                )
            )

            if accepted is not None:

                accepted.sale_value = (
                    target_sale
                )

                try:

                    accepted_data = json.loads(
                        accepted.extra_json
                        or "{}"
                    )

                    if not isinstance(
                        accepted_data,
                        dict,
                    ):
                        accepted_data = {}

                except Exception:

                    accepted_data = {}

                if remove_commercial:

                    accepted_data.pop(
                        "commercial_offer",
                        None,
                    )

                else:

                    accepted_data[
                        "commercial_offer"
                    ] = {
                        "cost_value":
                            target_cost,

                        "cash_sale_value":
                            target_sale,

                        "profit_value":
                            target_profit,

                        "profit_percent":
                            profit_percent,

                        "card_installments":
                            installments,

                        "card_interest_mode":
                            commercial.card_interest_mode,

                        "card_total_value":
                            target_card_total,

                        "card_installment_value":
                            round(
                                target_card_total
                                / max(
                                    1,
                                    installments,
                                ),
                                2,
                            ),

                        "card_difference_value":
                            target_difference,

                        "sent_to_client":
                            sent_to_client,
                    }

                accepted.extra_json = (
                    json.dumps(
                        accepted_data,
                        ensure_ascii=False,
                    )
                )

            # -------------------------------------------------
            # RESPOSTA PARA ATUALIZAR O HISTÓRICO
            # -------------------------------------------------

            response_items.append(
                {
                    "quote_id":
                        target.id,

                    "cost":
                        target_cost,

                    "removed":
                        remove_commercial,

                    "profit_value":
                        0
                        if remove_commercial
                        else target_profit,

                    "profit_percent":
                        0
                        if remove_commercial
                        else profit_percent,

                    "sale_value":
                        target_sale,

                    "sent_to_client":
                        False
                        if remove_commercial
                        else sent_to_client,

                    "card_installments":
                        1
                        if remove_commercial
                        else installments,

                    "card_interest_mode":
                        "cash"
                        if remove_commercial
                        else commercial.card_interest_mode,

                    "card_total_value":
                        target_card_total,

                    "card_installment_value":
                        round(
                            target_card_total
                            / (
                                1
                                if remove_commercial
                                else max(
                                    1,
                                    installments,
                                )
                            ),
                            2,
                        ),

                    "card_difference_value":
                        0
                        if remove_commercial
                        else target_difference,

                    "card_difference_percent":
                        (
                            0
                            if remove_commercial
                            or target_sale <= 0
                            else round(
                                target_difference
                                / target_sale
                                * 100,
                                4,
                            )
                        ),
                }
            )

        # -----------------------------------------------------
        # COMMIT
        # -----------------------------------------------------

        db.commit()

        # -----------------------------------------------------
        # RESPOSTA
        # -----------------------------------------------------

        if remove_commercial:

            message = (
                "Lucro removido. "
                "A opção voltou ao custo calculado."
            )

        else:

            message = (
                "Condição comercial salva com sucesso."
            )

        if wants_json:

            return JSONResponse(
                {
                    "ok": True,
                    "message": message,
                    "removed": remove_commercial,
                    "items": response_items,
                }
            )

        flash(
            request,
            message,
            "success",
        )

        return RedirectResponse(
            return_to,
            status_code=303,
        )

    # ---------------------------------------------------------
    # ERRO CONTROLADO
    # ---------------------------------------------------------

    except Exception as exc:

        db.rollback()

        logger.exception(
            "Erro ao salvar condição comercial "
            "da cotação %s",
            quote_id,
        )

        message = (
            "Erro ao salvar condição comercial: "
            + str(exc)
        )

        if wants_json:

            return JSONResponse(
                {
                    "ok": False,
                    "message": message,
                },
                status_code=500,
            )

        flash(
            request,
            message,
            "error",
        )

        return RedirectResponse(
            return_to,
            status_code=303,
        )
        

@router.post("/option/{quote_id}/duplicate")
async def duplicate_option(quote_id: int, request: Request, db: Session = Depends(get_db)):
    """Duplica um voo/cálculo dentro da mesma cotação e subcotação."""
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/calculations/history", status_code=303)
    source = db.scalar(
        select(WebQuote)
        .where(WebQuote.id == quote_id)
        .options(selectinload(WebQuote.trip), selectinload(WebQuote.commercial))
    )
    link = db.get(QuoteOptionIndex, quote_id)
    if not _quote_allowed(user, source) or link is None:
        flash(request, "Opção calculada não encontrada.", "error")
        return RedirectResponse("/calculations/history", status_code=303)
    group = db.get(QuoteGroup, link.group_id)
    if not _group_allowed(user, group):
        flash(request, "Cotação principal não encontrada.", "error")
        return RedirectResponse("/calculations/history", status_code=303)
    clone = WebQuote(
        user_id=user.id,
        company_id=user.company_id,
        airline_id=source.airline_id,
        calculation_type_id=source.calculation_type_id,
        quote_name=source.quote_name,
        origin=source.origin,
        destination=source.destination,
        passengers=source.passengers,
        babies=source.babies,
        bags=source.bags,
        currency=source.currency,
        input_json=source.input_json,
        breakdown_json=source.breakdown_json,
        total=source.total,
    )
    db.add(clone)
    db.flush()
    if source.trip:
        db.add(QuoteTripDetail(
            quote_id=clone.id,
            travel_type=source.trip.travel_type,
            departure_date=source.trip.departure_date,
            return_date=source.trip.return_date,
            segments_json=source.trip.segments_json,
            client_person_id=source.trip.client_person_id,
            client_name=source.trip.client_name,
            client_email=source.trip.client_email,
            client_phone=source.trip.client_phone,
            notes=source.trip.notes,
        ))
    if source.commercial:
        db.add(QuoteCommercial(
            quote_id=clone.id, sale_value=source.commercial.sale_value,
            cost_basis=source.commercial.cost_basis, profit_value=source.commercial.profit_value,
            profit_percent=source.commercial.profit_percent, sent_to_client_at=source.commercial.sent_to_client_at,
            card_installments=source.commercial.card_installments or 1,
            card_interest_mode=source.commercial.card_interest_mode or "cash",
            card_total_value=source.commercial.card_total_value,
            card_installment_value=source.commercial.card_installment_value,
            card_difference_value=source.commercial.card_difference_value,
            observations=source.commercial.observations,
        ))
    positions = db.scalars(select(QuoteOptionIndex).where(QuoteOptionIndex.group_id == group.id)).all()
    max_position = max((item.position for item in positions), default=0)
    db.add(QuoteOptionIndex(quote_id=clone.id, group_id=group.id, position=max_position + 1))
    group.updated_at = datetime.utcnow()
    db.commit()
    flash(request, "Voo/cálculo duplicado dentro da mesma cotação. Abra a cópia para alterar tarifa, datas, horários ou valores.", "success")
    return RedirectResponse(f"/calculations/new?group_id={group.id}&edit_id={clone.id}&calc=1", status_code=303)



@router.post("/group/{group_id}/combine")
async def combine_group_options(group_id: int, request: Request, db: Session = Depends(get_db)):
    """Junta opções compatíveis da MESMA cotação e soma os valores.

    Permitido:
    - 1 opção Só ida + 1 opção Só volta;
    - 2 ou mais opções Só ida;
    - 2 ou mais opções Só volta;
    - 2 ou mais Trechos diferentes (Trecho 1 + Trecho 2 + ...).

    Nunca mistura grupos/cotações diferentes e nunca mistura subcotações
    diferentes dentro do mesmo grupo.
    """
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)

    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada. Atualize a página e tente novamente.", "error")
        return RedirectResponse("/calculations/history", status_code=303)

    group = db.scalar(
        select(QuoteGroup)
        .where(QuoteGroup.id == group_id)
        .options(selectinload(QuoteGroup.trip))
    )
    if not _group_allowed(user, group):
        flash(request, "Cotação principal não encontrada.", "error")
        return RedirectResponse("/calculations/history", status_code=303)

    raw_ids = form.getlist("quote_ids")
    quote_ids: list[int] = []
    for raw in raw_ids:
        try:
            quote_id = int(raw)
        except (TypeError, ValueError):
            continue
        if quote_id not in quote_ids:
            quote_ids.append(quote_id)

    if len(quote_ids) < 2:
        flash(request, "Selecione pelo menos duas opções para juntar.", "error")
        return RedirectResponse("/calculations/history", status_code=303)
    if len(quote_ids) > 12:
        flash(request, "Você pode juntar no máximo 12 trechos por vez.", "error")
        return RedirectResponse("/calculations/history", status_code=303)

    # Segurança principal: todos os IDs precisam estar vinculados ao MESMO grupo.
    links = list(
        db.scalars(
            select(QuoteOptionIndex)
            .where(
                QuoteOptionIndex.group_id == group_id,
                QuoteOptionIndex.quote_id.in_(quote_ids),
            )
        ).all()
    )
    linked_ids = {int(link.quote_id) for link in links}
    if linked_ids != set(quote_ids):
        flash(request, "Só é possível juntar opções da mesma cotação criada.", "error")
        return RedirectResponse("/calculations/history", status_code=303)

    access_filter = WebQuote.company_id == user.company_id if user.company_id else WebQuote.user_id == user.id
    source_quotes = list(
        db.scalars(
            select(WebQuote)
            .where(WebQuote.id.in_(quote_ids), access_filter)
            .options(
                selectinload(WebQuote.airline),
                selectinload(WebQuote.calculation_type),
                selectinload(WebQuote.trip),
                selectinload(WebQuote.commercial),
                selectinload(WebQuote.user),
            )
        ).all()
    )
    by_id = {int(item.id): item for item in source_quotes}
    if set(by_id) != set(quote_ids):
        flash(request, "Uma das opções selecionadas não está mais disponível.", "error")
        return RedirectResponse("/calculations/history", status_code=303)

    source_quotes = [_decorate_quote_scope(by_id[item_id], group) for item_id in quote_ids]

    if any(getattr(item, "is_combined", False) for item in source_quotes):
        flash(request, "Uma opção já combinada não pode ser combinada novamente.", "error")
        return RedirectResponse("/calculations/history", status_code=303)

    variant_keys = {str(getattr(item, "variant_key", "primary") or "primary") for item in source_quotes}
    if len(variant_keys) != 1:
        flash(request, "As opções precisam pertencer à mesma cotação/subcotação.", "error")
        return RedirectResponse("/calculations/history", status_code=303)
    variant_key = next(iter(variant_keys))

    scope_keys = [str(getattr(item, "combine_scope_key", "") or "") for item in source_quotes]
    if any(not key for key in scope_keys):
        flash(request, "Só é possível juntar Só ida + Só volta ou Trechos diferentes.", "error")
        return RedirectResponse("/calculations/history", status_code=303)

    is_round_pair = len(scope_keys) == 2 and set(scope_keys) == {"outbound", "return"}
    is_outbound_set = len(scope_keys) >= 2 and all(key == "outbound" for key in scope_keys)
    is_return_set = len(scope_keys) >= 2 and all(key == "return" for key in scope_keys)
    is_segment_set = (
        len(scope_keys) >= 2
        and all(re.fullmatch(r"segment_\d+", key) for key in scope_keys)
        and len(set(scope_keys)) == len(scope_keys)
    )
    if not (is_round_pair or is_outbound_set or is_return_set or is_segment_set):
        flash(
            request,
            "Combinação inválida. Use ida + volta, duas ou mais idas, duas ou mais voltas, ou Trechos diferentes da mesma cotação.",
            "error",
        )
        return RedirectResponse("/calculations/history", status_code=303)

    # Mesma quantidade de passageiros para evitar combinação operacional incoerente.
    pax_signatures = {(int(item.passengers or 0), int(item.babies or 0)) for item in source_quotes}
    if len(pax_signatures) != 1:
        flash(request, "As opções selecionadas possuem quantidades de passageiros diferentes.", "error")
        return RedirectResponse("/calculations/history", status_code=303)

    def segment_number(key: str) -> int:
        match = re.fullmatch(r"segment_(\d+)", key)
        return int(match.group(1)) if match else 999

    if is_round_pair:
        order_map = {"outbound": 0, "return": 1}
        source_quotes.sort(key=lambda item: order_map.get(str(item.combine_scope_key), 99))
    elif is_outbound_set or is_return_set:
        # Em duas/múltiplas idas ou voltas, preserva a ordem visual em que os
        # cards aparecem e foram enviados pelo formulário.
        submitted_position = {quote_id: index for index, quote_id in enumerate(quote_ids)}
        source_quotes.sort(key=lambda item: submitted_position.get(int(item.id), 999))
    else:
        source_quotes.sort(key=lambda item: segment_number(str(item.combine_scope_key)))

    # Evita criar exatamente a mesma combinação repetidas vezes.
    wanted_signature = sorted(int(item.id) for item in source_quotes)
    all_group_quotes = _load_options(db, user, group_id)
    for existing in all_group_quotes:
        existing_data = _quote_input_data(existing)
        combined = existing_data.get("_combined") if isinstance(existing_data.get("_combined"), dict) else {}
        existing_ids = []
        for raw in combined.get("component_ids") or []:
            try:
                existing_ids.append(int(raw))
            except (TypeError, ValueError):
                pass
        if sorted(existing_ids) == wanted_signature:
            flash(request, "Essa combinação já existe no Histórico.", "warning")
            return RedirectResponse("/calculations/history", status_code=303)

    total_cost = round(sum(float(item.total or 0) for item in source_quotes), 2)
    component_sales: list[float] = []
    component_profits: list[float] = []
    for item in source_quotes:
        commercial = item.commercial
        sale = float(commercial.sale_value) if commercial and commercial.sale_value is not None else float(item.total or 0)
        component_sales.append(sale)
        component_profits.append(max(0.0, sale - float(item.total or 0)))
    total_sale = round(sum(component_sales), 2)
    total_profit = round(sum(component_profits), 2)

    merged_segments: list[dict[str, Any]] = []
    merged_details: list[dict[str, Any]] = []
    components: list[dict[str, Any]] = []
    airline_names: list[str] = []
    operation_scopes: list[str] = []

    for component_index, item in enumerate(source_quotes, start=1):
        data = _quote_input_data(item)
        scope = item.scope_data if isinstance(getattr(item, "scope_data", None), dict) else {}
        segments = scope.get("segments") if isinstance(scope.get("segments"), list) else []
        if not segments and item.trip:
            parsed_segments = _safe_json(item.trip.segments_json, [])
            segments = parsed_segments if isinstance(parsed_segments, list) else []

        same_direction_bundle = is_outbound_set or is_return_set
        bundle_segment_key = f"segment_{component_index}" if same_direction_bundle else ""

        for segment in segments:
            if isinstance(segment, dict):
                copied_segment = dict(segment)
                if same_direction_bundle:
                    copied_segment["key"] = bundle_segment_key
                    copied_segment["label"] = (
                        f"Ida {component_index}" if is_outbound_set
                        else f"Volta {component_index}"
                    )
                merged_segments.append(copied_segment)

        details = data.get("_flight_details") if isinstance(data.get("_flight_details"), list) else []
        airline_name = (
            item.airline.name if item.airline
            else str(getattr(item, "partner_airline", "") or "")
            or "Companhia"
        )
        if airline_name not in airline_names:
            airline_names.append(airline_name)

        if details:
            for detail in details:
                if not isinstance(detail, dict):
                    continue
                copied = dict(detail)
                copied["airline"] = str(copied.get("airline") or airline_name)
                if same_direction_bundle:
                    copied["segment_key"] = bundle_segment_key
                    copied["kind"] = "ida" if is_outbound_set else "volta"
                    copied["label"] = (
                        f"Ida {component_index}" if is_outbound_set
                        else f"Volta {component_index}"
                    )
                merged_details.append(copied)
        else:
            for index, segment in enumerate(segments, start=1):
                if not isinstance(segment, dict):
                    continue
                key = (
                    bundle_segment_key
                    if same_direction_bundle
                    else str(segment.get("key") or item.combine_scope_key or f"segment_{index}")
                )
                kind = (
                    "ida" if is_outbound_set
                    else ("volta" if is_return_set
                          else ("volta" if key == "return"
                                else ("ida" if key == "outbound" else "trecho")))
                )
                label = (
                    f"Ida {component_index}" if is_outbound_set
                    else (f"Volta {component_index}" if is_return_set
                          else ("Voo de Volta" if kind == "volta"
                                else ("Voo de Ida" if kind == "ida" else f"Trecho {index}")))
                )
                merged_details.append({
                    "segment_key": key,
                    "kind": kind,
                    "label": label,
                    "origin": str(segment.get("origin") or ""),
                    "destination": str(segment.get("destination") or ""),
                    "departure_date": str(segment.get("date") or ""),
                    "departure_time": "",
                    "arrival_date": "",
                    "arrival_time": "",
                    "airline": airline_name,
                })

        operation_scope = str(getattr(item, "operation_scope", "") or "")
        if operation_scope and operation_scope not in operation_scopes:
            operation_scopes.append(operation_scope)

        components.append({
            "quote_id": int(item.id),
            "scope_key": str(item.combine_scope_key),
            "scope_label": str(getattr(item, "scope_label", "") or ""),
            "airline": airline_name,
            "logo_path": str(getattr(getattr(item, "airline", None), "logo_path", "") or ""),
            "cost": round(float(item.total or 0), 2),
            "sale": round(
                float(item.commercial.sale_value)
                if item.commercial and item.commercial.sale_value is not None
                else float(item.total or 0),
                2,
            ),
        })

    if is_round_pair:
        combined_scope_key = "round_trip"
        combined_scope_label = "Ida + Volta combinadas"
        travel_type = "round_trip"
        ordered_scope_names = ["Só ida", "Só volta"]
    elif is_outbound_set:
        combined_scope_key = "multi_city"
        combined_scope_label = f"{len(source_quotes)} idas combinadas"
        travel_type = "multi_city"
        ordered_scope_names = [f"Só ida {index}" for index in range(1, len(source_quotes) + 1)]
    elif is_return_set:
        combined_scope_key = "multi_city"
        combined_scope_label = f"{len(source_quotes)} voltas combinadas"
        travel_type = "multi_city"
        ordered_scope_names = [f"Só volta {index}" for index in range(1, len(source_quotes) + 1)]
    else:
        combined_scope_key = "multi_city"
        segment_labels = [f"Trecho {segment_number(str(item.combine_scope_key))}" for item in source_quotes]
        combined_scope_label = " + ".join(segment_labels) + " combinados"
        travel_type = "multi_city"
        ordered_scope_names = segment_labels

    first_scope = source_quotes[0].scope_data if isinstance(source_quotes[0].scope_data, dict) else {}
    last_scope = source_quotes[-1].scope_data if isinstance(source_quotes[-1].scope_data, dict) else {}
    departure_date = str(
        first_scope.get("departure_date")
        or (merged_segments[0].get("date") if merged_segments else "")
        or ""
    )
    return_date = str(
        last_scope.get("return_date")
        or last_scope.get("departure_date")
        or (merged_segments[-1].get("date") if len(merged_segments) > 1 else "")
        or ""
    )

    first_input = _quote_input_data(source_quotes[0])
    variant_data = first_input.get("_variant") if isinstance(first_input.get("_variant"), dict) else {
        "key": variant_key,
        "name": "Cotação principal" if variant_key == "primary" else "Subcotação",
    }

    display_name = " + ".join(airline_names) if airline_names else "Opção combinada"
    if len(display_name) > 220:
        display_name = f"{len(airline_names)} companhias combinadas"

    values: dict[str, Any] = {
        "_variant": dict(variant_data),
        "_scope": {
            "key": combined_scope_key,
            "label": combined_scope_label,
            "segments": merged_segments,
            "departure_date": departure_date,
            "return_date": return_date if travel_type == "round_trip" else "",
        },
        "_flight_details": merged_details,
        "_combined": {
            "component_ids": [int(item.id) for item in source_quotes],
            "components": components,
            "airlines": airline_names,
            "display_name": display_name,
            "scope_names": ordered_scope_names,
            "created_at": datetime.utcnow().isoformat(timespec="seconds"),
        },
        "_meta": {
            "fare_brand": "Combinada",
            "cabin_class": "",
            "description": f"Combinação: {' + '.join(ordered_scope_names)}",
            "extra_name": "",
            "extra_value": "",
        },
        "_partnership": {
            "operation_scope": operation_scopes[0] if len(operation_scopes) == 1 else "",
            "partner_airline": "",
            "segment_partners": [],
        },
    }

    same_airline_ids = {item.airline_id for item in source_quotes}
    same_type_ids = {item.calculation_type_id for item in source_quotes}

    combined_quote = WebQuote(
        user_id=user.id,
        company_id=user.company_id,
        airline_id=next(iter(same_airline_ids)) if len(same_airline_ids) == 1 else None,
        calculation_type_id=next(iter(same_type_ids)) if len(same_type_ids) == 1 else None,
        quote_name=group.quote_name,
        origin=str((merged_segments[0].get("origin") if merged_segments else group.origin) or ""),
        destination=str((merged_segments[-1].get("destination") if merged_segments else group.destination) or ""),
        passengers=int(source_quotes[0].passengers or group.passengers or 1),
        babies=int(source_quotes[0].babies or group.babies or 0),
        bags=max(int(item.bags or 0) for item in source_quotes),
        currency="BRL",
        input_json=json.dumps(values, ensure_ascii=False),
        breakdown_json=json.dumps({
            "modo": "opcoes_combinadas",
            "componentes": components,
            "custo_total": total_cost,
            "venda_total": total_sale,
        }, ensure_ascii=False),
        total=total_cost,
    )
    db.add(combined_quote)
    db.flush()

    base_trip = group.trip
    combined_trip = QuoteTripDetail(
        quote_id=combined_quote.id,
        travel_type=travel_type,
        departure_date=departure_date or None,
        return_date=(return_date or None) if travel_type == "round_trip" else None,
        segments_json=json.dumps(merged_segments, ensure_ascii=False),
        client_person_id=base_trip.client_person_id if base_trip else None,
        client_name=base_trip.client_name if base_trip else None,
        client_email=base_trip.client_email if base_trip else None,
        client_phone=base_trip.client_phone if base_trip else None,
        notes=base_trip.notes if base_trip else None,
    )
    db.add(combined_trip)

    # Preserva o lucro já informado nas partes. Se não havia lucro, a opção
    # combinada nasce apenas com o custo e pode receber lucro depois normalmente.
    any_commercial = any(item.commercial is not None for item in source_quotes)
    if any_commercial and (total_profit > 0 or total_sale != total_cost):
        profit_percent = round((total_profit / total_cost * 100.0) if total_cost > 0 else 0.0, 4)

        source_modes = {
            str(item.commercial.card_interest_mode or "cash")
            for item in source_quotes if item.commercial
        }
        source_installments = {
            int(item.commercial.card_installments or 1)
            for item in source_quotes if item.commercial
        }
        all_have_commercial = all(item.commercial is not None for item in source_quotes)

        if all_have_commercial and len(source_modes) == 1 and len(source_installments) == 1:
            card_mode = next(iter(source_modes))
            installments = max(1, next(iter(source_installments)))
            card_total = round(sum(
                float(item.commercial.card_total_value or item.commercial.sale_value or item.total or 0)
                for item in source_quotes
            ), 2)
            card_difference = round(max(0.0, card_total - total_sale), 2)
        else:
            card_mode = "cash"
            installments = 1
            card_total = total_sale
            card_difference = 0.0

        db.add(QuoteCommercial(
            quote_id=combined_quote.id,
            cost_basis=total_cost,
            profit_value=total_profit,
            profit_percent=profit_percent,
            sale_value=total_sale,
            sent_to_client_at=None,
            card_installments=installments,
            card_interest_mode=card_mode,
            card_total_value=card_total,
            card_installment_value=round(card_total / installments, 2),
            card_difference_value=card_difference,
        ))

    existing_links = list(
        db.scalars(
            select(QuoteOptionIndex)
            .where(QuoteOptionIndex.group_id == group_id)
        ).all()
    )
    max_position = max((int(item.position or 0) for item in existing_links), default=0)
    db.add(QuoteOptionIndex(
        quote_id=combined_quote.id,
        group_id=group_id,
        position=max_position + 1,
    ))

    group.updated_at = datetime.utcnow()
    _message, payload = record_quote_activity(
        db,
        user,
        group,
        f"Opções combinadas na cotação {group.quote_name}: {' + '.join(ordered_scope_names)} = R$ {total_cost:.2f}.",
        event="quote_options_combined",
        send_to_chat=False,
        record_audit=False,
    )
    db.commit()
    await publish_quote_activity(user.company_id, payload)

    flash(
        request,
        f"Opções juntadas com sucesso. Novo custo combinado: R$ {total_cost:,.2f}.",
        "success",
    )
    return RedirectResponse("/calculations/history", status_code=303)


@router.post("/group/{group_id}/duplicate")
async def duplicate_group(group_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/calculations/history", status_code=303)
    group = db.scalar(select(QuoteGroup).where(QuoteGroup.id == group_id).options(selectinload(QuoteGroup.trip), selectinload(QuoteGroup.user).selectinload(WebUser.profile), selectinload(QuoteGroup.assigned_user).selectinload(WebUser.profile)))
    if not _group_allowed(user, group):
        flash(request, "Cotação principal não encontrada.", "error")
        return RedirectResponse("/calculations/history", status_code=303)

    new_group = QuoteGroup(
        user_id=user.id,
        company_id=user.company_id,
        quote_name=f"Cópia de {group.quote_name}",
        origin=group.origin,
        destination=group.destination,
        passengers=group.passengers,
        babies=group.babies,
        bags=0,
        source_request_id=group.source_request_id,
        assigned_user_id=user.id,
    )
    db.add(new_group)
    db.flush()
    if group.trip:
        db.add(
            QuoteGroupTripDetail(
                group_id=new_group.id,
                travel_type=group.trip.travel_type,
                departure_date=group.trip.departure_date,
                return_date=group.trip.return_date,
                segments_json=group.trip.segments_json,
                variants_json=getattr(group.trip, "variants_json", "[]") or "[]",
                client_person_id=group.trip.client_person_id,
                client_name=group.trip.client_name,
                client_email=group.trip.client_email,
                client_phone=group.trip.client_phone,
                notes=group.trip.notes,
            )
        )
    db.commit()
    request.session["active_quote_group_id"] = new_group.id
    request.session["force_calc_group_id"] = new_group.id

    # V5.5.10: duplicar deve levar direto para a tela de cálculo antiga,
    # com a base da cotação já copiada e fixa. O usuário só escolhe a
    # companhia e preenche milhas/milheiro/taxa, sem precisar salvar a base
    # novamente. Para alterar os dados da base, ele clica em "Alterar dados".
    _airlines, first_airline, _first_type = _selected_airline_and_type(db, user, None, None)
    redirect_url = f"/calculations/new?group_id={new_group.id}&calc=1&mode=calc"
    if first_airline is not None:
        redirect_url += f"&airline_id={first_airline.id}"

    flash(request, "Cotação principal duplicada. A base já está salva; escolha uma companhia e calcule novas opções sem alterar a original.", "success")
    return RedirectResponse(redirect_url, status_code=303)


@router.post("/bulk-delete")
async def bulk_delete_quotes(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/calculations/history", status_code=303)

    group_ids: list[int] = []
    for raw in form.getlist("group_ids"):
        try:
            group_ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    group_ids = list(dict.fromkeys(group_ids))[:500]

    quote_ids: list[int] = []
    for raw in form.getlist("quote_ids"):
        try:
            quote_ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    quote_ids = list(dict.fromkeys(quote_ids))[:500]

    deleted_groups = 0
    deleted_quotes = 0
    access_group = QuoteGroup.company_id == user.company_id if user.company_id else QuoteGroup.user_id == user.id
    access_quote = WebQuote.company_id == user.company_id if user.company_id else WebQuote.user_id == user.id

    if group_ids:
        groups = db.scalars(select(QuoteGroup).where(QuoteGroup.id.in_(group_ids), access_group)).all()
        for group in groups:
            options = _load_options(db, user, group.id)
            for quote in options:
                db.delete(quote)
                deleted_quotes += 1
            db.delete(group)
            deleted_groups += 1
    if quote_ids:
        quotes = db.scalars(select(WebQuote).where(WebQuote.id.in_(quote_ids), access_quote)).all()
        for quote in quotes:
            db.delete(quote)
            deleted_quotes += 1
    db.commit()
    if deleted_groups or deleted_quotes:
        flash(request, f"{deleted_groups} cotação(ões) principal(is) e {deleted_quotes} opção(ões) excluída(s).", "success")
    else:
        flash(request, "Selecione ao menos uma cotação.", "error")
    return RedirectResponse("/calculations/history", status_code=303)


@router.post("/group/{group_id}/delete")
async def delete_group(group_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/calculations/history", status_code=303)
    group = db.get(QuoteGroup, group_id)
    if _group_allowed(user, group):
        for quote in _load_options(db, user, group.id):
            db.delete(quote)
        db.delete(group)
        db.commit()
        flash(request, "Cotação principal excluída.", "success")
    return RedirectResponse("/calculations/history", status_code=303)


@router.post("/{quote_id}/delete")
async def delete_quote(quote_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/calculations/history", status_code=303)
    quote = db.get(WebQuote, quote_id)
    link = db.get(QuoteOptionIndex, quote_id)
    redirect = f"/calculations/group/{link.group_id}" if link else "/calculations/history"
    if _quote_allowed(user, quote):
        db.delete(quote)
        db.commit()
        flash(request, "Opção excluída.", "success")
    return RedirectResponse(redirect, status_code=303)
