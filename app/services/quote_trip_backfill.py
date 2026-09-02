from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import QuoteTripDetail, WebQuote


def _normalize_date(value: Any) -> str | None:
    """Normaliza datas antigas para YYYY-MM-DD sem inventar valores."""
    if value in (None, "", "None"):
        return None

    text = str(value).strip()
    if not text:
        return None

    # Já está em formato compatível com input type=date.
    if len(text) >= 10 and text[4:5] == "-" and text[7:8] == "-":
        return text[:10]

    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    return text[:20]


def _travel_type(value: Any, return_date: str | None = None) -> str:
    text = str(value or "").strip().lower()
    normalized = (
        text.replace("á", "a")
        .replace("à", "a")
        .replace("ã", "a")
        .replace("â", "a")
        .replace("é", "e")
        .replace("ê", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ô", "o")
        .replace("õ", "o")
        .replace("ú", "u")
        .replace("ç", "c")
    )

    if "multi" in normalized or "trecho" in normalized:
        return "multi_city"
    if "ida e volta" in normalized or "round" in normalized:
        return "round_trip"
    if "somente ida" in normalized or "one way" in normalized or normalized == "ida":
        return "one_way"
    return "round_trip" if return_date else "one_way"


def _safe_json(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        parsed = json.loads(value)
        return parsed
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def backfill_quote_trip_details(db: Session) -> int:
    """
    Cria os detalhes de viagem que não existiam na V4.

    Isso é executado na inicialização e é idempotente: cotações que já possuem
    QuoteTripDetail não são alteradas. Assim, uma pasta V4 pode receber a V5
    sem perder histórico nem exigir uma nova migração do banco antigo.
    """
    quotes = db.scalars(
        select(WebQuote)
        .outerjoin(QuoteTripDetail, QuoteTripDetail.quote_id == WebQuote.id)
        .where(QuoteTripDetail.quote_id.is_(None))
        .order_by(WebQuote.id)
    ).all()

    created = 0
    for quote in quotes:
        payload = _safe_json(quote.input_json, {})
        if not isinstance(payload, dict):
            payload = {}

        metadata = payload.get("metadata_legado") or payload.get("metadata") or {}
        if isinstance(metadata, str):
            metadata = _safe_json(metadata, {})
        if not isinstance(metadata, dict):
            metadata = {}

        departure = _normalize_date(
            metadata.get("data_ida")
            or metadata.get("departure_date")
            or payload.get("data_ida")
            or payload.get("departure_date")
        )
        return_date = _normalize_date(
            metadata.get("data_volta")
            or metadata.get("return_date")
            or payload.get("data_volta")
            or payload.get("return_date")
        )

        travel_type = _travel_type(
            metadata.get("tipo_viagem")
            or metadata.get("travel_type")
            or payload.get("tipo_viagem")
            or payload.get("travel_type"),
            return_date,
        )

        segments = (
            metadata.get("segmentos")
            or metadata.get("segments")
            or payload.get("segmentos")
            or payload.get("segments")
            or []
        )
        if isinstance(segments, str):
            segments = _safe_json(segments, [])
        if not isinstance(segments, list):
            segments = []

        client_name = (
            metadata.get("cliente")
            or metadata.get("nome_cliente")
            or metadata.get("client_name")
            or payload.get("client_name")
        )
        client_email = metadata.get("client_email") or payload.get("client_email")
        client_phone = metadata.get("client_phone") or payload.get("client_phone")
        notes = metadata.get("observacoes") or metadata.get("notes") or payload.get("notes")

        db.add(
            QuoteTripDetail(
                quote_id=quote.id,
                travel_type=travel_type,
                departure_date=departure,
                return_date=return_date,
                segments_json=json.dumps(segments, ensure_ascii=False),
                client_name=str(client_name).strip() if client_name else None,
                client_email=str(client_email).strip() if client_email else None,
                client_phone=str(client_phone).strip() if client_phone else None,
                notes=str(notes).strip() if notes else None,
            )
        )
        created += 1

    if created:
        db.commit()
    return created
