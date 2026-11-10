"""Companhia que aparece para o cliente (arte, PDF).

Consolidadoras e sistemas são fornecedores: o cliente vê apenas a companhia que
opera o voo (campo "Operado por"), nunca o nome do fornecedor.
"""
from __future__ import annotations

import json
import unicodedata

from sqlalchemy import or_, select
from sqlalchemy.orm import object_session

from ..models import Airline, WebQuote
from .airline_logos import logo_from_name

SUPPLIER_CATEGORIES = {"systems", "consolidators"}


def is_supplier(quote: WebQuote | None) -> bool:
    airline = getattr(quote, "airline", None)
    return bool(airline and getattr(airline, "catalog_category", "") in SUPPLIER_CATEGORIES)


def _token(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().lower()
    return "".join(ch for ch in text if ch.isalnum())


def operating_names(quote: WebQuote) -> list[str]:
    try:
        data = json.loads(quote.input_json or "{}")
    except (TypeError, ValueError):
        data = {}
    partnership = data.get("_partnership") if isinstance(data, dict) and isinstance(data.get("_partnership"), dict) else {}
    names: list[str] = []
    rows = partnership.get("segment_partners") if isinstance(partnership.get("segment_partners"), list) else []
    for row in sorted((r for r in rows if isinstance(r, dict)), key=lambda r: int(r.get("segment") or 0) if str(r.get("segment") or "0").isdigit() else 0):
        name = str(row.get("partner_airline") or row.get("name") or "").strip()[:180]
        if name and _token(name) not in {_token(n) for n in names}:
            names.append(name)
    single = str(partnership.get("partner_airline") or "").strip()[:180]
    if not names and single:
        names.append(single)
    return names


def _logo_for(quote: WebQuote, name: str) -> str:
    session = object_session(quote)
    if session is not None:
        owner = quote.company_id
        rows = session.scalars(
            select(Airline).where(
                Airline.active.is_(True),
                or_(Airline.builtin.is_(True), Airline.owner_company_id == owner) if owner else Airline.builtin.is_(True),
            )
        ).all()
        wanted = _token(name)
        for row in rows:
            if row.logo_path and _token(row.name) == wanted:
                return row.logo_path
    return logo_from_name(name) or ""


def client_airline(quote: WebQuote) -> dict:
    """Nome, logo (caminho) e cor da companhia mostrada ao cliente."""
    airline = getattr(quote, "airline", None)
    if not is_supplier(quote):
        return {
            "name": airline.name if airline else "",
            "logo_path": (airline.logo_path if airline else "") or "",
            "color": (airline.color if airline else "") or "#24b7d3",
            "supplier": False,
        }
    names = operating_names(quote)
    return {
        "name": " + ".join(names),
        "logo_path": _logo_for(quote, names[0]) if names else "",
        "color": "#24b7d3",
        "supplier": True,
    }
