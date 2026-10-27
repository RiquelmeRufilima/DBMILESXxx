"""Reservas aéreas pelo localizador: salvar, sincronizar e listar."""
from __future__ import annotations

import json
import logging
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ...models import AirlineReservation, WebUser
from ..airline_logos import AirlineLogoResolver
from .airlines import airline_catalog, clean_inputs, get_airline
from .providers import ReservationQuery, ReservationResult, provider_for, providers_status

logger = logging.getLogger(__name__)
_SCHEMA_READY = False

STATUS_LABELS = {
    "pendente": "Aguardando sincronização",
    "sincronizada": "Confirmada",
    "nao_encontrada": "Não encontrada",
    "erro": "Erro na busca",
}

__all__ = [
    "STATUS_LABELS", "airline_catalog", "create_reservation", "ensure_reservation_schema",
    "list_reservations", "providers_status", "reservation_scope", "sync_reservation",
    "find_or_create_reservation", "quote_flights_from_reservation", "get_airline",
]


def ensure_reservation_schema(db: Session) -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    try:
        AirlineReservation.__table__.create(bind=db.get_bind(), checkfirst=True)
    except Exception as exc:  # pragma: no cover
        logger.warning("Tabela de reservas não pôde ser criada agora: %s", exc)
    _SCHEMA_READY = True


def reservation_scope(user: WebUser):
    if user.company_id:
        return AirlineReservation.company_id == user.company_id
    return (AirlineReservation.company_id.is_(None)) & (AirlineReservation.user_id == user.id)


def _loads(value: str | None) -> list:
    try:
        data = json.loads(value or "[]")
        return data if isinstance(data, list) else []
    except (TypeError, ValueError):
        return []


async def sync_reservation(db: Session, reservation: AirlineReservation) -> ReservationResult:
    """Consulta o conector da companhia e grava o resultado. Não faz commit."""
    provider = provider_for(reservation.airline_slug)
    query = ReservationQuery(
        airline_slug=reservation.airline_slug,
        airline_name=reservation.airline_name,
        locator=reservation.locator or "",
        purchase_number=reservation.purchase_number or "",
        last_name=reservation.last_name or "",
        origin=reservation.origin or "",
    )
    try:
        result = await provider.lookup(query)
    except Exception as exc:  # conector nunca derruba a tela
        logger.exception("Falha no conector %s: %s", provider.name, exc)
        result = ReservationResult(status="error", message="O serviço da companhia não respondeu. Tente novamente mais tarde.")

    reservation.provider = provider.name
    reservation.last_sync_at = datetime.utcnow()
    reservation.last_message = (result.message or "")[:300] or None
    if result.status == "found":
        reservation.status = "sincronizada"
        reservation.booking_status = (result.booking_status or "Confirmado")[:40]
        reservation.passengers_json = json.dumps(result.passengers or [], ensure_ascii=False)
        locator = reservation.locator or ""
        flights = []
        for item in result.flights or []:
            item = dict(item)
            item.setdefault("airline", reservation.airline_name)
            item.setdefault("locator", locator)
            flights.append(item)
        reservation.flights_json = json.dumps(flights, ensure_ascii=False)
        if result.total_value is not None:
            reservation.total_value = float(result.total_value)
            reservation.currency = (result.currency or "BRL")[:3]
    elif result.status == "not_found":
        reservation.status = "nao_encontrada"
    elif result.status == "error":
        reservation.status = "erro"
    else:
        reservation.status = "pendente"
    return result


async def create_reservation(db: Session, user: WebUser, data: dict) -> tuple[AirlineReservation | None, str, ReservationResult | None]:
    """Valida, impede duplicidade, salva e tenta sincronizar. Não faz commit."""
    ensure_reservation_schema(db)
    airline = get_airline(data.get("airline"))
    if airline is None:
        return None, "Escolha a companhia da reserva.", None
    values, error = clean_inputs(airline, data)
    if error:
        return None, error, None

    code = values.get("locator") or values.get("purchase_number")
    duplicate = db.scalar(
        select(AirlineReservation.id).where(
            reservation_scope(user),
            AirlineReservation.airline_slug == airline["slug"],
            or_(AirlineReservation.locator == code, AirlineReservation.purchase_number == code),
        ).limit(1)
    )
    if duplicate:
        return None, f"A reserva {code} da {airline['name']} já foi adicionada.", None

    reservation = AirlineReservation(
        company_id=user.company_id or None,
        user_id=user.id,
        airline_slug=airline["slug"],
        airline_name=airline["name"],
        locator=values.get("locator"),
        purchase_number=values.get("purchase_number"),
        last_name=values.get("last_name") or values.get("full_last_name"),
        origin=values.get("origin"),
        notify_changes=str(data.get("notify", "1")).lower() in {"1", "true", "on", "yes", "sim"},
        status="pendente",
        description=str(data.get("description") or "").strip()[:300] or None,
    )
    db.add(reservation)
    db.flush()
    result = await sync_reservation(db, reservation)
    return reservation, "", result


def list_reservations(db: Session, user: WebUser, *, q: str = "", status: str = "", limit: int = 300) -> list[dict]:
    """Reservas da empresa prontas para a tela (logo, ida/volta, passageiros)."""
    ensure_reservation_schema(db)
    conditions = [reservation_scope(user)]
    if status in STATUS_LABELS:
        conditions.append(AirlineReservation.status == status)
    if q:
        pattern = f"%{q.strip()}%"
        conditions.append(or_(
            AirlineReservation.locator.ilike(pattern),
            AirlineReservation.purchase_number.ilike(pattern),
            AirlineReservation.last_name.ilike(pattern),
            AirlineReservation.airline_name.ilike(pattern),
            AirlineReservation.description.ilike(pattern),
            AirlineReservation.passengers_json.ilike(pattern),
        ))
    rows = db.scalars(
        select(AirlineReservation).where(*conditions).order_by(AirlineReservation.created_at.desc()).limit(limit)
    ).all()
    logos = AirlineLogoResolver([])
    catalog = {item["slug"]: item for item in airline_catalog()}
    items = []
    for row in rows:
        flights = _loads(row.flights_json)
        passengers = _loads(row.passengers_json)
        outbound = next((f for f in flights if str(f.get("kind") or "").lower() != "volta"), None)
        inbound = next((f for f in flights if str(f.get("kind") or "").lower() == "volta"), None)
        items.append({
            "row": row,
            "code": row.locator or row.purchase_number or "—",
            "airline": logos.resolve(row.airline_name),
            "manage_url": catalog.get(row.airline_slug, {}).get("manage_url", ""),
            "status_label": STATUS_LABELS.get(row.status, row.status),
            "passengers": passengers,
            "passenger_label": (passengers[0].get("name") if passengers else (row.last_name or "—")),
            "extra_passengers": max(0, len(passengers) - 1),
            "outbound": outbound,
            "inbound": inbound,
        })
    return items


async def find_or_create_reservation(db: Session, user: WebUser, data: dict) -> tuple[AirlineReservation | None, str, ReservationResult | None]:
    """Usado pelo botão da cotação: se a reserva já existe, sincroniza de novo."""
    ensure_reservation_schema(db)
    airline = get_airline(data.get("airline"))
    if airline is None:
        return None, "Escolha a companhia da reserva.", None
    values, error = clean_inputs(airline, data)
    if error:
        return None, error, None
    code = values.get("locator") or values.get("purchase_number")
    existing = db.scalar(
        select(AirlineReservation).where(
            reservation_scope(user),
            AirlineReservation.airline_slug == airline["slug"],
            or_(AirlineReservation.locator == code, AirlineReservation.purchase_number == code),
        ).limit(1)
    )
    if existing is not None:
        result = await sync_reservation(db, existing)
        return existing, "", result
    return await create_reservation(db, user, data)


def quote_flights_from_reservation(reservation: AirlineReservation, *, notify: bool = True, checkin_link: str = "") -> list[dict]:
    """Converte os voos da reserva para o formato de voo da cotação (Orçamento)."""
    flights = []
    for item in _loads(reservation.flights_json):
        dep = item.get("departure_date") or item.get("date") or ""
        kind = str(item.get("kind") or "ida").lower()
        flights.append({
            "kind": kind if kind in {"ida", "volta", "interno"} else "ida",
            "label": item.get("label") or ("Voo de Volta" if kind == "volta" else "Voo de Ida"),
            "segment_key": "return" if kind == "volta" else "outbound",
            "airline": item.get("airline") or reservation.airline_name,
            "flight_number": str(item.get("flight_number") or "").upper(),
            "origin": str(item.get("origin") or "").upper(),
            "destination": str(item.get("destination") or "").upper(),
            "date": dep, "departure_date": dep,
            "departure_time": item.get("departure_time") or "",
            "arrival_date": item.get("arrival_date") or dep,
            "arrival_time": item.get("arrival_time") or "",
            "locator": reservation.locator or "",
            "purchase_number": reservation.purchase_number or "",
            "class": item.get("class") or "Econômica",
            "connections": item.get("connections") or "Direto",
            "checkin_status": "pendente",
            "checkin_link": checkin_link,
            "selected_schedule": True, "schedule_option_number": 1,
            "bags_personal": 1, "bags_carry": 1, "bags_checked": 0,
            "stops": [],
            "notify_changes": notify,
            "source": "localizador",
            "reservation_id": reservation.id,
        })
    return flights
