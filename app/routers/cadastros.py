from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, selectinload

from ..config import UPLOAD_DIR
from ..database import get_db
from ..dependencies import require_user
from ..models import (
    AcceptedQuote,
    FlightRegistry,
    Person,
    QuoteGroup,
    QuoteGroupTripDetail,
    QuoteOptionIndex,
    QuoteBoardStatus,
    WebQuote,
    WebUser,
)
from ..security import validate_csrf_token
from ..services.travel_data import AIRLINE_OPTIONS, BR_AIRPORTS, checkin_link_for_airline
from ..services.quote_activity import record_quote_activity, publish_quote_activity
from ..services.uploads import delete_relative_upload, save_quote_attachment, save_upload_image
from ..services.pdf_service import _html_to_pdf, file_to_data_uri
from ..web import context, flash, templates

router = APIRouter(prefix="/cadastros", tags=["cadastros"])

BOARD_STATUSES = [
    ("aguardando", "Aguardando", "#8d8d8d"),
    ("em_cotacao", "Em cotação", "#ff7a3d"),
    ("aguardando_cliente", "Aguardando cliente", "#2fa1c9"),
    ("ap_pgmt_cartao", "AP - PGMT cartão", "#9be7b6"),
    ("venda_cadastrada", "Venda cadastrada", "#eff200"),
    ("aprovado", "Aprovado", "#08b86f"),
    ("lancada", "Lançada", "#2f7cf6"),
    ("reprovado", "Reprovado", "#f24848"),
]
DEFAULT_BOARD_STATUSES = list(BOARD_STATUSES)
STATUS_KEYS = {key for key, _label, _color in DEFAULT_BOARD_STATUSES}
SALE_UNLOCK_STATUS = "venda_cadastrada"


def _slugify_status(label: str) -> str:
    raw = unicodedata.normalize("NFD", str(label or "").strip().lower())
    raw = "".join(ch for ch in raw if unicodedata.category(ch) != "Mn")
    raw = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
    return raw or "area"


def _status_scope_filter(user):
    return QuoteBoardStatus.company_id == user.company_id if user.company_id else QuoteBoardStatus.user_id == user.id


def _board_statuses(db: Session, user) -> list[tuple[str, str, str]]:
    """Fases padrão + áreas personalizadas da empresa/usuário."""
    statuses = list(DEFAULT_BOARD_STATUSES)
    seen = {key for key, _label, _color in statuses}
    try:
        custom = db.scalars(
            select(QuoteBoardStatus)
            .where(_status_scope_filter(user), QuoteBoardStatus.active.is_(True))
            .order_by(QuoteBoardStatus.position, QuoteBoardStatus.label)
        ).all()
    except Exception:
        custom = []
    for row in custom:
        key = str(row.key or "").strip()
        if not key or key in seen:
            continue
        statuses.append((key, row.label or key.replace("_", " ").title(), row.color or "#8d8d8d"))
        seen.add(key)
    return statuses


def _status_keys(db: Session, user) -> set[str]:
    return {key for key, _label, _color in _board_statuses(db, user)}

PAYMENT_METHODS = [
    "", "[Boleto]", "[Cartão de Crédito]", "[Cartão de Débito]", "[Cheque]", "[Dinheiro]", "[Pix]",
    "[Transferência]", "Cartão Amex", "Cartão Banco Inter", "Cartão C6", "Cartão LatamPass",
    "Cartão Nubank", "Cartão Sicred", "Cartão XP", "Mercado Pago",
]
ACCOUNTS = ["", "Mercado Pago", "Pix", "Dinheiro", "Cartão Nubank", "Cartão C6", "Cartão XP", "Banco Inter", "Outro"]
COST_CATEGORIES = ["", "Pagamento Fornecedor", "Taxa", "Bagagem", "Milhas", "Hotel", "Transporte", "Seguro", "Serviço adicional", "Outro"]
SALE_CATEGORIES = ["", "Venda de Passagem", "Venda de Hospedagem", "Venda de Pacote", "Taxa de Serviço", "Comissão", "Outro"]
CHANNELS = ["", "WhatsApp", "Instagram", "Telefone", "E-mail", "Indicação", "Presencial", "Site", "Outro"]
CHECKIN_STATUSES = ["pendente", "em_periodo", "realizado", "nao_notificar"]


def _airline_key(value: str | None) -> str:
    """Normaliza nomes/aliases de companhia para o catálogo de logomarcas."""
    raw = unicodedata.normalize("NFD", str(value or "").strip().lower())
    raw = "".join(ch for ch in raw if unicodedata.category(ch) != "Mn")
    raw = re.sub(r"[^a-z0-9]+", " ", raw).strip()
    return raw


def _airline_logo_map(db: Session, user) -> dict[str, str]:
    """Mapa seguro de logos oficiais, sem consultar o banco.

    Mantemos a assinatura por compatibilidade com as rotas existentes. Isso
    evita que uma tabela/coluna de companhias desatualizada derrube a tela.
    """
    builtins = {
        "gol": "app/imagens/gol2.png",
        "gol linhas aereas": "app/imagens/gol2.png",
        "smiles": "app/imagens/gol2.png",
        "azul": "app/imagens/azul.png",
        "azul linhas aereas": "app/imagens/azul.png",
        "azul pelo mundo": "app/imagens/azulpelomundo.png",
        "latam": "app/imagens/latam.png",
        "latam airlines": "app/imagens/latam.png",
        "american": "app/imagens/american.png",
        "american airlines": "app/imagens/american.png",
        "aadvantage": "app/imagens/american.png",
    }
    catalog: dict[str, str] = {}
    for alias, path in builtins.items():
        try:
            logo = file_to_data_uri(path)
        except Exception:
            logo = None
        if logo:
            catalog[alias] = logo
    return catalog


def _person_filter(user):
    return Person.company_id == user.company_id if user.company_id else Person.user_id == user.id


def _group_filter(user):
    return QuoteGroup.company_id == user.company_id if user.company_id else QuoteGroup.user_id == user.id


def _quote_filter(user):
    return WebQuote.company_id == user.company_id if user.company_id else WebQuote.user_id == user.id


def _accepted_filter(user):
    return AcceptedQuote.company_id == user.company_id if user.company_id else AcceptedQuote.user_id == user.id


def _flight_filter(user):
    return FlightRegistry.company_id == user.company_id if user.company_id else FlightRegistry.user_id == user.id


def _users_for_filters(db: Session, user) -> list[WebUser]:
    """Usuários visíveis nos filtros.

    Se existir empresa/grupo, mostra todos do grupo para permitir controle
    das cotações feitas por cada membro. Se não existir empresa, mostra só o
    usuário atual.
    """
    if user.company_id:
        return db.scalars(
            select(WebUser)
            .where(WebUser.company_id == user.company_id, WebUser.active.is_(True))
            .options(selectinload(WebUser.profile))
            .order_by(WebUser.name)
        ).all()
    return [user]


def _parse_int(value: str | None) -> int | None:
    try:
        number = int(value or 0)
        return number or None
    except (TypeError, ValueError):
        return None


def _avatar_initial(name: str | None) -> str:
    clean = str(name or '').strip()
    return (clean[:1] or '?').upper()


def _parse_date(value: str | None):
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def _flight_status(departure: str | None) -> str:
    dep = _parse_date(departure)
    if dep is None:
        return "Sem data"
    today = date.today()
    delta = (dep - today).days
    if delta < 0:
        return "Voo passado"
    if delta <= 2:
        return "Check-in próximo"
    return "Voo futuro"


def _money_to_float(value: str | None) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = text.replace("R$", "").replace(" ", "").replace(".", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _float_to_br(value: float | int | None) -> str:
    try:
        number = float(value or 0)
    except Exception:
        number = 0.0
    return f"{number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def _checkin_link_for_airline(airline_name: str | None, locator: str | None = None, purchase_number: str | None = None) -> str:
    return checkin_link_for_airline(airline_name, locator=locator, purchase_number=purchase_number)

def _ensure_quick_person(db: Session, user, name: str | None, person_type: str = "passageiro") -> Person | None:
    """Cria cadastro rápido de pessoa quando a reserva recebeu apenas nome.

    A pessoa fica pendente porque CPF/data de nascimento continuam vazios. Isso
    deixa o fluxo livre e mantém o cadastro organizado para completar depois.
    """
    clean = " ".join(str(name or "").strip().split())
    if len(clean) < 2:
        return None
    existing = db.scalar(
        select(Person)
        .where(_person_filter(user), func.lower(Person.name) == clean.lower(), Person.active.is_(True))
        .order_by(Person.id.desc())
    )
    if existing:
        return existing
    ptype = person_type if person_type in {"passageiro", "cliente", "fornecedor", "representante"} else "passageiro"
    person = Person(
        company_id=user.company_id,
        user_id=None if user.company_id else user.id,
        name=clean,
        person_type=ptype,
        is_complete=False,
        active=True,
    )
    db.add(person)
    db.flush()
    return person


def _safe_json(value: str | None, default: Any) -> Any:
    try:
        if not value:
            return default
        parsed = json.loads(value)
        return parsed if parsed is not None else default
    except Exception:
        return default


def _safe_flight_list(value: Any) -> list[dict[str, Any]]:
    """Normaliza listas de voos antigas ou parcialmente salvas.

    Registros antigos podem conter ``flights`` vazio, como dicionário único ou
    com itens que não são objetos. A agenda nunca deve cair por causa disso.
    """
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _quote_scope_label(quote: WebQuote | None, fallback_trip: QuoteGroupTripDetail | None = None) -> str:
    """Rótulo seguro para a opção no histórico de cotações feitas."""
    if quote is not None:
        data = _safe_json(getattr(quote, "input_json", "{}"), {})
        if isinstance(data, dict):
            scope = data.get("_scope") if isinstance(data.get("_scope"), dict) else {}
            label = str(scope.get("label") or "").strip()
            if label and label.lower() != "cálculo":
                return label
            key = str(scope.get("key") or "").strip().lower()
            labels = {
                "round_trip": "Ida e volta",
                "outbound": "Só ida",
                "one_way": "Só ida",
                "return": "Só volta",
                "multi_city": "Multitrecho",
                "skip_normal": "Skip normal",
                "skip_inverse": "Skip inverso",
            }
            if key in labels:
                return labels[key]
        trip = getattr(quote, "trip", None)
        if trip is not None and getattr(trip, "travel_type", None):
            fallback_trip = trip
    travel_type = str(getattr(fallback_trip, "travel_type", "") or "").strip().lower()
    return {
        "round_trip": "Ida e volta",
        "multi_city": "Multitrecho",
        "return": "Só volta",
        "one_way": "Só ida",
    }.get(travel_type, "Só ida")


def _payload(item: AcceptedQuote | None) -> dict[str, Any]:
    data = _safe_json(getattr(item, "extra_json", "{}"), {})
    return data if isinstance(data, dict) else {}


def _set_payload(item: AcceptedQuote, data: dict[str, Any]) -> None:
    item.extra_json = json.dumps(data or {}, ensure_ascii=False)


def _group_allowed(user, group: QuoteGroup | None) -> bool:
    return bool(group and (group.user_id == user.id or (user.company_id and group.company_id == user.company_id)))


def _quote_allowed(user, quote: WebQuote | None) -> bool:
    return bool(quote and (quote.user_id == user.id or (user.company_id and quote.company_id == user.company_id)))


def _get_option_group(db: Session, user, quote_id: int) -> tuple[WebQuote | None, QuoteGroup | None]:
    quote = db.scalar(
        select(WebQuote)
        .where(WebQuote.id == quote_id)
        .options(selectinload(WebQuote.airline), selectinload(WebQuote.calculation_type), selectinload(WebQuote.trip), selectinload(WebQuote.commercial))
    )
    if not _quote_allowed(user, quote):
        return None, None

    link = db.get(QuoteOptionIndex, quote.id)
    if link:
        group = db.scalar(select(QuoteGroup).where(QuoteGroup.id == link.group_id).options(selectinload(QuoteGroup.trip)))
        if _group_allowed(user, group):
            return quote, group

    group = _copy_quote_to_group(db, user, quote)
    return quote, group


def _first_option_for_group(db: Session, user, group: QuoteGroup) -> WebQuote | None:
    links = db.scalars(
        select(QuoteOptionIndex).where(QuoteOptionIndex.group_id == group.id).order_by(QuoteOptionIndex.position, QuoteOptionIndex.created_at)
    ).all()
    for link in links:
        quote = db.scalar(
            select(WebQuote)
            .where(WebQuote.id == link.quote_id)
            .options(selectinload(WebQuote.airline), selectinload(WebQuote.calculation_type), selectinload(WebQuote.trip))
        )
        if _quote_allowed(user, quote):
            return quote
    return None


def _copy_quote_to_group(db: Session, user, quote: WebQuote) -> QuoteGroup:
    existing_link = db.get(QuoteOptionIndex, quote.id)
    if existing_link:
        group = db.get(QuoteGroup, existing_link.group_id)
        if _group_allowed(user, group):
            return group

    group = QuoteGroup(
        user_id=user.id,
        company_id=user.company_id,
        quote_name=quote.quote_name or "Cotação selecionada",
        origin=quote.origin,
        destination=quote.destination,
        passengers=quote.passengers or 1,
        babies=quote.babies or 0,
        bags=0,
        assigned_user_id=user.id,
    )
    db.add(group)
    db.flush()

    if quote.trip:
        db.add(
            QuoteGroupTripDetail(
                group_id=group.id,
                travel_type=quote.trip.travel_type,
                departure_date=quote.trip.departure_date,
                return_date=quote.trip.return_date,
                segments_json=quote.trip.segments_json,
                client_name=quote.trip.client_name,
                client_email=quote.trip.client_email,
                client_phone=quote.trip.client_phone,
                notes=quote.trip.notes,
            )
        )
    db.add(QuoteOptionIndex(quote_id=quote.id, group_id=group.id, position=1))
    db.flush()
    return group


def _selected_groups_from_form(db: Session, user, form) -> list[QuoteGroup]:
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

    selected: list[QuoteGroup] = []
    seen: set[int] = set()
    if group_ids:
        groups = db.scalars(select(QuoteGroup).where(QuoteGroup.id.in_(group_ids), _group_filter(user)).options(selectinload(QuoteGroup.trip))).all()
        for group in groups:
            if group.id not in seen:
                selected.append(group)
                seen.add(group.id)
    if quote_ids:
        quotes = db.scalars(select(WebQuote).where(WebQuote.id.in_(quote_ids), _quote_filter(user)).options(selectinload(WebQuote.trip))).all()
        for quote in quotes:
            if not _quote_allowed(user, quote):
                continue
            group = _copy_quote_to_group(db, user, quote)
            if group.id not in seen:
                selected.append(group)
                seen.add(group.id)
    return selected


def _quote_schedule_data(quote: WebQuote | None) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    if quote is None:
        return {}, {}, []
    data = _safe_json(getattr(quote, "input_json", "{}"), {})
    if not isinstance(data, dict):
        data = {}
    scope = data.get("_scope") if isinstance(data.get("_scope"), dict) else {}
    details = data.get("_flight_details") if isinstance(data.get("_flight_details"), list) else []
    return data, scope, [item for item in details if isinstance(item, dict)]


def _seed_flights(group: QuoteGroup, quote: WebQuote | None = None) -> list[dict[str, Any]]:
    trip = group.trip
    airline_name = quote.airline.name if quote and quote.airline else ""
    _data, scope, details = _quote_schedule_data(quote)
    fallback_origin = (quote.origin if quote else None) or group.origin or ""
    fallback_destination = (quote.destination if quote else None) or group.destination or ""
    checked_bags = int(getattr(quote, "bags", 0) or 0)

    def mark_skip(flights: list[dict[str, Any]]) -> list[dict[str, Any]]:
        skip_mode = str(scope.get("skip_mode") or "")
        try:
            flown_segment = int(scope.get("flown_segment") or 0)
        except (TypeError, ValueError):
            flown_segment = 0
        if not skip_mode or not flown_segment:
            return flights
        for index, flight in enumerate(flights, start=1):
            flight["skip_mode"] = skip_mode
            flight["is_flown_segment"] = index == flown_segment
            marker = "TRECHO UTILIZADO PELO PASSAGEIRO" if index == flown_segment else "TRECHO NÃO UTILIZADO NO PADRÃO SKIP"
            existing_notes = str(flight.get("notes") or "").strip()
            flight["notes"] = f"{marker}. {existing_notes}".strip()
        return flights

    def make_flight(*, kind: str, label: str, origin: str, destination: str, departure_date: str = "", departure_time: str = "", arrival_date: str = "", arrival_time: str = "", flexible: bool = False, option_number: int = 1, segment_key: str = "", selected_schedule: bool = True, airline_override: str = "") -> dict[str, Any]:
        return {
            "kind": kind,
            "label": label,
            "segment_key": segment_key or kind,
            "selected_schedule": bool(selected_schedule),
            "origin": origin or "",
            "destination": destination or "",
            "date": departure_date or "",
            "departure_date": departure_date or "",
            "arrival_date": arrival_date or departure_date or "",
            "return_date": str(scope.get("return_date") or (trip.return_date if trip else "") or ""),
            "airline": str(airline_override or airline_name),
            "checkin_link": "",
            "notification_mode": "notificar_48h",
            "flight_number": "",
            "locator": "",
            "purchase_number": "",
            "departure_time": departure_time or "",
            "arrival_time": arrival_time or "",
            "duration": "",
            "class": "Econômica",
            "connections": "Direto",
            "checkin_status": "pendente",
            "bags_personal": 1,
            "bags_carry": 1,
            "bags_checked": checked_bags,
            "notes": "Alternativa de data/horário da cotação" if flexible else "",
            "stops": [],
            "is_flexible_option": flexible,
            "schedule_option_number": option_number,
        }

    if details:
        totals: dict[str, int] = {}
        for detail in details:
            key = str(detail.get("segment_key") or detail.get("label") or "voo")
            totals[key] = totals.get(key, 0) + 1
        positions: dict[str, int] = {}
        flights: list[dict[str, Any]] = []
        for detail in details[:20]:
            key = str(detail.get("segment_key") or detail.get("label") or "voo")
            positions[key] = positions.get(key, 0) + 1
            flexible = totals.get(key, 0) > 1
            base_label = str(detail.get("label") or "Voo").strip() or "Voo"
            label = f"{base_label} — opção {positions[key]}" if flexible else base_label
            kind = str(detail.get("kind") or ("volta" if key == "return" else "ida" if key in {"outbound", "one_way"} else "trecho"))
            flights.append(make_flight(
                kind=kind,
                label=label,
                origin=str(detail.get("origin") or fallback_origin),
                destination=str(detail.get("destination") or fallback_destination),
                departure_date=str(detail.get("departure_date") or detail.get("date") or ""),
                departure_time=str(detail.get("departure_time") or ""),
                arrival_date=str(detail.get("arrival_date") or ""),
                arrival_time=str(detail.get("arrival_time") or ""),
                flexible=flexible,
                option_number=positions[key],
                segment_key=key,
                selected_schedule=(positions[key] == 1),
                airline_override=str(detail.get("airline") or ""),
            ))
        if flights:
            return mark_skip(flights)

    segments = scope.get("segments") if isinstance(scope.get("segments"), list) else []
    if not segments and quote and quote.trip:
        parsed = _safe_json(quote.trip.segments_json, [])
        segments = parsed if isinstance(parsed, list) else []
    if segments:
        flights = []
        for index, segment in enumerate(segments[:20]):
            if not isinstance(segment, dict):
                continue
            key = str(segment.get("key") or f"segment_{index + 1}")
            kind = "volta" if key == "return" else ("ida" if key in {"outbound", "one_way"} else "trecho")
            label = "Voo de Volta" if kind == "volta" else ("Voo de Ida" if kind == "ida" else f"Trecho {index + 1}")
            flights.append(make_flight(
                kind=kind,
                label=label,
                origin=str(segment.get("origin") or fallback_origin),
                destination=str(segment.get("destination") or fallback_destination),
                departure_date=str(segment.get("date") or ""),
                segment_key=key,
                selected_schedule=True,
            ))
        if flights:
            return mark_skip(flights)

    scope_key = str(scope.get("key") or "")
    departure_date = str(scope.get("departure_date") or (quote.trip.departure_date if quote and quote.trip else "") or (trip.departure_date if trip else "") or "")
    return_date = str(scope.get("return_date") or (quote.trip.return_date if quote and quote.trip else "") or (trip.return_date if trip else "") or "")
    if scope_key == "return":
        return [make_flight(kind="volta", label="Voo de Volta", origin=fallback_origin, destination=fallback_destination, departure_date=return_date or departure_date, segment_key="return")]
    if scope_key == "round_trip":
        return [
            make_flight(kind="ida", label="Voo de Ida", origin=fallback_origin, destination=fallback_destination, departure_date=departure_date, segment_key="outbound"),
            make_flight(kind="volta", label="Voo de Volta", origin=fallback_destination, destination=fallback_origin, departure_date=return_date, segment_key="return"),
        ]
    if fallback_origin or fallback_destination or departure_date or airline_name:
        return [make_flight(kind="ida", label="Voo de Ida", origin=fallback_origin, destination=fallback_destination, departure_date=departure_date, segment_key="outbound")]
    return []


def _seed_payload(group: QuoteGroup, quote: WebQuote | None = None) -> dict[str, Any]:
    trip = group.trip
    _input_data, scope, _details = _quote_schedule_data(quote)
    variant = _input_data.get("_variant") if isinstance(_input_data.get("_variant"), dict) else {}
    title = group.quote_name or (quote.quote_name if quote else "Nova cotação") or "Nova cotação"
    variant_name = str(variant.get("name") or "").strip()
    if variant_name and str(variant.get("key") or "primary") != "primary":
        title = f"{title} • {variant_name}"
    client_name = trip.client_name if trip else ""
    origin = (quote.origin if quote else None) or group.origin or ""
    destination = (quote.destination if quote else None) or group.destination or ""
    departure_date = str(scope.get("departure_date") or (quote.trip.departure_date if quote and quote.trip else "") or (trip.departure_date if trip else "") or "")
    return_date = str(scope.get("return_date") or (quote.trip.return_date if quote and quote.trip else "") or (trip.return_date if trip else "") or "")
    if str(scope.get("key") or "") == "return" and not departure_date:
        departure_date = return_date
    cost_value = float(getattr(quote, "total", 0) or 0)
    commercial = getattr(quote, "commercial", None) if quote is not None else None
    cash_sale_value = float(getattr(commercial, "sale_value", 0) or cost_value) if commercial else cost_value
    card_installments = max(1, int(getattr(commercial, "card_installments", 1) or 1)) if commercial else 1
    card_mode = str(getattr(commercial, "card_interest_mode", "cash") or "cash") if commercial else "cash"
    card_total_value = float(getattr(commercial, "card_total_value", 0) or cash_sale_value) if commercial else cash_sale_value
    card_installment_value = float(getattr(commercial, "card_installment_value", 0) or (card_total_value / card_installments if card_installments else card_total_value)) if commercial else cash_sale_value
    card_difference_value = float(getattr(commercial, "card_difference_value", 0) or max(0.0, card_total_value - cash_sale_value)) if commercial else 0.0
    desc = " ".join(x for x in [client_name or title, origin, destination, departure_date] if x).strip() or title
    flights = _seed_flights(group, quote)
    return {
        "quote_code": f"q{group.id:04d}",
        "title": title,
        "client_person_id": (trip.client_person_id if trip else None),
        "client_name": client_name,
        "channel": "WhatsApp",
        "affiliate": "",
        "user_name": "",
        "adults": max(1, int(group.passengers or 1)),
        "children": 0,
        "babies": max(0, int(group.babies or 0)),
        "flights": flights,
        "passengers": [],
        "cost_items": [
            {
                "type": "Milhas/Dinheiro",
                "description": desc,
                "supplier": "",
                "account": "",
                "category": "Pagamento Fornecedor",
                "payment_method": "[Pix]",
                "installments": 1,
                "due_date": departure_date,
                "value": cost_value,
                "paid": False,
            }
        ] if cost_value else [],
        "sale_items": [
            {
                "description": desc,
                "account": "",
                "category": "Venda de Passagem",
                "payment_method": "[Cartão]" if card_mode in {"no_interest", "with_interest"} else "[Pix]",
                "installments": card_installments if card_mode in {"no_interest", "with_interest"} else 1,
                "due_date": departure_date,
                "value": cash_sale_value,
                "paid": False,
            }
        ] if cash_sale_value else [],
        "commission": {"receive": [], "pay": [], "extra": 0},
        "services": {"hotel": [], "transport": [], "cruise": [], "experiences": [], "insurance": [], "additional": [], "itinerary": ""},
        "terms": "",
        "notes": "",
        "sale": {"date": "", "launched": False, "launched_at": "", "notes": ""},
        "commercial_offer": {
            "cost_value": round(cost_value, 2),
            "cash_sale_value": round(cash_sale_value, 2),
            "profit_value": round(float(getattr(commercial, "profit_value", 0) or max(0.0, cash_sale_value - cost_value)), 2) if commercial else 0.0,
            "profit_percent": round(float(getattr(commercial, "profit_percent", 0) or 0), 4) if commercial else 0.0,
            "card_installments": card_installments,
            "card_interest_mode": card_mode,
            "card_total_value": round(card_total_value, 2),
            "card_installment_value": round(card_installment_value, 2),
            "card_difference_value": round(card_difference_value, 2),
            "sent_to_client": bool(getattr(commercial, "sent_to_client_at", None)) if commercial else False,
        },
        "_source_quote_id": quote.id if quote else None,
        "_selected_variant": variant,
        "_selected_scope": scope,
    }


def _ensure_accepted(db: Session, user, group: QuoteGroup, quote: WebQuote | None = None) -> tuple[AcceptedQuote, bool]:
    item = db.get(AcceptedQuote, group.id)
    created = item is None
    previous_quote_id = item.quote_id if item is not None else None
    if item is None:
        item = AcceptedQuote(group_id=group.id, user_id=user.id, company_id=user.company_id)
        db.add(item)
    item.user_id = user.id
    item.company_id = user.company_id
    if quote is not None:
        item.quote_id = quote.id
        if not item.sale_value or previous_quote_id != quote.id:
            commercial_sale = float(getattr(getattr(quote, "commercial", None), "sale_value", 0) or 0)
            item.sale_value = commercial_sale or quote.total
    if not item.status or item.status == "aceita":
        item.status = "aguardando"
    data = _payload(item)
    seeded = _seed_payload(group, quote)
    if created or not data:
        data = seeded
        _set_payload(item, data)
    elif quote is not None and (previous_quote_id != quote.id or not data.get("flights")):
        # Ao escolher outra opção calculada, leva junto os horários, datas e
        # possibilidades daquela opção sem apagar os demais dados comerciais.
        data["flights"] = seeded.get("flights", [])
        data["title"] = seeded.get("title", data.get("title", ""))
        data["_source_quote_id"] = quote.id
        data["_selected_variant"] = seeded.get("_selected_variant", {})
        data["_selected_scope"] = seeded.get("_selected_scope", {})
        data["commercial_offer"] = seeded.get("commercial_offer", {})
        data["cost_items"] = seeded.get("cost_items", data.get("cost_items", []))
        data["sale_items"] = seeded.get("sale_items", data.get("sale_items", []))
        _set_payload(item, data)
    return item, created


def _ensure_flight(db: Session, user, group: QuoteGroup, quote: WebQuote | None = None) -> tuple[FlightRegistry, bool]:
    item = db.get(FlightRegistry, group.id)
    created = item is None
    if item is None:
        item = FlightRegistry(group_id=group.id, user_id=user.id, company_id=user.company_id)
        db.add(item)
    item.user_id = user.id
    item.company_id = user.company_id
    if quote is not None:
        item.quote_id = quote.id
        if quote.airline and not item.airline_name:
            item.airline_name = quote.airline.name
    return item, created


def _mark_accepted(db: Session, user, groups: list[QuoteGroup]) -> int:
    count = 0
    for group in groups:
        if not _group_allowed(user, group):
            continue
        quote = _first_option_for_group(db, user, group)
        _item, created = _ensure_accepted(db, user, group, quote)
        count += int(created)
    return count


def _mark_flight(db: Session, user, groups: list[QuoteGroup]) -> int:
    count = 0
    for group in groups:
        if not _group_allowed(user, group):
            continue
        quote = _first_option_for_group(db, user, group)
        _item, created = _ensure_flight(db, user, group, quote)
        count += int(created)
    return count


def _item_total(data: dict[str, Any], key: str) -> float:
    total = 0.0
    for row in data.get(key, []) or []:
        try:
            total += float(row.get("value") or 0)
        except Exception:
            pass
    return total


def _sync_sale_total_from_preview(data: dict[str, Any], value: Any) -> float:
    """Mantém o valor do preview e os itens de venda apontando para o mesmo total."""
    try:
        total = max(0.0, round(float(value or 0), 2))
    except (TypeError, ValueError):
        total = 0.0

    rows = [row for row in (data.get("sale_items") or []) if isinstance(row, dict)]
    if not rows:
        if total > 0:
            rows = [{
                "description": "Valor da cotação",
                "value": total,
                "account": "",
                "category": "Passagem aérea",
                "due_date": "",
                "payment_method": "",
                "installments": 1,
                "paid": False,
            }]
        else:
            rows = []
    else:
        old_total = sum(max(0.0, float(row.get("value") or 0)) for row in rows)
        if old_total > 0:
            allocated = 0.0
            for row in rows[:-1]:
                part = round(total * (max(0.0, float(row.get("value") or 0)) / old_total), 2)
                row["value"] = part
                allocated += part
            rows[-1]["value"] = round(total - allocated, 2)
        else:
            for row in rows:
                row["value"] = 0.0
            if rows:
                rows[0]["value"] = total
    data["sale_items"] = rows

    preview = data.get("preview") if isinstance(data.get("preview"), dict) else {}
    preview["price"] = total
    data["preview"] = preview

    commercial = data.get("commercial_offer") if isinstance(data.get("commercial_offer"), dict) else {}
    if commercial:
        commercial["cash_sale_value"] = total
        data["commercial_offer"] = commercial
    return total


def _apply_quote_from_payload(item: AcceptedQuote, data: dict[str, Any]) -> None:
    sale_total = _item_total(data, "sale_items")
    # O total de venda é canônico: se os itens foram removidos, o valor também zera.
    if "sale_items" in data:
        item.sale_value = sale_total
    item.channel = data.get("channel") or item.channel
    item.locator = ""
    flights = data.get("flights") or []
    for fl in flights:
        if fl.get("locator"):
            item.locator = str(fl.get("locator") or "").strip().upper()
            break
    item.notes = data.get("notes") or None
    item.terms = data.get("terms") or None
    sale = data.get("sale") or {}
    if sale.get("launched") and item.status != "reprovado":
        item.status = "lancada"


def _operational_flights(data: dict[str, Any]) -> list[dict[str, Any]]:
    flights = [item for item in (data.get("flights") or []) if isinstance(item, dict)]
    # Registros antigos não tinham seleção de horário: nesse caso todos continuam válidos.
    if not any("selected_schedule" in item for item in flights):
        return flights
    chosen = [item for item in flights if bool(item.get("selected_schedule"))]
    return chosen or flights[:1]


def _sync_flight_registry(db: Session, user, item: AcceptedQuote, data: dict[str, Any]) -> None:
    flights = _operational_flights(data)
    first = None
    for fl in flights:
        if fl.get("departure_date") or fl.get("date") or fl.get("origin") or fl.get("destination") or fl.get("flight_number") or fl.get("locator"):
            first = fl
            break
    if not first:
        return
    flight, _created = _ensure_flight(db, user, item.group, item.quote)
    airline_name = first.get("airline") or (item.quote.airline.name if item.quote and item.quote.airline else None)
    flight.checkin_status = first.get("checkin_status") or "pendente"
    flight.notification_mode = first.get("notification_mode") or None
    flight.locator = (first.get("locator") or item.locator or "").strip().upper() or None
    flight.flight_number = first.get("flight_number") or None
    flight.airline_name = airline_name
    flight.departure_time = first.get("departure_time") or None
    flight.arrival_time = first.get("arrival_time") or None
    flight.checkin_link = (first.get("checkin_link") or _checkin_link_for_airline(airline_name, first.get("locator"), first.get("purchase_number")) or None)
    flight.notes = first.get("notes") or None
    flight.extra_json = json.dumps({"flights": flights}, ensure_ascii=False)


def _people_choices(db: Session, user) -> list[Person]:
    return db.scalars(select(Person).where(_person_filter(user), Person.active.is_(True)).order_by(Person.name).limit(1000)).all()


def _registered_person(
    db: Session,
    user,
    raw_id: Any = None,
    *,
    exact_name: str | None = None,
    allowed_types: set[str] | None = None,
) -> Person | None:
    """Resolve somente cadastros ativos e visíveis ao usuário atual.

    O nome exato é aceito apenas como compatibilidade para registros antigos que
    ainda não possuem ``person_id`` no JSON. Nomes novos precisam ser escolhidos
    no autocomplete, que sempre envia o identificador.
    """
    person: Person | None = None
    try:
        person_id = int(str(raw_id or "").strip())
    except (TypeError, ValueError):
        person_id = 0
    if person_id:
        person = db.scalar(
            select(Person).where(Person.id == person_id, _person_filter(user), Person.active.is_(True))
        )
    if person is None and exact_name:
        clean = " ".join(str(exact_name or "").strip().split())
        if clean:
            matches = db.scalars(
                select(Person)
                .where(_person_filter(user), Person.active.is_(True), func.lower(Person.name) == clean.lower())
                .order_by(Person.id.desc())
                .limit(2)
            ).all()
            if len(matches) == 1:
                person = matches[0]
    if person is None:
        return None
    if allowed_types and person.person_type not in allowed_types:
        return None
    return person


def _iata_code(value: Any) -> str:
    """Retorna o código IATA de três letras sempre que possível."""
    raw = " ".join(str(value or "").strip().split())
    if not raw:
        return ""
    upper = raw.upper()
    code_match = re.search(r"\b([A-Z]{3})\b", upper)
    if code_match:
        return code_match.group(1)
    normalized = _search_normalized(raw)
    exact = [code for code, name in BR_AIRPORTS.items() if normalized in {_search_normalized(code), _search_normalized(name)}]
    if len(exact) == 1:
        return exact[0]
    partial = [code for code, name in BR_AIRPORTS.items() if normalized and normalized in _search_normalized(name)]
    return partial[0] if len(partial) == 1 else upper[:80]


def _iata_value_valid(value: Any) -> bool:
    raw = " ".join(str(value or "").strip().split())
    if not raw:
        return True
    upper = raw.upper()
    if re.fullmatch(r"[A-Z]{3}", upper):
        return True
    if re.match(r"^[A-Z]{3}\s*(?:[-—|/]|$)", upper):
        return True
    normalized = _search_normalized(raw)
    return any(normalized == _search_normalized(name) for name in BR_AIRPORTS.values())


def _current_item(db: Session, user, group_id: int) -> AcceptedQuote | None:
    return db.scalar(
        select(AcceptedQuote)
        .where(AcceptedQuote.group_id == group_id, _accepted_filter(user))
        .options(
            selectinload(AcceptedQuote.group).selectinload(QuoteGroup.trip),
            selectinload(AcceptedQuote.group).selectinload(QuoteGroup.user).selectinload(WebUser.profile),
            selectinload(AcceptedQuote.group).selectinload(QuoteGroup.assigned_user).selectinload(WebUser.profile),
            selectinload(AcceptedQuote.quote).selectinload(WebQuote.airline),
            selectinload(AcceptedQuote.quote).selectinload(WebQuote.calculation_type),
            selectinload(AcceptedQuote.quote).selectinload(WebQuote.commercial),
            selectinload(AcceptedQuote.user).selectinload(WebUser.profile),
        )
    )



def _search_normalized(value: str | None) -> str:
    raw = unicodedata.normalize("NFD", str(value or "").strip().lower())
    return "".join(ch for ch in raw if unicodedata.category(ch) != "Mn")


@router.get("/airports/search")
def search_airports(request: Request, q: str = "", limit: int = 20, db: Session = Depends(get_db)):
    """Autocomplete estrito por prefixo do código IATA.

    Ex.: ao digitar ``VC`` aparece ``VCP - Viracopos / Campinas``. Nomes de
    cidades não são usados como chave de pesquisa, evitando resultados fora
    do padrão operacional da agência.
    """
    require_user(request, db)
    needle = re.sub(r"[^A-Za-z]", "", str(q or "")).upper()[:3]
    safe_limit = min(max(int(limit or 20), 5), 60)
    rows: list[dict[str, str]] = []
    for code, name in BR_AIRPORTS.items():
        code_upper = str(code or "").upper()[:3]
        if needle and not code_upper.startswith(needle):
            continue
        rows.append({"code": code_upper, "name": name, "display": f"{code_upper} - {name}"})
    preferred = {"FOR": 0, "GRU": 1, "CGH": 2, "GIG": 3, "SDU": 4, "BSB": 5, "REC": 6, "SSA": 7, "VCP": 8, "MIA": 9, "MCO": 10, "LIS": 11, "OPO": 12, "FAO": 13, "FNC": 14, "PDL": 15}
    rows.sort(key=lambda item: (0 if needle and item["code"].startswith(needle) else 1, preferred.get(item["code"], 1000), item["code"]))
    if len(needle) == 3 and needle not in BR_AIRPORTS:
        rows.insert(0, {"code": needle, "name": "IATA informado manualmente", "display": f"{needle} - usar código manual", "manual": "1"})
    return JSONResponse({"results": rows[:safe_limit]}, headers={"Cache-Control": "no-store, max-age=0"})


@router.get("")
@router.get("/")
def cadastros_menu(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    pending_people = db.scalars(
        select(Person).where(_person_filter(user), Person.is_complete.is_(False), Person.active.is_(True)).order_by(desc(Person.created_at)).limit(6)
    ).all()
    accepted_count = db.scalar(select(func.count(AcceptedQuote.group_id)).where(_accepted_filter(user))) or 0
    flight_count = db.scalar(select(func.count(FlightRegistry.group_id)).where(_flight_filter(user))) or 0
    return templates.TemplateResponse(
        request,
        "cadastros/menu.html",
        context(request, user=user, pending_people=pending_people, accepted_count=accepted_count, flight_count=flight_count),
    )


@router.get("/pessoas")
@router.get("/pessoa")
def cadastros_pessoas_redirect(request: Request):
    return RedirectResponse("/persons", status_code=303)


@router.get("/cotacoes")
@router.get("/cotacoes-aceitas")
def cotacoes(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    qp = request.query_params
    q = (qp.get("q") or "").strip().lower()
    status_filter = (qp.get("status") or "").strip()
    client_filter = (qp.get("client") or "").strip().lower()
    user_filter = _parse_int(qp.get("user_id"))
    date_from = _parse_date(qp.get("from"))
    date_to = _parse_date(qp.get("to"))

    board_statuses = _board_statuses(db, user)
    valid_statuses = {key for key, _label, _color in board_statuses}

    rows = db.scalars(
        select(AcceptedQuote)
        .where(_accepted_filter(user))
        .options(
            selectinload(AcceptedQuote.group).selectinload(QuoteGroup.trip),
            selectinload(AcceptedQuote.group).selectinload(QuoteGroup.user).selectinload(WebUser.profile),
            selectinload(AcceptedQuote.group).selectinload(QuoteGroup.assigned_user).selectinload(WebUser.profile),
            selectinload(AcceptedQuote.quote).selectinload(WebQuote.airline),
            selectinload(AcceptedQuote.quote).selectinload(WebQuote.calculation_type),
            selectinload(AcceptedQuote.quote).selectinload(WebQuote.commercial),
            selectinload(AcceptedQuote.user).selectinload(WebUser.profile),
        )
        .order_by(desc(AcceptedQuote.updated_at), desc(AcceptedQuote.selected_at))
        .limit(800)
    ).all()

    cards = []
    totals = {key: 0.0 for key, _label, _color in board_statuses}
    counts = {key: 0 for key, _label, _color in board_statuses}
    accepted_group_ids = set()
    for item in rows:
        group = item.group
        if not _group_allowed(user, group):
            continue
        accepted_group_ids.add(group.id)
        data = _payload(item)
        status = item.status if item.status in valid_statuses else "aguardando"
        client = data.get("client_name") or (group.trip.client_name if group.trip else "") or group.quote_name or "Não informado"
        title = data.get("title") or group.quote_name or "Cotação"
        code = data.get("quote_code") or f"q{group.id:04d}"
        total = _item_total(data, "sale_items") or float(item.sale_value or 0)
        created = item.selected_at.date() if item.selected_at else date.today()
        if status_filter and status_filter != status:
            continue
        if user_filter and item.user_id != user_filter:
            continue
        if q and q not in " ".join([title, client, code, item.locator or "", getattr(item.user, "name", "") or ""]).lower():
            continue
        if client_filter and client_filter not in client.lower():
            continue
        if date_from and created < date_from:
            continue
        if date_to and created > date_to:
            continue
        cards.append({"item": item, "accepted": True, "group": group, "data": data, "status": status, "client": client, "title": title, "code": code, "total": total, "maker": group.user, "assigned": group.assigned_user, "accepted_by": item.user})
        totals[status] += total
        counts[status] += 1

    # V5.9.3: a cotação de cálculo também aparece no quadro de Cotações,
    # mesmo antes de virar cotação de emissão/reserva. Ela entra em
    # Aguardando como "bancada de cálculo" e continua abrindo o motor de cálculo.
    group_rows = db.scalars(
        select(QuoteGroup)
        .where(_group_filter(user))
        .options(selectinload(QuoteGroup.trip), selectinload(QuoteGroup.user).selectinload(WebUser.profile), selectinload(QuoteGroup.assigned_user).selectinload(WebUser.profile))
        .order_by(desc(QuoteGroup.updated_at), desc(QuoteGroup.created_at))
        .limit(800)
    ).all()
    for group in group_rows:
        if group.id in accepted_group_ids:
            continue
        options = _group_options_for_history(db, user, group)
        client = (group.trip.client_name if group.trip else "") or group.quote_name or "Não informado"
        title = group.quote_name or "Cotação de cálculo"
        code = f"calc{group.id:04d}"
        total = max([float(opt.total or 0) for opt in options], default=0.0)
        created = group.created_at.date() if group.created_at else date.today()
        status = "aguardando"
        if status_filter and status_filter != status:
            continue
        if user_filter and group.user_id != user_filter:
            continue
        if q and q not in " ".join([title, client, code, group.origin or "", group.destination or "", getattr(group.user, "name", "") or ""]).lower():
            continue
        if client_filter and client_filter not in client.lower():
            continue
        if date_from and created < date_from:
            continue
        if date_to and created > date_to:
            continue
        cards.append({"item": None, "accepted": False, "group": group, "data": {}, "status": status, "client": client, "title": title, "code": code, "total": total, "maker": group.user, "assigned": group.assigned_user, "options_count": len(options)})
        totals[status] += total
        counts[status] += 1

    grouped = {key: [] for key, _label, _color in board_statuses}
    for card in cards:
        grouped[card["status"]].append(card)

    people = _people_choices(db, user)
    return templates.TemplateResponse(
        request,
        "cadastros/cotacoes.html",
        context(
            request,
            user=user,
            statuses=board_statuses,
            grouped=grouped,
            totals=totals,
            counts=counts,
            people=people,
            users=_users_for_filters(db, user),
            filters={"q": q, "status": status_filter, "client": client_filter, "user_id": str(user_filter or ""), "from": qp.get("from") or "", "to": qp.get("to") or ""},
        ),
    )


def _group_options_for_history(db: Session, user, group: QuoteGroup) -> list[WebQuote]:
    links = db.scalars(
        select(QuoteOptionIndex)
        .where(QuoteOptionIndex.group_id == group.id)
        .order_by(QuoteOptionIndex.position, QuoteOptionIndex.created_at)
    ).all()
    quotes: list[WebQuote] = []
    for link in links:
        quote = db.scalar(
            select(WebQuote)
            .where(WebQuote.id == link.quote_id)
            .options(selectinload(WebQuote.airline), selectinload(WebQuote.calculation_type), selectinload(WebQuote.trip), selectinload(WebQuote.user).selectinload(WebUser.profile))
        )
        if _quote_allowed(user, quote):
            quotes.append(quote)
    return quotes




@router.get("/fluxo-calculo")
@router.get("/fluxo-calculo/")
@router.get("/fluxo-de-calculo")
def fluxo_calculo(request: Request, db: Session = Depends(get_db)):
    """Painel do fluxo de cálculo por usuário.

    Mostra quantas cotações/cálculos foram feitos no período por cada membro
    da empresa, com total geral, opções calculadas, cotações aceitas e vendas
    lançadas. É uma visão de produtividade, não substitui o quadro comercial.
    """
    user = require_user(request, db)
    qp = request.query_params
    today = date.today()
    date_from = _parse_date(qp.get("from")) or today
    date_to = _parse_date(qp.get("to")) or date_from
    if date_to < date_from:
        date_from, date_to = date_to, date_from
    user_filter = _parse_int(qp.get("user_id"))
    q = (qp.get("q") or "").strip().lower()

    visible_users = _users_for_filters(db, user)
    visible_ids = {u.id for u in visible_users}
    if user_filter:
        visible_ids = {user_filter} if user_filter in visible_ids else set()

    def _empty_stat(member: WebUser | None):
        return {
            "user": member,
            "bases": 0,
            "options": 0,
            "accepted": 0,
            "manual": 0,
            "legacy": 0,
            "launched": 0,
            "total_value": 0.0,
            "last_activity": None,
        }

    stats = {member.id: _empty_stat(member) for member in visible_users if member.id in visible_ids}
    daily: dict[str, dict[str, Any]] = {}

    def _inside(dt_value) -> bool:
        if dt_value is None:
            return False
        try:
            d = dt_value.date() if hasattr(dt_value, "date") else _parse_date(str(dt_value))
        except Exception:
            d = None
        return bool(d and date_from <= d <= date_to)

    def _day_key(dt_value) -> str:
        try:
            d = dt_value.date() if hasattr(dt_value, "date") else _parse_date(str(dt_value))
        except Exception:
            d = None
        d = d or today
        return d.isoformat()

    def _touch(uid: int | None, dt_value, field: str, value: float = 0.0):
        if uid not in stats:
            return
        stats[uid][field] += 1
        stats[uid]["total_value"] += float(value or 0)
        if dt_value and (stats[uid]["last_activity"] is None or dt_value > stats[uid]["last_activity"]):
            stats[uid]["last_activity"] = dt_value
        key = _day_key(dt_value)
        if key not in daily:
            daily[key] = {"date": key, "bases": 0, "options": 0, "accepted": 0, "manual": 0, "legacy": 0, "launched": 0, "total_value": 0.0}
        daily[key][field] += 1
        daily[key]["total_value"] += float(value or 0)

    groups = db.scalars(
        select(QuoteGroup)
        .where(_group_filter(user))
        .options(
            selectinload(QuoteGroup.trip),
            selectinload(QuoteGroup.user).selectinload(WebUser.profile),
            selectinload(QuoteGroup.option_links).selectinload(QuoteOptionIndex.quote).selectinload(WebQuote.airline),
        )
        .order_by(desc(QuoteGroup.created_at))
        .limit(3000)
    ).all()

    for group in groups:
        if not _group_allowed(user, group):
            continue
        trip = group.trip
        client = (trip.client_name if trip else "") or group.quote_name or ""
        haystack = " ".join([group.quote_name or "", client, group.origin or "", group.destination or "", getattr(group.user, "name", "") or ""]).lower()
        if q and q not in haystack:
            continue
        if _inside(group.created_at):
            options = [link.quote for link in (group.option_links or []) if link.quote is not None and _quote_allowed(user, link.quote)]
            group_value = max([float(opt.total or 0) for opt in options], default=0.0)
            _touch(group.user_id, group.created_at, "bases", group_value)
        for link in group.option_links or []:
            quote = link.quote
            if quote is None or not _quote_allowed(user, quote):
                continue
            if not _inside(quote.created_at):
                continue
            qhay = " ".join([quote.quote_name or "", quote.origin or "", quote.destination or "", getattr(quote.airline, "name", "") or "", getattr(quote.user, "name", "") or ""]).lower()
            if q and q not in (haystack + " " + qhay):
                continue
            _touch(quote.user_id, quote.created_at, "options", float(quote.total or 0))

    accepted_rows = db.scalars(
        select(AcceptedQuote)
        .where(_accepted_filter(user))
        .options(selectinload(AcceptedQuote.user).selectinload(WebUser.profile), selectinload(AcceptedQuote.group).selectinload(QuoteGroup.trip))
        .order_by(desc(AcceptedQuote.selected_at))
        .limit(3000)
    ).all()
    for item in accepted_rows:
        if item.user_id not in visible_ids or not _inside(item.selected_at):
            continue
        group = item.group
        pdata = _payload(item)
        client = pdata.get("client_name") or (group.trip.client_name if group and group.trip else "") or (group.quote_name if group else "") or ""
        haystack = " ".join([client, pdata.get("quote_code") or "", pdata.get("title") or "", getattr(item.user, "name", "") or "", item.locator or ""]).lower()
        if q and q not in haystack:
            continue
        total = _item_total(pdata, "sale_items") or float(item.sale_value or 0)
        _touch(item.user_id, item.selected_at, "accepted", total)
        if item.quote_id is None:
            _touch(item.user_id, item.selected_at, "manual", 0)
        if item.status == "lancada":
            _touch(item.user_id, item.updated_at or item.selected_at, "launched", total)

    linked_ids = select(QuoteOptionIndex.quote_id)
    legacy_rows = db.scalars(
        select(WebQuote)
        .where(_quote_filter(user), WebQuote.id.notin_(linked_ids))
        .options(selectinload(WebQuote.user).selectinload(WebUser.profile), selectinload(WebQuote.airline), selectinload(WebQuote.trip))
        .order_by(desc(WebQuote.created_at))
        .limit(1000)
    ).all()
    for quote in legacy_rows:
        if quote.user_id not in visible_ids or not _inside(quote.created_at):
            continue
        trip = quote.trip
        client = (trip.client_name if trip else "") or quote.quote_name or ""
        haystack = " ".join([quote.quote_name or "", client, quote.origin or "", quote.destination or "", getattr(quote.airline, "name", "") or "", getattr(quote.user, "name", "") or ""]).lower()
        if q and q not in haystack:
            continue
        _touch(quote.user_id, quote.created_at, "legacy", float(quote.total or 0))

    stat_rows = []
    for uid, row in stats.items():
        total_activity = row["bases"] + row["options"] + row["accepted"] + row["manual"] + row["legacy"]
        row["total_activity"] = total_activity
        if total_activity or not q:
            stat_rows.append(row)
    stat_rows.sort(key=lambda row: (row["total_activity"], row["total_value"]), reverse=True)

    totals = {
        "bases": sum(r["bases"] for r in stats.values()),
        "options": sum(r["options"] for r in stats.values()),
        "accepted": sum(r["accepted"] for r in stats.values()),
        "manual": sum(r["manual"] for r in stats.values()),
        "legacy": sum(r["legacy"] for r in stats.values()),
        "launched": sum(r["launched"] for r in stats.values()),
        "total_value": sum(r["total_value"] for r in stats.values()),
    }
    totals["total_activity"] = totals["bases"] + totals["options"] + totals["accepted"] + totals["manual"] + totals["legacy"]

    daily_rows = sorted(daily.values(), key=lambda row: row["date"], reverse=True)

    return templates.TemplateResponse(
        request,
        "cadastros/fluxo_calculo.html",
        context(
            request,
            user=user,
            users=_users_for_filters(db, user),
            rows=stat_rows,
            daily_rows=daily_rows,
            totals=totals,
            filters={"q": q, "user_id": str(user_filter or ""), "from": date_from.isoformat(), "to": date_to.isoformat()},
        ),
    )


@router.get("/cotacoes-feitas")
@router.get("/cotacoes-feitas/")
@router.get("/historico-cotacoes")
def cotacoes_feitas(request: Request, db: Session = Depends(get_db)):
    """Histórico comercial dentro do módulo de Cotações.

    Mostra bases/cálculos/cadastros de todos os usuários visíveis no grupo,
    com filtro por usuário e avatar de quem criou a cotação.
    """
    user = require_user(request, db)
    qp = request.query_params
    q = (qp.get("q") or "").strip().lower()
    client_filter = (qp.get("client") or "").strip().lower()
    source_filter = (qp.get("source") or "").strip()
    user_filter = _parse_int(qp.get("user_id"))
    date_from = _parse_date(qp.get("from"))
    date_to = _parse_date(qp.get("to"))

    groups = db.scalars(
        select(QuoteGroup)
        .where(_group_filter(user))
        .options(selectinload(QuoteGroup.trip), selectinload(QuoteGroup.user).selectinload(WebUser.profile))
        .order_by(desc(QuoteGroup.updated_at), desc(QuoteGroup.created_at))
        .limit(1000)
    ).all()

    accepted_rows = db.scalars(select(AcceptedQuote).where(_accepted_filter(user))).all()
    accepted_by_group = {row.group_id: row for row in accepted_rows}

    cards: list[dict[str, Any]] = []
    for group in groups:
        if not _group_allowed(user, group):
            continue
        options = _group_options_for_history(db, user, group)
        accepted = accepted_by_group.get(group.id)
        trip = group.trip
        client = (trip.client_name if trip else "") or group.quote_name or "Não informado"
        title = group.quote_name or "Cotação"
        code = f"q{group.id:04d}"
        created = (group.created_at or datetime.utcnow()).date()
        updated = group.updated_at or group.created_at
        total = max([float(opt.total or 0) for opt in options], default=float(getattr(accepted, "sale_value", 0) or 0))
        source = "manual" if accepted is not None and accepted.quote_id is None and not options else ("aceita" if accepted is not None else "calculada")
        if source_filter and source_filter != source:
            continue
        if user_filter and group.user_id != user_filter:
            continue
        if client_filter and client_filter not in client.lower():
            continue
        haystack = " ".join([title, client, code, group.origin or "", group.destination or "", getattr(group.user, "name", "") or ""]).lower()
        if q and q not in haystack:
            continue
        if date_from and created < date_from:
            continue
        if date_to and created > date_to:
            continue
        option_details = [
            {"quote": option, "scope_label": _quote_scope_label(option, trip)}
            for option in options
        ]
        cards.append({
            "group": group,
            "trip": trip,
            "options": options,
            "option_details": option_details,
            "accepted": accepted,
            "client": client,
            "title": title,
            "code": code,
            "total": total,
            "source": source,
            "created": created,
            "updated": updated,
            "creator": group.user,
        })

    # Cotações antigas sem grupo continuam visíveis na área de cotações feitas.
    linked_ids = select(QuoteOptionIndex.quote_id)
    legacy_rows = db.scalars(
        select(WebQuote)
        .where(_quote_filter(user), WebQuote.id.notin_(linked_ids))
        .options(selectinload(WebQuote.airline), selectinload(WebQuote.trip), selectinload(WebQuote.user).selectinload(WebUser.profile))
        .order_by(desc(WebQuote.created_at))
        .limit(300)
    ).all()
    legacy_cards: list[dict[str, Any]] = []
    if source_filter in {"", "calculada"}:
        for quote in legacy_rows:
            if not _quote_allowed(user, quote):
                continue
            trip = quote.trip
            client = (trip.client_name if trip else "") or quote.quote_name or "Não informado"
            created = (quote.created_at or datetime.utcnow()).date()
            code = f"w{quote.id:04d}"
            if user_filter and quote.user_id != user_filter:
                continue
            if client_filter and client_filter not in client.lower():
                continue
            haystack = " ".join([quote.quote_name or "", client, code, quote.origin or "", quote.destination or "", getattr(quote.user, "name", "") or ""]).lower()
            if q and q not in haystack:
                continue
            if date_from and created < date_from:
                continue
            if date_to and created > date_to:
                continue
            legacy_cards.append({"quote": quote, "client": client, "code": code, "total": float(quote.total or 0), "created": created, "creator": quote.user})

    made_totals = {
        "groups": len(cards),
        "legacy": len(legacy_cards),
        "options": sum(len(card.get("options") or []) for card in cards),
        "value": sum(float(card.get("total") or 0) for card in cards) + sum(float(card.get("total") or 0) for card in legacy_cards),
        "users": len({(card.get("creator").id if card.get("creator") else 0) for card in cards} | {(card.get("creator").id if card.get("creator") else 0) for card in legacy_cards}),
    }

    return templates.TemplateResponse(
        request,
        "cadastros/cotacoes_feitas.html",
        context(
            request,
            user=user,
            cards=cards,
            legacy_cards=legacy_cards,
            made_totals=made_totals,
            users=_users_for_filters(db, user),
            filters={
                "q": q,
                "client": client_filter,
                "user_id": str(user_filter or ""),
                "source": source_filter,
                "from": qp.get("from") or "",
                "to": qp.get("to") or "",
            },
        ),
    )


@router.get("/financeiro")
@router.get("/financeiro/")
@router.get("/financeiro/dashboard")
@router.get("/financeiro/vendas")
@router.get("/financeiro/fluxo-caixa")
@router.get("/financeiro/formas-pagamento")
@router.get("/financeiro/formas-de-pagamento")
@router.get("/financeiro/pagamentos")
@router.get("/financeiro/meios-pagamento")
@router.get("/financeiro/vendas-lancadas")
@router.get("/vendas-lancadas")
@router.get("/fluxo-caixa")
@router.get("/fluxo-de-caixa")
@router.get("/formas-pagamento")
@router.get("/formas-de-pagamento")
def financeiro(request: Request, db: Session = Depends(get_db)):
    """Financeiro básico gerado a partir das vendas lançadas.

    Por enquanto não cria uma tabela nova: lê as cotações com status lançada
    e os itens de venda/custo salvos no JSON da reserva. Assim não mexe no
    banco do usuário e já dá controle mensal da empresa.
    """
    user = require_user(request, db)
    if user.role not in {"admin", "gerente"}:
        flash(request, "Seu nível de acesso não permite abrir o financeiro.", "error")
        return RedirectResponse("/dashboard", status_code=303)
    qp = request.query_params
    path = str(request.url.path)
    active_tab = "dashboard" if path.rstrip("/").endswith("/financeiro") or "dashboard" in path else "vendas"
    if "fluxo-caixa" in path:
        active_tab = "fluxo"
    elif "formas-pagamento" in path:
        active_tab = "pagamentos"

    today = date.today()
    date_from = _parse_date(qp.get("from")) or date(today.year, today.month, 1)
    date_to = _parse_date(qp.get("to")) or today
    if date_to < date_from:
        date_from, date_to = date_to, date_from
    user_filter = _parse_int(qp.get("user_id"))
    q = (qp.get("q") or "").strip().lower()

    rows = db.scalars(
        select(AcceptedQuote)
        .where(_accepted_filter(user))
        .options(
            selectinload(AcceptedQuote.group).selectinload(QuoteGroup.trip),
            selectinload(AcceptedQuote.quote).selectinload(WebQuote.airline),
            selectinload(AcceptedQuote.user).selectinload(WebUser.profile),
        )
        .order_by(desc(AcceptedQuote.updated_at), desc(AcceptedQuote.selected_at))
        .limit(2000)
    ).all()

    sales: list[dict[str, Any]] = []
    cash_rows: list[dict[str, Any]] = []
    payment_map: dict[str, dict[str, Any]] = {}

    for item in rows:
        if user_filter and item.user_id != user_filter:
            continue
        data = _payload(item)
        sale_meta = data.get("sale") if isinstance(data.get("sale"), dict) else {}
        launched = item.status == "lancada" or bool(sale_meta.get("launched"))
        if not launched:
            continue

        group = item.group
        trip = group.trip if group else None
        client = data.get("client_name") or (trip.client_name if trip else "") or (group.quote_name if group else "") or "Não informado"
        title = data.get("title") or (group.quote_name if group else "Venda") or "Venda"
        code = data.get("quote_code") or (f"q{group.id:04d}" if group else "")
        sale_date = _parse_date(str(sale_meta.get("date") or "")) or ((item.updated_at or item.selected_at).date() if (item.updated_at or item.selected_at) else today)
        if sale_date < date_from or sale_date > date_to:
            continue
        haystack = " ".join([title, client, code, getattr(item.user, "name", "") or "", item.locator or ""]).lower()
        if q and q not in haystack:
            continue

        sale_items = data.get("sale_items") if isinstance(data.get("sale_items"), list) else []
        cost_items = data.get("cost_items") if isinstance(data.get("cost_items"), list) else []
        commission = data.get("commission") if isinstance(data.get("commission"), dict) else {}
        sale_total = sum(float(x.get("value") or 0) for x in sale_items if isinstance(x, dict)) or float(item.sale_value or 0)
        cost_total = sum(float(x.get("value") or 0) for x in cost_items if isinstance(x, dict))
        commission_receive = commission.get("receive") if isinstance(commission.get("receive"), list) else []
        commission_pay = commission.get("pay") if isinstance(commission.get("pay"), list) else []
        commission_receive_total = sum(float(x.get("value") or 0) for x in commission_receive if isinstance(x, dict))
        commission_pay_total = sum(float(x.get("value") or 0) for x in commission_pay if isinstance(x, dict))
        commission_extra = float(commission.get("extra") or 0)
        profit = sale_total - cost_total + commission_receive_total - commission_pay_total + commission_extra

        sale_row = {
            "item": item,
            "group": group,
            "user": item.user,
            "client": client,
            "title": title,
            "code": code,
            "date": sale_date,
            "sale_total": sale_total,
            "cost_total": cost_total,
            "profit": profit,
            "commission_receive_total": commission_receive_total,
            "commission_pay_total": commission_pay_total,
            "items": sale_items,
            "costs": cost_items,
            "commissions_received": commission_receive,
            "commissions_paid": commission_pay,
            "payments": [],
        }
        for idx, pay in enumerate(sale_items or []):
            if not isinstance(pay, dict):
                continue
            method = str(pay.get("payment_method") or pay.get("account") or "Não informado").strip() or "Não informado"
            account = str(pay.get("account") or "").strip()
            installments = int(pay.get("installments") or 1)
            amount = float(pay.get("value") or 0)
            due_date = _parse_date(str(pay.get("due_date") or "")) or sale_date
            payment_description = str(pay.get("description") or pay.get("category") or "Venda").strip()
            payment_key = (method + (" / " + account if account else "")).strip()
            entry = {"date": due_date, "sale_date": sale_date, "method": method, "account": account, "installments": installments, "amount": amount, "description": payment_description, "client": client, "code": code, "user": item.user, "kind": "entrada"}
            sale_row["payments"].append(entry)
            cash_rows.append(entry)
            pay_stat = payment_map.setdefault(payment_key, {"name": payment_key, "count": 0, "total": 0.0, "installments": set(), "last_date": None})
            pay_stat["count"] += 1
            pay_stat["total"] += amount
            pay_stat["installments"].add(installments)
            if pay_stat["last_date"] is None or due_date > pay_stat["last_date"]:
                pay_stat["last_date"] = due_date
        if not sale_row["payments"]:
            entry = {"date": sale_date, "sale_date": sale_date, "method": "Não informado", "account": "", "installments": 1, "amount": sale_total, "description": "Venda lançada", "client": client, "code": code, "user": item.user, "kind": "entrada"}
            sale_row["payments"].append(entry)
            cash_rows.append(entry)
            pay_stat = payment_map.setdefault("Não informado", {"name": "Não informado", "count": 0, "total": 0.0, "installments": set(), "last_date": None})
            pay_stat["count"] += 1
            pay_stat["total"] += sale_total
            pay_stat["installments"].add(1)
            pay_stat["last_date"] = sale_date

        # Recebimentos e pagamentos de comissão usam os mesmos dados
        # financeiros informados na janela da venda.
        for commission_kind, commission_rows, cash_kind in (("recebida", commission_receive, "entrada"), ("paga", commission_pay, "saida")):
            for commission_item in commission_rows:
                if not isinstance(commission_item, dict):
                    continue
                commission_amount = float(commission_item.get("value") or 0)
                if commission_amount <= 0:
                    continue
                commission_due_date = _parse_date(str(commission_item.get("due_date") or "")) or sale_date
                cash_rows.append({
                    "date": commission_due_date,
                    "sale_date": sale_date,
                    "method": str(commission_item.get("payment_method") or commission_item.get("account") or "Não informado").strip() or "Não informado",
                    "account": str(commission_item.get("account") or "").strip(),
                    "installments": int(commission_item.get("installments") or 1),
                    "amount": commission_amount,
                    "description": str(commission_item.get("description") or commission_item.get("category") or f"Comissão {commission_kind}").strip(),
                    "client": client,
                    "code": code,
                    "user": item.user,
                    "kind": cash_kind,
                    "supplier": str(commission_item.get("supplier") or "").strip(),
                })

        # Custos também entram no fluxo para o dashboard mostrar entradas,
        # saídas e saldo previsto sem misturar sinais nos valores exibidos.
        for cost in cost_items or []:
            if not isinstance(cost, dict):
                continue
            cost_amount = float(cost.get("value") or 0)
            if cost_amount <= 0:
                continue
            cost_due_date = _parse_date(str(cost.get("due_date") or "")) or sale_date
            cash_rows.append({
                "date": cost_due_date,
                "sale_date": sale_date,
                "method": str(cost.get("payment_method") or cost.get("account") or "Não informado").strip() or "Não informado",
                "account": str(cost.get("account") or "").strip(),
                "installments": int(cost.get("installments") or 1),
                "amount": cost_amount,
                "description": str(cost.get("description") or cost.get("category") or "Custo").strip(),
                "client": client,
                "code": code,
                "user": item.user,
                "kind": "saida",
            })
        sales.append(sale_row)

    cash_in_total = sum(row["amount"] for row in cash_rows if row.get("kind") == "entrada")
    cash_out_total = sum(row["amount"] for row in cash_rows if row.get("kind") == "saida")
    sale_total_sum = sum(x["sale_total"] for x in sales)
    cost_total_sum = sum(x["cost_total"] for x in sales)
    profit_total_sum = sum(x["profit"] for x in sales)
    totals = {
        "sales_count": len(sales),
        "sale_total": sale_total_sum,
        "cost_total": cost_total_sum,
        "profit_total": profit_total_sum,
        "payments_count": len([row for row in cash_rows if row.get("kind") == "entrada"]),
        "cash_in_total": cash_in_total,
        "cash_out_total": cash_out_total,
        "cash_balance": cash_in_total - cash_out_total,
        "average_ticket": sale_total_sum / len(sales) if sales else 0.0,
        "margin_percent": (profit_total_sum / sale_total_sum * 100) if sale_total_sum else 0.0,
    }

    cash_rows.sort(key=lambda x: (x["date"], x["client"]), reverse=True)
    payment_rows = sorted(payment_map.values(), key=lambda x: x["total"], reverse=True)
    for row in payment_rows:
        row["installments_label"] = ", ".join(str(n) + "x" for n in sorted(row["installments"])) if row.get("installments") else "—"

    # Série diária do período e ranking de clientes para o dashboard.
    trend_map: dict[date, dict[str, Any]] = {}
    client_map: dict[str, dict[str, Any]] = {}
    for sale_row in sales:
        day = sale_row["date"]
        bucket = trend_map.setdefault(day, {"date": day, "sales": 0.0, "costs": 0.0, "profit": 0.0, "count": 0})
        bucket["sales"] += sale_row["sale_total"]
        bucket["costs"] += sale_row["cost_total"]
        bucket["profit"] += sale_row["profit"]
        bucket["count"] += 1
        client_bucket = client_map.setdefault(sale_row["client"], {"name": sale_row["client"], "sales": 0.0, "profit": 0.0, "count": 0})
        client_bucket["sales"] += sale_row["sale_total"]
        client_bucket["profit"] += sale_row["profit"]
        client_bucket["count"] += 1

    trend_rows = [trend_map[key] for key in sorted(trend_map)]
    max_trend_value = max([max(row["sales"], row["costs"]) for row in trend_rows] or [1.0])
    for row in trend_rows:
        row["sales_pct"] = max(2.0, row["sales"] / max_trend_value * 100) if row["sales"] else 0.0
        row["costs_pct"] = max(2.0, row["costs"] / max_trend_value * 100) if row["costs"] else 0.0
    top_clients = sorted(client_map.values(), key=lambda row: row["sales"], reverse=True)[:6]
    recent_sales = sorted(sales, key=lambda row: row["date"], reverse=True)[:6]

    return templates.TemplateResponse(
        request,
        "cadastros/financeiro.html",
        context(
            request,
            user=user,
            users=_users_for_filters(db, user),
            active_tab=active_tab,
            sales=sales,
            cash_rows=cash_rows,
            payment_rows=payment_rows,
            totals=totals,
            trend_rows=trend_rows,
            top_clients=top_clients,
            recent_sales=recent_sales,
            filters={"q": q, "user_id": str(user_filter or ""), "from": date_from.isoformat(), "to": date_to.isoformat()},
        ),
    )


@router.post("/cotacoes/nova")
async def nova_cotacao_manual(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/cadastros/cotacoes", status_code=303)
    title = str(form.get("title") or "Nova cotação manual").strip() or "Nova cotação manual"
    group = QuoteGroup(user_id=user.id, company_id=user.company_id, assigned_user_id=user.id, quote_name=title, passengers=1, babies=0, bags=0, status="aberta")
    db.add(group)
    db.flush()
    db.add(QuoteGroupTripDetail(group_id=group.id, travel_type="round_trip", client_name=str(form.get("client_name") or "").strip() or None))
    item = AcceptedQuote(group_id=group.id, user_id=user.id, company_id=user.company_id, status="aguardando")
    db.add(item)
    db.flush()
    data = _seed_payload(group, None)
    data["title"] = title
    data["client_name"] = str(form.get("client_name") or "").strip()
    data["quote_code"] = f"m{group.id:04d}"
    _set_payload(item, data)
    _message, payload = record_quote_activity(
        db, user, group, f"Cotação {group.quote_name} criada por {user.name}.", event="quote_created"
    )
    db.commit()
    await publish_quote_activity(user.company_id, payload)
    flash(request, "Cotação manual criada. Preencha só o que quiser e salve para continuar depois.", "success")
    return RedirectResponse(f"/cadastros/cotacoes/{group.id}", status_code=303)


@router.post("/selecionar/cotacoes-aceitas")
async def selecionar_cotacoes_aceitas(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/calculations/history", status_code=303)
    groups = _selected_groups_from_form(db, user, form)
    if not groups:
        flash(request, "Selecione ao menos uma cotação no histórico.", "error")
        return RedirectResponse("/calculations/history", status_code=303)
    added = _mark_accepted(db, user, groups)
    db.commit()
    flash(request, f"{len(groups)} cotação(ões) selecionada(s). {added} nova(s) enviada(s) para Cotações.", "success")
    return RedirectResponse("/cadastros/cotacoes", status_code=303)


@router.post("/selecionar/voos")
async def selecionar_voos(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/calculations/history", status_code=303)
    groups = _selected_groups_from_form(db, user, form)
    if not groups:
        flash(request, "Selecione ao menos uma cotação no histórico.", "error")
        return RedirectResponse("/calculations/history", status_code=303)
    added = _mark_flight(db, user, groups)
    db.commit()
    flash(request, f"{len(groups)} cotação(ões) selecionada(s). {added} nova(s) enviada(s) para Voos.", "success")
    return RedirectResponse("/cadastros/voos", status_code=303)


@router.post("/cotacoes-aceitas/opcao/{quote_id}/add")
async def aceitar_opcao(quote_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/calculations/history", status_code=303)
    quote, group = _get_option_group(db, user, quote_id)
    if quote is None or group is None:
        flash(request, "Opção não encontrada.", "error")
        return RedirectResponse("/calculations/history", status_code=303)
    _ensure_accepted(db, user, group, quote)
    _message, payload = record_quote_activity(db, user, group, f"Cotação {group.quote_name} transferida para Cotações aceitas por {user.name}.", event="quote_transferred_accepted")
    db.commit()
    await publish_quote_activity(user.company_id, payload)
    flash(request, "Cotação transferida com sucesso para Cotações aceitas. Todos os trechos, datas e horários foram mantidos.", "success")
    return RedirectResponse(f"/cadastros/cotacoes/{group.id}", status_code=303)


@router.post("/voos/opcao/{quote_id}/add")
async def voo_opcao(quote_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/calculations/history", status_code=303)
    quote, group = _get_option_group(db, user, quote_id)
    if quote is None or group is None:
        flash(request, "Opção não encontrada.", "error")
        return RedirectResponse("/calculations/history", status_code=303)
    _ensure_flight(db, user, group, quote)
    _message, payload = record_quote_activity(db, user, group, f"Cotação {group.quote_name} transferida para Voos por {user.name}.", event="quote_transferred_flight")
    db.commit()
    await publish_quote_activity(user.company_id, payload)
    flash(request, "Cotação transferida com sucesso para Voos. Todos os trechos, datas e horários foram mantidos.", "success")
    return RedirectResponse(f"/cadastros/voos/{group.id}/editar", status_code=303)


@router.post("/cotacoes-aceitas/{group_id}/add")
async def adicionar_cotacao_aceita(group_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/calculations/history", status_code=303)
    group = db.get(QuoteGroup, group_id)
    if not _group_allowed(user, group):
        flash(request, "Cotação não encontrada.", "error")
        return RedirectResponse("/calculations/history", status_code=303)
    quote = _first_option_for_group(db, user, group)
    _ensure_accepted(db, user, group, quote)
    _message, payload = record_quote_activity(db, user, group, f"Cotação {group.quote_name} transferida para Cotações aceitas por {user.name}.", event="quote_transferred_accepted")
    db.commit()
    await publish_quote_activity(user.company_id, payload)
    flash(request, "Cotação transferida com sucesso para Cotações aceitas.", "success")
    return RedirectResponse(f"/cadastros/cotacoes/{group.id}", status_code=303)


@router.post("/voos/{group_id}/add")
async def adicionar_voo(group_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/calculations/history", status_code=303)
    group = db.get(QuoteGroup, group_id)
    if not _group_allowed(user, group):
        flash(request, "Cotação não encontrada.", "error")
        return RedirectResponse("/calculations/history", status_code=303)
    quote = _first_option_for_group(db, user, group)
    _ensure_flight(db, user, group, quote)
    _message, payload = record_quote_activity(db, user, group, f"Cotação {group.quote_name} transferida para Voos por {user.name}.", event="quote_transferred_flight")
    db.commit()
    await publish_quote_activity(user.company_id, payload)
    flash(request, "Cotação transferida com sucesso para Voos.", "success")
    return RedirectResponse(f"/cadastros/voos/{group.id}/editar", status_code=303)


@router.get("/cotacoes/{group_id}")
@router.get("/cotacoes-aceitas/{group_id}/editar")
def editar_cotacao(group_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    item = _current_item(db, user, group_id)
    if item is None or not _group_allowed(user, item.group):
        flash(request, "Cotação não encontrada.", "error")
        return RedirectResponse("/cadastros/cotacoes", status_code=303)
    data = _payload(item)
    changed = False
    if not data:
        data = _seed_payload(item.group, item.quote)
        changed = True
    trip = item.group.trip
    if trip is not None and trip.client_person_id and not data.get("client_person_id"):
        data["client_person_id"] = str(trip.client_person_id)
        if trip.client_person is not None:
            data["client_name"] = trip.client_person.name or data.get("client_name") or ""
        changed = True
    if changed:
        _set_payload(item, data)
        db.commit()
    people = _people_choices(db, user)
    board_statuses = _board_statuses(db, user)
    return templates.TemplateResponse(
        request,
        "cadastros/cotacao_form.html",
        context(
            request,
            user=user,
            item=item,
            group=item.group,
            quote=item.quote,
            data=data,
            statuses=board_statuses,
            people=people,
            payment_methods=PAYMENT_METHODS,
            accounts=ACCOUNTS,
            cost_categories=COST_CATEGORIES,
            sale_categories=SALE_CATEGORIES,
            channels=CHANNELS,
            airline_options=AIRLINE_OPTIONS,
            airline_logo_map=_airline_logo_map(db, user),
            airport_map=BR_AIRPORTS,
            sale_unlocked=(item.status == SALE_UNLOCK_STATUS or item.status in {"aprovado", "lancada"}),
        ),
    )


@router.post("/cotacoes/{group_id}/status")
async def alterar_status_cotacao(group_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        return JSONResponse({"ok": False, "message": "Sessão expirada."}, status_code=400)
    item = _current_item(db, user, group_id)
    if item is None or not _group_allowed(user, item.group):
        return JSONResponse({"ok": False, "message": "Cotação não encontrada."}, status_code=404)
    status = str(form.get("status") or "").strip()
    if status not in _status_keys(db, user):
        return JSONResponse({"ok": False, "message": "Status inválido."}, status_code=400)
    old_status = item.status
    item.status = status
    status_labels = {key: label for key, label, _color in _board_statuses(db, user)}
    _message, payload = record_quote_activity(
        db, user, item.group,
        f"Cotação {item.group.quote_name} movida de {status_labels.get(old_status, old_status)} para {status_labels.get(status, status)} por {user.name}.",
        event="quote_status_changed",
    )
    db.commit()
    await publish_quote_activity(user.company_id, payload)
    return JSONResponse({"ok": True, "status": status})


@router.post("/cotacoes/statuses/new")
async def criar_status_cotacao(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/cadastros/cotacoes", status_code=303)
    label = " ".join(str(form.get("label") or "").strip().split())
    color = str(form.get("color") or "#8d8d8d").strip() or "#8d8d8d"
    if not label:
        flash(request, "Informe o nome da nova área.", "error")
        return RedirectResponse("/cadastros/cotacoes", status_code=303)
    base_key = _slugify_status(label)
    existing_keys = _status_keys(db, user)
    key = base_key
    i = 2
    while key in existing_keys:
        key = f"{base_key}_{i}"
        i += 1
    current_count = db.scalar(select(func.count(QuoteBoardStatus.id)).where(_status_scope_filter(user))) or 0
    row = QuoteBoardStatus(
        company_id=user.company_id,
        user_id=None if user.company_id else user.id,
        key=key,
        label=label,
        color=color if color.startswith("#") else "#8d8d8d",
        position=100 + int(current_count),
        active=True,
    )
    db.add(row)
    db.commit()
    flash(request, f"Área '{label}' criada no quadro de cotações.", "success")
    return RedirectResponse("/cadastros/cotacoes", status_code=303)


@router.post("/cotacoes/{group_id}/salvar")
@router.post("/cotacoes-aceitas/{group_id}/editar")
async def salvar_cotacao(group_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    form = await request.form()
    wants_json = request.headers.get("X-Requested-With") == "fetch" or "application/json" in request.headers.get("accept", "")

    def save_error(message: str, status_code: int = 400):
        if wants_json:
            db.rollback()
            return JSONResponse({"ok": False, "message": message}, status_code=status_code)
        flash(request, message, "error")
        return RedirectResponse(f"/cadastros/cotacoes/{group_id}", status_code=303)

    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        return save_error("Sessão expirada. Recarregue a página e tente novamente.", 400)
    item = _current_item(db, user, group_id)
    if item is None or not _group_allowed(user, item.group):
        return save_error("Cotação não encontrada.", 404)

    status = str(form.get("status") or item.status or "aguardando").strip()
    if status in _status_keys(db, user):
        item.status = status

    data = _payload(item)
    data.update({
        "quote_code": str(form.get("quote_code") or data.get("quote_code") or f"q{group_id:04d}").strip(),
        "title": str(form.get("title") or "").strip(),
        "client_person_id": str(form.get("client_person_id") or "").strip() or None,
        "client_name": str(form.get("client_name") or "").strip(),
        "channel": str(form.get("channel") or "").strip(),
        "affiliate": str(form.get("affiliate") or "").strip(),
        "user_name": str(form.get("user_name") or "").strip(),
        "adults": int(form.get("adults") or 0),
        "children": int(form.get("children") or 0),
        "babies": int(form.get("babies") or 0),
        "terms": str(form.get("terms") or "").strip(),
        "notes": str(form.get("notes") or "").strip(),
    })
    for key in ["flights", "passengers", "cost_items", "sale_items"]:
        parsed = _safe_json(str(form.get(f"{key}_json") or "[]"), [])
        data[key] = parsed if isinstance(parsed, list) else []
    services = _safe_json(str(form.get("services_json") or "{}"), {})
    data["services"] = services if isinstance(services, dict) else {}
    commission = _safe_json(str(form.get("commission_json") or "{}"), {})
    data["commission"] = commission if isinstance(commission, dict) else {"receive": [], "pay": [], "extra": 0}
    sale = _safe_json(str(form.get("sale_json") or "{}"), {})
    data["sale"] = sale if isinstance(sale, dict) else {"date": "", "launched": False, "launched_at": "", "notes": ""}

    # Alterações no valor feitas na tela principal aparecem imediatamente no preview.
    current_sale_total = _item_total(data, "sale_items")
    preview_data = data.get("preview") if isinstance(data.get("preview"), dict) else {}
    preview_data["price"] = current_sale_total
    data["preview"] = preview_data

    # Cliente, passageiros e fornecedores precisam existir no cadastro.
    client_name = str(data.get("client_name") or "").strip()
    client_person = _registered_person(
        db,
        user,
        data.get("client_person_id"),
        exact_name=client_name,
        allowed_types={"cliente", "passageiro"},
    ) if client_name else None
    if client_name and client_person is None:
        return save_error("Selecione um cliente cadastrado na lista. Se ele não existir, faça o cadastro primeiro.")
    if client_person is not None:
        data["client_person_id"] = str(client_person.id)
        data["client_name"] = client_person.name
    else:
        data["client_person_id"] = None
        data["client_name"] = ""

    fixed_passengers: list[dict[str, Any]] = []
    for pax in data.get("passengers", []) or []:
        if not isinstance(pax, dict):
            continue
        person = _registered_person(
            db,
            user,
            pax.get("person_id"),
            exact_name=str(pax.get("name") or "").strip(),
            allowed_types={"passageiro", "cliente"},
        )
        if person is None:
            return save_error("Há passageiro sem cadastro válido. Selecione cada passageiro na lista antes de salvar.")
        fixed_passengers.append({
            **pax,
            "person_id": str(person.id),
            "name": person.name,
            "birth_date": person.birth_date or "",
            "cpf": person.cpf_cnpj or "",
            "rg": person.rg or "",
            "passport": person.passport or "",
            "phone": person.mobile or person.phone or "",
            "email": person.email or "",
            "pending": not person.is_complete,
        })
    data["passengers"] = fixed_passengers

    supplier_error: list[str] = []
    def normalize_supplier(entry: dict[str, Any], *, label: str, allowed_types: set[str]) -> bool:
        supplier_name = str(entry.get("supplier") or "").strip()
        if not supplier_name:
            entry["supplier"] = ""
            entry["supplier_person_id"] = None
            return True
        person = _registered_person(
            db,
            user,
            entry.get("supplier_person_id"),
            exact_name=supplier_name,
            allowed_types=allowed_types,
        )
        if person is None:
            supplier_error[:] = [f"Selecione {label} cadastrado na lista antes de salvar."]
            return False
        entry["supplier"] = person.name
        entry["supplier_person_id"] = str(person.id)
        return True

    for cost in data.get("cost_items", []) or []:
        if isinstance(cost, dict) and not normalize_supplier(cost, label="o fornecedor do custo", allowed_types={"fornecedor"}):
            return save_error(supplier_error[0] if supplier_error else "Fornecedor inválido.")

    commission_data = data.get("commission") if isinstance(data.get("commission"), dict) else {}
    for commission_type in ("receive", "pay"):
        for row in commission_data.get(commission_type, []) or []:
            if isinstance(row, dict) and not normalize_supplier(row, label="o fornecedor ou beneficiário da comissão", allowed_types={"fornecedor", "representante"}):
                return save_error(supplier_error[0] if supplier_error else "Fornecedor ou beneficiário inválido.")

    services_data = data.get("services") if isinstance(data.get("services"), dict) else {}
    for service_key, rows in services_data.items():
        if not isinstance(rows, list):
            continue
        for service in rows:
            if not isinstance(service, dict):
                continue
            if not normalize_supplier(service, label="o fornecedor do serviço", allowed_types={"fornecedor"}):
                return save_error(supplier_error[0] if supplier_error else "Fornecedor do serviço inválido.")
            if not _iata_value_valid(service.get("origin")) or not _iata_value_valid(service.get("destination")):
                return save_error("Há um serviço com origem ou destino inválido. Digite um código IATA de exatamente 3 letras.")
            service["origin"] = _iata_code(service.get("origin"))
            service["destination"] = _iata_code(service.get("destination"))

    # Garante link de check-in sugerido pela companhia e datas separadas.
    for fl in data.get("flights", []) or []:
        if not isinstance(fl, dict):
            continue
        if not _iata_value_valid(fl.get("origin")) or not _iata_value_valid(fl.get("destination")):
            return save_error("Há um voo com origem ou destino inválido. Digite um código IATA de exatamente 3 letras.")
        fl["origin"] = _iata_code(fl.get("origin"))
        fl["destination"] = _iata_code(fl.get("destination"))
        for stop in fl.get("stops", []) or []:
            if isinstance(stop, dict):
                if not _iata_value_valid(stop.get("origin")) or not _iata_value_valid(stop.get("destination")):
                    return save_error("Há uma parada com origem ou destino inválido. Digite um código IATA de exatamente 3 letras.")
                stop["origin"] = _iata_code(stop.get("origin"))
                stop["destination"] = _iata_code(stop.get("destination"))
        if fl.get("departure_date") and not fl.get("date"):
            fl["date"] = fl.get("departure_date")
        if fl.get("date") and not fl.get("departure_date"):
            fl["departure_date"] = fl.get("date")
        if not fl.get("arrival_date"):
            fl["arrival_date"] = fl.get("departure_date") or fl.get("date") or ""

        # A duração também é recalculada no backend antes de gravar no Neon.
        # Assim, mesmo que o JavaScript não rode por algum motivo, o banco recebe o valor correto.
        dep_date = str(fl.get("departure_date") or fl.get("date") or "").strip()
        arr_date = str(fl.get("arrival_date") or dep_date).strip()
        dep_time = str(fl.get("departure_time") or "").strip()[:5]
        arr_time = str(fl.get("arrival_time") or "").strip()[:5]
        if dep_date and arr_date and dep_time and arr_time:
            try:
                start_dt = datetime.fromisoformat(f"{dep_date}T{dep_time}:00")
                end_dt = datetime.fromisoformat(f"{arr_date}T{arr_time}:00")
                if end_dt < start_dt and arr_date == dep_date:
                    end_dt += timedelta(days=1)
                    fl["arrival_date"] = end_dt.date().isoformat()
                total_minutes = int((end_dt - start_dt).total_seconds() // 60)
                if total_minutes >= 0:
                    fl["duration"] = f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"
            except ValueError:
                pass

        if not fl.get("checkin_link"):
            fl["checkin_link"] = _checkin_link_for_airline(fl.get("airline"), fl.get("locator"), fl.get("purchase_number"))

    # Atualiza resumo principal para busca e histórico.
    item.group.quote_name = data.get("title") or data.get("client_name") or item.group.quote_name or "Cotação"
    item.group.passengers = max(0, int(data.get("adults") or 0) + int(data.get("children") or 0)) or item.group.passengers
    item.group.babies = max(0, int(data.get("babies") or 0))
    if item.group.trip:
        item.group.trip.client_person_id = client_person.id if client_person is not None else None
        item.group.trip.client_name = client_person.name if client_person is not None else None
        item.group.trip.client_email = client_person.email if client_person is not None else None
        item.group.trip.client_phone = (client_person.mobile or client_person.phone) if client_person is not None else None
        flights = data.get("flights") or []
        if flights:
            item.group.origin = flights[0].get("origin") or item.group.origin
            item.group.destination = flights[0].get("destination") or item.group.destination
            item.group.trip.departure_date = flights[0].get("departure_date") or flights[0].get("date") or item.group.trip.departure_date
    _apply_quote_from_payload(item, data)
    _set_payload(item, data)
    _sync_flight_registry(db, user, item, data)
    db.commit()
    # Em Vercel + Neon, só informamos sucesso ao front-end depois do COMMIT concluir.
    if wants_json:
        return JSONResponse({"ok": True, "group_id": group_id, "status": item.status})
    flash(request, "Cotação salva. Ela pode continuar em edição até você lançar a venda.", "success")
    if form.get("save_close"):
        return RedirectResponse("/cadastros/cotacoes", status_code=303)
    return RedirectResponse(f"/cadastros/cotacoes/{group_id}", status_code=303)


@router.post("/cotacoes/{group_id}/lancar-venda")
async def lancar_venda(group_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse(f"/cadastros/cotacoes/{group_id}", status_code=303)
    item = _current_item(db, user, group_id)
    if item is None or not _group_allowed(user, item.group):
        flash(request, "Cotação não encontrada.", "error")
        return RedirectResponse("/cadastros/cotacoes", status_code=303)
    if item.status not in {"venda_cadastrada", "aprovado", "lancada"}:
        flash(request, "Mova a cotação para Venda cadastrada antes de lançar a venda.", "error")
        return RedirectResponse(f"/cadastros/cotacoes/{group_id}", status_code=303)
    data = _payload(item)
    data.setdefault("sale", {})
    data["sale"]["launched"] = True
    data["sale"]["launched_at"] = datetime.utcnow().isoformat()
    data["sale"]["date"] = str(form.get("sale_date") or data["sale"].get("date") or date.today().isoformat())
    item.status = "lancada"
    _set_payload(item, data)
    db.commit()
    flash(request, "Venda lançada. Agora ela entra nos controles financeiros da reserva.", "success")
    return RedirectResponse(f"/cadastros/cotacoes/{group_id}", status_code=303)



@router.post("/cotacoes/{group_id}/anexos/upload")
async def upload_cotacao_anexos(group_id: int, request: Request, db: Session = Depends(get_db)):
    """Anexa documentos e imagens sem alterar a estrutura do banco."""
    user = require_user(request, db)
    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        return JSONResponse({"ok": False, "message": "Sessão expirada."}, status_code=403)
    item = _current_item(db, user, group_id)
    if item is None or not _group_allowed(user, item.group):
        return JSONResponse({"ok": False, "message": "Cotação não encontrada."}, status_code=404)

    uploads = [f for f in form.getlist("files") if getattr(f, "filename", None)]
    if not uploads:
        return JSONResponse({"ok": False, "message": "Selecione pelo menos um arquivo."}, status_code=400)
    if len(uploads) > 20:
        return JSONResponse({"ok": False, "message": "Envie no máximo 20 arquivos por vez."}, status_code=400)

    data = _payload(item)
    attachments = data.get("attachments") if isinstance(data.get("attachments"), list) else []
    try:
        for upload in uploads:
            saved = await save_quote_attachment(upload, UPLOAD_DIR / "quotes" / str(group_id))
            if saved:
                saved["uploaded_at"] = datetime.utcnow().isoformat()
                saved["uploaded_by"] = user.name
                attachments.append(saved)
    except ValueError as exc:
        return JSONResponse({"ok": False, "message": str(exc)}, status_code=400)

    data["attachments"] = attachments[-250:]
    _set_payload(item, data)
    db.commit()
    return JSONResponse({"ok": True, "attachments": data["attachments"]})


@router.post("/cotacoes/{group_id}/anexos/{attachment_id}/delete")
async def delete_cotacao_anexo(group_id: int, attachment_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        return JSONResponse({"ok": False, "message": "Sessão expirada."}, status_code=403)
    item = _current_item(db, user, group_id)
    if item is None or not _group_allowed(user, item.group):
        return JSONResponse({"ok": False, "message": "Cotação não encontrada."}, status_code=404)

    data = _payload(item)
    old = data.get("attachments") if isinstance(data.get("attachments"), list) else []
    kept = []
    removed = None
    for entry in old:
        if isinstance(entry, dict) and str(entry.get("id") or "") == str(attachment_id):
            removed = entry
        else:
            kept.append(entry)
    if removed:
        delete_relative_upload(str(removed.get("path") or ""))
    data["attachments"] = kept
    _set_payload(item, data)
    db.commit()
    return JSONResponse({"ok": True, "attachments": kept})


@router.get("/cotacoes/{group_id}/preview/data")
def dados_preview_reserva(group_id: int, request: Request, db: Session = Depends(get_db)):
    """Fonte leve para o preview refletir alterações salvas em outras telas."""
    user = require_user(request, db)
    item = _current_item(db, user, group_id)
    if item is None or not _group_allowed(user, item.group):
        return JSONResponse({"ok": False, "message": "Cotação não encontrada."}, status_code=404)
    data = dict(_payload(item))
    sale_rows = data.get("sale_items") if isinstance(data.get("sale_items"), list) else []
    data["current_sale_value"] = _item_total(data, "sale_items") if sale_rows else float(item.sale_value or 0)
    return JSONResponse({"ok": True, "data": data})


@router.post("/cotacoes/{group_id}/preview/save")
async def salvar_preview_reserva(group_id: int, request: Request, db: Session = Depends(get_db)):
    """Salva somente as opções visuais do preview. Dados comerciais/voos vêm da cotação."""
    user = require_user(request, db)
    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        return JSONResponse({"ok": False, "message": "Sessão expirada."}, status_code=403)
    item = _current_item(db, user, group_id)
    if item is None or not _group_allowed(user, item.group):
        return JSONResponse({"ok": False, "message": "Cotação não encontrada."}, status_code=404)

    data = _payload(item)
    old_preview = data.get("preview") if isinstance(data.get("preview"), dict) else {}
    incoming = _safe_json(str(form.get("preview_json") or "{}"), {})
    preview = dict(old_preview)

    # Somente preferências de apresentação podem ser alteradas nesta tela.
    allowed = {
        "document_title", "show_logo", "show_passengers", "show_terms",
        "show_notes", "hidden_segments"
    }
    if isinstance(incoming, dict):
        for key in allowed:
            if key in incoming:
                preview[key] = incoming[key]

    upload = form.get("club_image")
    remove_image = str(form.get("remove_club_image") or "") == "1"
    old_image = str(preview.get("club_image_path") or "")
    try:
        if remove_image:
            delete_relative_upload(old_image)
            preview["club_image_path"] = ""
        elif getattr(upload, "filename", None):
            new_image = await save_upload_image(
                upload,
                UPLOAD_DIR / "quotes" / str(group_id) / "preview",
                max_bytes=8 * 1024 * 1024,
                filename_prefix=f"club-{group_id}",
            )
            if new_image:
                if old_image and old_image != new_image:
                    delete_relative_upload(old_image)
                preview["club_image_path"] = new_image
    except ValueError as exc:
        return JSONResponse({"ok": False, "message": str(exc)}, status_code=400)

    data["preview"] = preview
    _set_payload(item, data)
    db.commit()
    club_image_data = file_to_data_uri(preview.get("club_image_path")) if preview.get("club_image_path") else None
    return JSONResponse({"ok": True, "message": "Preview salvo.", "club_image_data": club_image_data})


@router.post("/cotacoes/{group_id}/preview/pdf")
async def baixar_preview_pdf(group_id: int, request: Request, db: Session = Depends(get_db)):
    """Converte exatamente o documento HTML visível no editor para PDF."""
    user = require_user(request, db)
    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        return Response("Sessão expirada.", status_code=403)
    item = _current_item(db, user, group_id)
    if item is None or not _group_allowed(user, item.group):
        return Response("Cotação não encontrada.", status_code=404)
    document_html = str(form.get("document_html") or "")
    if not document_html or len(document_html) > 2_000_000:
        return Response("Prévia inválida ou muito grande.", status_code=400)
    css_path = Path(__file__).resolve().parent.parent / "static" / "css" / "reservation-preview.css"
    css = css_path.read_text(encoding="utf-8") if css_path.exists() else ""
    html = f"<!doctype html><html><head><meta charset='utf-8'><style>{css}</style></head><body class='pdf-export-body'>{document_html}</body></html>"
    try:
        pdf = await _html_to_pdf(html)
    except Exception as exc:
        return Response(f"Não foi possível gerar o PDF: {exc}", status_code=500)
    code = str(_payload(item).get("quote_code") or f"q{group_id:04d}").replace("/", "-")
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="reserva-{code}.pdf"'})


@router.get("/cotacoes/{group_id}/visualizar")
def visualizar_reserva(group_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    item = _current_item(db, user, group_id)
    if item is None or not _group_allowed(user, item.group):
        flash(request, "Cotação não encontrada.", "error")
        return RedirectResponse("/cadastros/cotacoes", status_code=303)
    data = _payload(item)
    data = dict(data)
    sale_rows = data.get("sale_items") if isinstance(data.get("sale_items"), list) else []
    data["current_sale_value"] = _item_total(data, "sale_items") if sale_rows else float(item.sale_value or 0)
    preview_data = dict(data.get("preview") or {}) if isinstance(data.get("preview"), dict) else {}
    preview_data["price"] = data["current_sale_value"]
    data["preview"] = preview_data
    
    company_logo_data = file_to_data_uri(user.company.logo_path) if getattr(user, "company", None) and user.company.logo_path else None
    club_image_data = file_to_data_uri(preview_data.get("club_image_path")) if preview_data.get("club_image_path") else None
    return templates.TemplateResponse(request, "cadastros/cotacao_preview.html", context(request, user=user, item=item, group=item.group, quote=item.quote, data=data, airport_map=BR_AIRPORTS, company_logo_data=company_logo_data, club_image_data=club_image_data, airline_logo_map=_airline_logo_map(db, user)))


@router.post("/cotacoes/{group_id}/remove")
@router.post("/cotacoes-aceitas/{group_id}/remove")
async def remover_cotacao(group_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/cadastros/cotacoes", status_code=303)
    item = db.get(AcceptedQuote, group_id)
    if item and ((user.company_id and item.company_id == user.company_id) or item.user_id == user.id):
        db.delete(item)
        db.commit()
        flash(request, "Cotação removida do quadro. O histórico original não foi apagado.", "success")
    return RedirectResponse("/cadastros/cotacoes", status_code=303)


@router.get("/voos")
@router.get("/voos/")
def voos(request: Request, db: Session = Depends(get_db)):
    """Agenda dos voos pertencentes a cotações aceitas.

    A tela não usa mais registros operacionais soltos como origem da agenda.
    Somente cotações aceitas que possuam ao menos um trecho de voo aparecem.
    Quando existe um ``FlightRegistry`` para a mesma cotação, ele continua
    servindo de apoio para localizador, status e link de check-in.
    """
    user = require_user(request, db)
    qp = request.query_params
    q = (qp.get("q") or "").strip().lower()
    client_filter = (qp.get("client") or "").strip().lower()
    locator_filter = (qp.get("locator") or "").strip().lower()
    status_filter = (qp.get("status") or "").strip().lower()
    user_filter = _parse_int(qp.get("user_id"))
    date_from = _parse_date(qp.get("from"))
    date_to = _parse_date(qp.get("to"))

    accepted_rows = db.scalars(
        select(AcceptedQuote)
        .where(_accepted_filter(user))
        .options(
            selectinload(AcceptedQuote.group).selectinload(QuoteGroup.trip),
            selectinload(AcceptedQuote.group).selectinload(QuoteGroup.user).selectinload(WebUser.profile),
            selectinload(AcceptedQuote.group).selectinload(QuoteGroup.assigned_user).selectinload(WebUser.profile),
            selectinload(AcceptedQuote.quote).selectinload(WebQuote.airline),
            selectinload(AcceptedQuote.user).selectinload(WebUser.profile),
        )
        .order_by(desc(AcceptedQuote.updated_at), desc(AcceptedQuote.selected_at))
        .limit(1200)
    ).all()

    # O registro operacional é somente um complemento para a cotação aceita.
    # Um FlightRegistry sem AcceptedQuote correspondente NÃO aparece na agenda.
    registry_rows = db.scalars(
        select(FlightRegistry)
        .where(_flight_filter(user))
        .options(
            selectinload(FlightRegistry.group).selectinload(QuoteGroup.trip),
            selectinload(FlightRegistry.quote).selectinload(WebQuote.airline),
            selectinload(FlightRegistry.user).selectinload(WebUser.profile),
        )
        .order_by(desc(FlightRegistry.selected_at))
        .limit(1200)
    ).all()
    registry_by_group = {row.group_id: row for row in registry_rows}

    flight_items: list[dict[str, Any]] = []

    def append_item(*, row: Any, group: QuoteGroup, quote: WebQuote | None, trip: QuoteGroupTripDetail | None, fl_data: dict[str, Any], flight_index: int = 0, accepted: AcceptedQuote | None = None) -> None:
        departure = str(fl_data.get("departure_date") or fl_data.get("date") or "").strip()
        kind = str(fl_data.get("kind") or "").strip().lower()
        if not departure and trip is not None:
            departure = str(trip.return_date if kind == "volta" else trip.departure_date or "").strip()
        dep_date = _parse_date(departure)
        display_status = _flight_status(departure)
        client_name = str(
            (accepted and _payload(accepted).get("client_name"))
            or (trip.client_name if trip else "")
            or group.quote_name
            or "Não informado"
        ).strip()
        locator_value = str(
            fl_data.get("locator")
            or (getattr(row, "locator", None) if not isinstance(row, dict) else row.get("locator"))
            or fl_data.get("purchase_number")
            or (accepted.locator if accepted else "")
            or ""
        ).lower()
        airline_name = str(
            fl_data.get("airline")
            or (getattr(row, "airline_name", None) if not isinstance(row, dict) else row.get("airline_name"))
            or (quote.airline.name if quote and quote.airline else "")
            or ""
        )
        flight_number = str(
            fl_data.get("flight_number")
            or (getattr(row, "flight_number", None) if not isinstance(row, dict) else row.get("flight_number"))
            or ""
        )
        maker = (accepted.user if accepted and accepted.user else None) or (getattr(row, "user", None) if not isinstance(row, dict) else row.get("user")) or group.user
        checkin_status = getattr(row, "checkin_status", None) if not isinstance(row, dict) else row.get("checkin_status")
        haystack = " ".join([
            client_name, group.quote_name or "", group.origin or "", group.destination or "",
            str(fl_data.get("origin") or ""), str(fl_data.get("destination") or ""),
            airline_name, flight_number, locator_value, getattr(maker, "name", "") or "",
        ]).lower()
        if q and q not in haystack:
            return
        if client_filter and client_filter not in client_name.lower():
            return
        if locator_filter and locator_filter not in locator_value:
            return
        if status_filter and status_filter not in display_status.lower() and status_filter not in str(checkin_status or fl_data.get("checkin_status") or "").lower():
            return
        maker_id = getattr(maker, "id", None)
        if user_filter and maker_id != user_filter:
            return
        if date_from and dep_date and dep_date < date_from:
            return
        if date_to and dep_date and dep_date > date_to:
            return

        selected_at = (
            getattr(row, "selected_at", None) if not isinstance(row, dict) else row.get("selected_at")
        ) or (accepted.selected_at if accepted else None)
        row_data = {
            "selected_at": selected_at,
            "user": maker,
            "user_id": getattr(maker, "id", None),
            "locator": fl_data.get("locator") or (getattr(row, "locator", None) if not isinstance(row, dict) else row.get("locator")) or (accepted.locator if accepted else None),
            "airline_name": airline_name,
            "flight_number": flight_number,
            "checkin_status": fl_data.get("checkin_status") or checkin_status or "pendente",
            "checkin_link": fl_data.get("checkin_link") or (getattr(row, "checkin_link", None) if not isinstance(row, dict) else row.get("checkin_link")),
        }
        quote_code = f"q{int(group.id):04d}"
        flight_items.append({
            "row": row_data,
            "group": group,
            "quote": quote,
            "trip": trip,
            "flight_data": fl_data,
            "departure_date": departure,
            "return_date": None,
            "status": display_status,
            "sort_date": dep_date or date.max,
            "virtual": True,
            "flight_index": flight_index,
            "client_name": client_name,
            "accepted": accepted,
            "quote_code": quote_code,
            "links": {
                "edit_flight": f"/cadastros/voos/{group.id}/editar?flight_index={int(flight_index or 0)}",
                "edit_quote": f"/cadastros/cotacoes/{group.id}?origem=voos&codigo={quote_code}",
                "preview": f"/cadastros/cotacoes/{group.id}/visualizar?origem=voos&codigo={quote_code}",
            },
        })

    for accepted in accepted_rows:
        group = accepted.group
        if not _group_allowed(user, group):
            continue

        registry = registry_by_group.get(group.id)
        all_accepted_flights = _safe_flight_list(_payload(accepted).get("flights"))
        if any("selected_schedule" in fl for fl in all_accepted_flights):
            accepted_pairs = [(idx, fl) for idx, fl in enumerate(all_accepted_flights) if bool(fl.get("selected_schedule"))]
        else:
            accepted_pairs = list(enumerate(all_accepted_flights))
        registry_data = _safe_json(getattr(registry, "extra_json", "{}"), {}) if registry is not None else {}
        registry_flights = _safe_flight_list(registry_data.get("flights")) if isinstance(registry_data, dict) else []

        # A agenda operacional mostra apenas a opção de horário escolhida de
        # cada trecho. As alternativas continuam salvas na cotação/PDF.
        if accepted_pairs:
            flight_pairs = accepted_pairs
        else:
            flight_pairs = list(enumerate(registry_flights))
        if not flight_pairs:
            continue

        for display_idx, (payload_idx, accepted_fl) in enumerate(flight_pairs):
            fl_data = dict(accepted_fl or {})
            if display_idx < len(registry_flights):
                reg_fl = registry_flights[display_idx]
                for key in ("locator", "purchase_number", "flight_number", "checkin_status", "notification_mode", "checkin_link", "notes"):
                    if not fl_data.get(key) and reg_fl.get(key):
                        fl_data[key] = reg_fl.get(key)
            append_item(
                row=registry or {},
                group=group,
                quote=accepted.quote,
                trip=group.trip,
                fl_data=fl_data,
                flight_index=payload_idx,
                accepted=accepted,
            )

    flight_items.sort(key=lambda item: (item.get("sort_date") or date.max, (item.get("group").quote_name if item.get("group") else "") or "", item.get("flight_index", 0)))
    return templates.TemplateResponse(
        request,
        "cadastros/voos.html",
        context(
            request,
            user=user,
            flight_items=flight_items,
            airport_map=BR_AIRPORTS,
            users=_users_for_filters(db, user),
            filters={
                "q": q, "client": client_filter, "locator": locator_filter, "status": status_filter,
                "user_id": str(user_filter or ""), "from": qp.get("from") or "", "to": qp.get("to") or "",
            },
        ),
    )


@router.get("/voos/{group_id}/editar")
def editar_voo(group_id: int, request: Request, db: Session = Depends(get_db)):
    """Edita um trecho do voo mantendo a rota numérica estável.

    qXXXX é somente o código visual da cotação. O vínculo real continua sendo
    ``group_id`` no banco, evitando as rotas experimentais da V1.5/V1.6.
    """
    user = require_user(request, db)
    flight_index = max(0, int(_parse_int(request.query_params.get("flight_index")) or 0))

    accepted = db.scalar(
        select(AcceptedQuote)
        .where(AcceptedQuote.group_id == group_id, _accepted_filter(user))
        .options(
            selectinload(AcceptedQuote.group).selectinload(QuoteGroup.trip),
            selectinload(AcceptedQuote.quote).selectinload(WebQuote.airline),
            selectinload(AcceptedQuote.quote).selectinload(WebQuote.trip),
        )
    )
    if accepted is None or not _group_allowed(user, accepted.group):
        flash(request, "Cotação aceita não encontrada para este voo.", "error")
        return RedirectResponse("/cadastros/voos", status_code=303)

    item = db.scalar(
        select(FlightRegistry)
        .where(FlightRegistry.group_id == group_id, _flight_filter(user))
        .options(
            selectinload(FlightRegistry.group).selectinload(QuoteGroup.trip),
            selectinload(FlightRegistry.quote).selectinload(WebQuote.airline),
        )
    )
    if item is None:
        item, _created = _ensure_flight(db, user, accepted.group, accepted.quote)
        db.flush()

    payload = _payload(accepted)
    flights = _safe_flight_list(payload.get("flights"))
    registry_json = _safe_json(getattr(item, "extra_json", "{}"), {})
    registry_flights = _safe_flight_list(registry_json.get("flights")) if isinstance(registry_json, dict) else []
    if not flights:
        flights = registry_flights
    flight_data = dict(flights[flight_index]) if 0 <= flight_index < len(flights) else {}

    return templates.TemplateResponse(
        request,
        "cadastros/voo_form.html",
        context(
            request,
            user=user,
            item=item,
            group=accepted.group,
            quote=accepted.quote,
            accepted=accepted,
            quote_code=f"q{group_id:04d}",
            flight_index=flight_index,
            flight_data=flight_data,
        ),
    )


@router.post("/voos/{group_id}/editar")
async def salvar_voo(group_id: int, request: Request, db: Session = Depends(get_db)):
    """Salva o trecho e sincroniza Cotação ↔ Voo sem trocar a arquitetura de rotas."""
    user = require_user(request, db)
    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/cadastros/voos", status_code=303)

    flight_index = max(0, int(_parse_int(str(form.get("flight_index") or "0")) or 0))
    accepted = db.scalar(
        select(AcceptedQuote)
        .where(AcceptedQuote.group_id == group_id, _accepted_filter(user))
        .options(
            selectinload(AcceptedQuote.group).selectinload(QuoteGroup.trip),
            selectinload(AcceptedQuote.quote).selectinload(WebQuote.airline),
            selectinload(AcceptedQuote.quote).selectinload(WebQuote.trip),
        )
    )
    if accepted is None or not _group_allowed(user, accepted.group):
        flash(request, "Cotação aceita não encontrada para este voo.", "error")
        return RedirectResponse("/cadastros/voos", status_code=303)

    item = db.scalar(
        select(FlightRegistry)
        .where(FlightRegistry.group_id == group_id, _flight_filter(user))
        .options(
            selectinload(FlightRegistry.group).selectinload(QuoteGroup.trip),
            selectinload(FlightRegistry.quote).selectinload(WebQuote.trip),
        )
    )
    if item is None:
        item, _created = _ensure_flight(db, user, accepted.group, accepted.quote)

    group = accepted.group
    trip = group.trip or QuoteGroupTripDetail(group_id=group.id)
    if group.trip is None:
        db.add(trip)

    payload = _payload(accepted)
    flights = _safe_flight_list(payload.get("flights"))
    registry_json = _safe_json(getattr(item, "extra_json", "{}"), {})
    registry_flights = _safe_flight_list(registry_json.get("flights")) if isinstance(registry_json, dict) else []
    if not flights and registry_flights:
        flights = [dict(row) for row in registry_flights]
    while len(flights) <= flight_index:
        flights.append({})
    old_selected = dict(flights[flight_index] or {})

    origin = _iata_code(form.get("origin") or old_selected.get("origin") or group.origin)
    destination = _iata_code(form.get("destination") or old_selected.get("destination") or group.destination)
    if not _iata_value_valid(origin) or not _iata_value_valid(destination) or origin == destination:
        flash(request, "Informe origem e destino com códigos IATA válidos e diferentes.", "error")
        return RedirectResponse(f"/cadastros/voos/{group_id}/editar?flight_index={flight_index}", status_code=303)

    departure_date = str(form.get("departure_date") or old_selected.get("departure_date") or old_selected.get("date") or "").strip()[:20]
    arrival_date = str(form.get("arrival_date") or old_selected.get("arrival_date") or departure_date or "").strip()[:20]
    locator = str(form.get("locator") or old_selected.get("locator") or item.locator or "").strip().upper()
    flight_number = str(form.get("flight_number") or old_selected.get("flight_number") or item.flight_number or "").strip().upper()
    airline_name = str(form.get("airline_name") or old_selected.get("airline") or item.airline_name or "").strip()
    departure_time = str(form.get("departure_time") or old_selected.get("departure_time") or item.departure_time or "").strip()
    arrival_time = str(form.get("arrival_time") or old_selected.get("arrival_time") or item.arrival_time or "").strip()
    checkin_status = str(form.get("checkin_status") or old_selected.get("checkin_status") or item.checkin_status or "pendente").strip() or "pendente"
    notification_mode = str(form.get("notification_mode") or old_selected.get("notification_mode") or item.notification_mode or "").strip()
    notes = str(form.get("notes") or old_selected.get("notes") or item.notes or "").strip()
    checkin_link = str(form.get("checkin_link") or old_selected.get("checkin_link") or item.checkin_link or "").strip()
    if not checkin_link:
        checkin_link = _checkin_link_for_airline(airline_name, locator, old_selected.get("purchase_number")) or ""

    current = dict(old_selected)
    current.update({
        "origin": origin,
        "destination": destination,
        "departure_date": departure_date,
        "date": departure_date,
        "arrival_date": arrival_date,
        "locator": locator,
        "flight_number": flight_number,
        "airline": airline_name,
        "departure_time": departure_time,
        "arrival_time": arrival_time,
        "checkin_status": checkin_status,
        "notification_mode": notification_mode,
        "checkin_link": checkin_link,
        "notes": notes,
    })
    flights[flight_index] = current
    payload["quote_code"] = f"q{group_id:04d}"
    payload["flights"] = flights
    _apply_quote_from_payload(accepted, payload)
    _set_payload(accepted, payload)

    # O resumo da cotação acompanha o primeiro e o último trecho.
    first = flights[0] if flights else current
    last = flights[-1] if flights else current
    group.origin = _iata_code(first.get("origin") or group.origin) or group.origin
    group.destination = _iata_code(last.get("destination") or group.destination) or group.destination
    group.updated_at = datetime.utcnow()
    trip.departure_date = str(first.get("departure_date") or first.get("date") or trip.departure_date or "").strip() or None
    trip.return_date = (str(last.get("departure_date") or last.get("date") or "").strip() or None) if len(flights) > 1 else trip.return_date

    if accepted.quote is not None:
        accepted.quote.origin = group.origin
        accepted.quote.destination = group.destination
        if accepted.quote.trip is not None:
            accepted.quote.trip.departure_date = trip.departure_date
            accepted.quote.trip.return_date = trip.return_date

    # O registro operacional recebe a mesma lista de trechos.
    item.quote_id = accepted.quote_id
    item.checkin_status = checkin_status
    item.notification_mode = notification_mode or None
    item.locator = locator or None
    item.flight_number = flight_number or None
    item.airline_name = airline_name or None
    item.departure_time = departure_time or None
    item.arrival_time = arrival_time or None
    item.checkin_link = checkin_link or None
    item.notes = notes or None
    item.extra_json = json.dumps({"quote_code": f"q{group_id:04d}", "flights": flights}, ensure_ascii=False)

    activity_text = f"Voo da cotação q{group_id:04d} atualizado: trecho {flight_index + 1}."
    _message, event_payload = record_quote_activity(
        db, user, group, activity_text, event="quote_flight_updated", send_to_chat=False
    )
    db.commit()
    await publish_quote_activity(user.company_id, event_payload)
    flash(request, f"Voo q{group_id:04d} salvo. A cotação vinculada foi atualizada também.", "success")
    return RedirectResponse("/cadastros/voos", status_code=303)


@router.post("/voos/{group_id}/remove")
async def remover_voo(group_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/cadastros/voos", status_code=303)
    item = db.get(FlightRegistry, group_id)
    if item and ((user.company_id and item.company_id == user.company_id) or item.user_id == user.id):
        db.delete(item)
        db.commit()
        flash(request, "Voo removido da lista operacional.", "success")
    return RedirectResponse("/cadastros/voos", status_code=303)
