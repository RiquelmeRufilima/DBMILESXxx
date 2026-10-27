"""Reservas: lista e "Adicionar reserva" pelo localizador."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import current_user
from ..models import AirlineReservation
from ..security import validate_csrf_token
from ..services.protection import register_attempt, seconds_until_allowed, wait_message
from ..services.reservations import (
    STATUS_LABELS,
    airline_catalog,
    create_reservation,
    ensure_reservation_schema,
    list_reservations,
    providers_status,
    reservation_scope,
    sync_reservation,
)
from ..web import context, templates

router = APIRouter(prefix="/reservas", tags=["reservas"])


async def _payload(request: Request) -> dict:
    try:
        data = await request.json()
        return data if isinstance(data, dict) else {}
    except Exception:
        return dict(await request.form())


def _deny(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"ok": False, "message": message}, status_code=status)


@router.get("")
def reservations_page(request: Request, q: str = "", status: str = "", db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    items = list_reservations(db, user, q=q, status=status)
    counts = dict(
        db.execute(
            select(AirlineReservation.status, func.count(AirlineReservation.id))
            .where(reservation_scope(user))
            .group_by(AirlineReservation.status)
        ).all()
    )
    notify_count = db.scalar(
        select(func.count(AirlineReservation.id)).where(reservation_scope(user), AirlineReservation.notify_changes.is_(True))
    ) or 0
    return templates.TemplateResponse(
        request,
        "reservations/index.html",
        context(
            request,
            user=user,
            items=items,
            catalog=airline_catalog(),
            status_labels=STATUS_LABELS,
            counts=counts,
            total=sum(counts.values()),
            notify_count=notify_count,
            search_query=q,
            status_filter=status if status in STATUS_LABELS else "",
            auto_enabled=any(p["configured"] and p["name"] != "manual" for p in providers_status()),
        ),
    )


@router.get("/companhias")
def reservations_airlines(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return _deny("Faça login novamente.", 401)
    return {"ok": True, "airlines": airline_catalog(), "providers": providers_status()}


@router.post("")
async def reservations_create(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return _deny("Faça login novamente.", 401)
    data = await _payload(request)
    if not validate_csrf_token(request.session, str(data.get("csrf_token") or "")):
        return _deny("Sessão expirada. Recarregue a página.", 403)
    # Evita uso do formulário para "varrer" localizadores.
    wait = seconds_until_allowed(db, "reservation_lookup", str(user.id))
    if wait:
        return _deny(wait_message(wait), 429)
    register_attempt(db, "reservation_lookup", str(user.id), commit=False)

    reservation, error, result = await create_reservation(db, user, data)
    if reservation is None:
        db.commit()
        return _deny(error)
    db.commit()
    return {
        "ok": True,
        "id": reservation.id,
        "status": reservation.status,
        "status_label": STATUS_LABELS.get(reservation.status, reservation.status),
        "message": (result.message if result else "") or "Reserva adicionada.",
    }


@router.post("/{reservation_id}/sincronizar")
async def reservations_sync(reservation_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return _deny("Faça login novamente.", 401)
    data = await _payload(request)
    if not validate_csrf_token(request.session, str(data.get("csrf_token") or "")):
        return _deny("Sessão expirada. Recarregue a página.", 403)
    ensure_reservation_schema(db)
    reservation = db.scalar(select(AirlineReservation).where(AirlineReservation.id == reservation_id, reservation_scope(user)))
    if reservation is None:
        return _deny("Reserva não encontrada.", 404)
    result = await sync_reservation(db, reservation)
    db.commit()
    return {"ok": True, "status": reservation.status, "status_label": STATUS_LABELS.get(reservation.status), "message": result.message}


@router.post("/{reservation_id}/atualizar")
async def reservations_update(reservation_id: int, request: Request, db: Session = Depends(get_db)):
    """Atualiza descrição e notificação (edição rápida na lista)."""
    user = current_user(request, db)
    if user is None:
        return _deny("Faça login novamente.", 401)
    data = await _payload(request)
    if not validate_csrf_token(request.session, str(data.get("csrf_token") or "")):
        return _deny("Sessão expirada. Recarregue a página.", 403)
    ensure_reservation_schema(db)
    reservation = db.scalar(select(AirlineReservation).where(AirlineReservation.id == reservation_id, reservation_scope(user)))
    if reservation is None:
        return _deny("Reserva não encontrada.", 404)
    if "description" in data:
        reservation.description = str(data.get("description") or "").strip()[:300] or None
    if "notify" in data:
        reservation.notify_changes = str(data.get("notify")).lower() in {"1", "true", "on", "yes", "sim"}
    db.commit()
    return {"ok": True}


@router.post("/{reservation_id}/excluir")
async def reservations_delete(reservation_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return _deny("Faça login novamente.", 401)
    data = await _payload(request)
    if not validate_csrf_token(request.session, str(data.get("csrf_token") or "")):
        return _deny("Sessão expirada. Recarregue a página.", 403)
    ensure_reservation_schema(db)
    reservation = db.scalar(select(AirlineReservation).where(AirlineReservation.id == reservation_id, reservation_scope(user)))
    if reservation is None:
        return _deny("Reserva não encontrada.", 404)
    db.delete(reservation)
    db.commit()
    return {"ok": True}
