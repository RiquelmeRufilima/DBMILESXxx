from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import current_user
from ..services.amadeus import AmadeusError, amadeus_client

router = APIRouter(prefix="/api/amadeus", tags=["amadeus"])


def _require_login(request: Request, db: Session):
    user = current_user(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Login necessário")
    return user


@router.get("/status")
async def amadeus_status(request: Request, db: Session = Depends(get_db)):
    _require_login(request, db)
    return {
        "enabled": amadeus_client.enabled,
        "configured": amadeus_client.configured,
        "environment": amadeus_client.environment,
        "booking_enabled": False,
    }


@router.get("/locations")
async def amadeus_locations(
    request: Request,
    keyword: str = Query(..., min_length=2, max_length=80),
    db: Session = Depends(get_db),
):
    _require_login(request, db)
    try:
        return await amadeus_client.search_locations(keyword)
    except AmadeusError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/flights")
async def amadeus_flights(
    request: Request,
    origin: str = Query(..., min_length=3, max_length=3),
    destination: str = Query(..., min_length=3, max_length=3),
    departure_date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    return_date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    adults: int = Query(1, ge=1, le=9),
    children: int = Query(0, ge=0, le=8),
    infants: int = Query(0, ge=0, le=8),
    travel_class: str | None = Query(None),
    non_stop: bool | None = Query(None),
    max_results: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    _require_login(request, db)
    if origin.upper() == destination.upper():
        raise HTTPException(status_code=422, detail="Origem e destino precisam ser diferentes.")
    try:
        return await amadeus_client.search_flights(
            origin=origin,
            destination=destination,
            departure_date=departure_date,
            return_date=return_date,
            adults=adults,
            children=children,
            infants=infants,
            travel_class=travel_class,
            non_stop=non_stop,
            max_results=max_results,
        )
    except AmadeusError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
