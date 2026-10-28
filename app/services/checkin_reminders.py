"""Lembretes periódicos de abertura do check-in para voos aceitos."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..models import AcceptedQuote, CheckinReminder, FlightRegistry, QuoteGroup, WebUser
from .notifications import create_notification
from .push import send_push

logger = logging.getLogger(__name__)
BRAZIL_TZ = ZoneInfo("America/Sao_Paulo")


def _json_dict(value: str | None) -> dict:
    try:
        result = json.loads(value or "{}")
        return result if isinstance(result, dict) else {}
    except (ValueError, TypeError):
        return {}


def _flights(value: object) -> list[dict]:
    if isinstance(value, dict):
        value = [value]
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _departure(flight: dict, fallback_date: str | None, fallback_time: str | None) -> datetime | None:
    date = str(flight.get("departure_date") or flight.get("date") or fallback_date or "").strip()[:10]
    clock = str(flight.get("departure_time") or fallback_time or "00:00").strip()[:5]
    for fmt in ("%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(f"{date} {clock}", fmt).replace(tzinfo=BRAZIL_TZ)
        except ValueError:
            pass
    return None


def _hours_window(mode: str) -> int:
    value = mode.strip().lower()
    if any(v in value for v in ("desativ", "nenhum", "nunca", "não notificar", "nao notificar", "sem notific")):
        return 0
    if "24h" in value or "24_h" in value:
        return 24
    return 48


def process_checkin_reminders(db: Session, now: datetime | None = None) -> dict:
    """Processa em lotes, deduplica em banco e envia Push aos responsáveis.

    O horário do voo é tratado como horário de Brasília se nenhum fuso está
    salvo; companhias podem abrir check-in em horários diferentes.
    """
    now = now or datetime.now(BRAZIL_TZ)
    if now.tzinfo is None:
        now = now.replace(tzinfo=BRAZIL_TZ)
    cursor = 0
    scanned = 0
    created = 0
    delivered = 0
    while True:
        quotes = db.scalars(
            select(AcceptedQuote)
            .where(AcceptedQuote.group_id > cursor)
            .options(selectinload(AcceptedQuote.group).selectinload(QuoteGroup.trip))
            .order_by(AcceptedQuote.group_id)
            .limit(150)
        ).all()
        if not quotes:
            break
        cursor = quotes[-1].group_id
        scanned += len(quotes)
        registries = {r.group_id: r for r in db.scalars(
            select(FlightRegistry).where(FlightRegistry.group_id.in_([q.group_id for q in quotes]))
        ).all()}
        for quote in quotes:
            if not quote.group or str(quote.status or '').lower() in {'cancelada', 'cancelado', 'rejeitada', 'excluida', 'excluída'}:
                continue
            payload = _json_dict(quote.extra_json)
            registry = registries.get(quote.group_id)
            registry_flights = _flights(_json_dict(registry.extra_json).get("flights")) if registry else []
            flights = _flights(payload.get("flights")) or registry_flights
            if any("selected_schedule" in f for f in flights):
                flights = [f for f in flights if f.get("selected_schedule")]
            recipients = {uid for uid in (quote.user_id, getattr(quote.group, "assigned_user_id", None)) if uid}
            for index, item in enumerate(flights):
                flight = dict(item)
                if index < len(registry_flights):
                    for field, value in registry_flights[index].items():
                        flight.setdefault(field, value)
                mode = str(flight.get("notification_mode") or (registry.notification_mode if registry else "") or "notificar_48h")
                window = _hours_window(mode)
                status = str(flight.get("checkin_status") or "").strip().lower()
                if not window or status in {"realizado", "concluido", "concluído", "feito", "cancelado"}:
                    continue
                trip = quote.group.trip
                kind = str(flight.get("kind") or "").lower()
                fallback_date = (trip.return_date if kind == "volta" else trip.departure_date) if trip else None
                departure = _departure(flight, fallback_date, registry.departure_time if registry else None)
                if departure is None or not timedelta(0) <= departure - now <= timedelta(hours=window):
                    continue
                flight_number = str(flight.get("flight_number") or (registry.flight_number if registry else "") or "")
                unique = f"{quote.group_id}:{index}:{departure.isoformat()}:{flight_number}"
                flight_key = hashlib.sha256(unique.encode()).hexdigest()
                client = str(payload.get("client_name") or quote.group.quote_name or "Passageiro")[:80]
                title = "Check-in disponível para o seu voo"
                body = f"{client} • {departure.strftime('%d/%m/%Y %H:%M')} • voo {flight_number or 'programado'}. Confira o check-in da companhia."
                link = f"/cadastros/voos/{quote.group_id}/editar?flight_index={index}"
                for user_id in recipients:
                    if not db.scalar(select(WebUser.id).where(WebUser.id == user_id, WebUser.active.is_(True))):
                        continue
                    if db.scalar(select(CheckinReminder.id).where(CheckinReminder.user_id == user_id,
                                                                  CheckinReminder.flight_key == flight_key)):
                        continue
                    try:
                        db.add(CheckinReminder(user_id=user_id, flight_key=flight_key))
                        create_notification(db, user_id, title, body, kind="warning", link=link, commit=False)
                        db.commit()
                    except IntegrityError:
                        db.rollback()  # outra instância do cron processou este voo
                        continue
                    created += 1
                    try:
                        delivered += send_push(db, user_id, title, body, link)
                    except Exception:
                        logger.exception("Notificação interna salva; erro no Push do usuário %s", user_id)
                        db.rollback()
    return {"scanned": scanned, "notifications_created": created, "push_delivered": delivered}
