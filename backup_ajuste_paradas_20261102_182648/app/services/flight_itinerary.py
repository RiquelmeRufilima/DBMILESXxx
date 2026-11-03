"""Optional flight stop/leg metadata; no DB migration, no change to fare formula.

All submitted fields are untrusted. Normalize, cap, and derive the cost server-side.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

MAX_STOPS = 4
MAX_SIDES = 12
MAX_BAGS = 10
_ALLOWED_CLASSES = {"", "Econômica", "Premium", "Executiva", "Primeira"}
_CURRENCY_LIMIT = Decimal("1000000.00")


def _text(value: Any, limit: int = 140) -> str:
    return " ".join(str(value or "").split())[:limit]


def _iata(value: Any) -> str:
    val = _text(value, 8).upper()
    return val if re.fullmatch(r"[A-Z]{3}", val) else ""


def _money(value: Any) -> Decimal:
    if isinstance(value, bool):
        return Decimal("0")
    text = str(value if value is not None else "0").strip()
    if "," in text and "." in text and text.rfind(",") > text.rfind("."):
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        amount = Decimal(text)
        if not amount.is_finite() or amount < 0:
            return Decimal("0")
        return min(amount, _CURRENCY_LIMIT).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _number(value: Any, low: int, high: int, default: int = 0) -> int:
    try:
        parsed = int(value)
    except (ValueError, TypeError, OverflowError):
        return default
    return min(high, max(low, parsed))


def _datetime(value: Any) -> str:
    raw = str(value or "")[:16]
    if not raw:
        return ""
    try:
        # HTML datetime-local: YYYY-MM-DDTHH:mm
        dt = datetime.strptime(raw, "%Y-%m-%dT%H:%M")
        return dt.strftime("%Y-%m-%dT%H:%M")
    except ValueError:
        return ""


def _tz(value: Any) -> str:
    # Explicit time zone UTC offset, not inferred from IATA.
    val = str(value or "")
    if not re.fullmatch(r"[+-](?:0\d|1[0-4]):(?:00|30|45)", val):
        return ""
    hours = int(val[1:3]); minutes = int(val[4:6])
    if hours == 14 and minutes != 0:
        return ""
    return val


def _as_utc(local: str, offset: str) -> datetime | None:
    if not local or not offset:
        return None
    dt = datetime.strptime(local, "%Y-%m-%dT%H:%M")
    sign = 1 if offset.startswith("+") else -1
    minutes = int(offset[1:3]) * 60 + int(offset[4:6])
    return dt - timedelta(minutes=sign * minutes)


def normalize_itinerary(raw: Any, selected_segments: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Each direction is independent; absent/disabled state is a no-op.

    The route's origin and destination are controlled by the actual quote, never by
    an arbitrary client side string. No expected stop count is mandatory.
    """
    if isinstance(raw, str):
        if len(raw) > 70000:
            return {"version": 1, "sides": [], "charge_extra_bags": False, "extra_bags_cost": 0, "extra_bags_sale": 0}
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            raw = {}
    if not isinstance(raw, dict):
        raw = {}
    allowed: dict[str, tuple[str, str]] = {}
    for i, segment in enumerate(selected_segments or []):
        if not isinstance(segment, dict):
            continue
        key = _text(segment.get("key") or f"segment_{i+1}", 30)
        if not re.fullmatch(r"(?:outbound|return|one_way|segment_\d+)", key):
            continue
        allowed[key] = (_iata(segment.get("origin")), _iata(segment.get("destination")))
    # A saved itinerary from an older quote need not be valid in a new scope.
    raw_sides = raw.get("sides") if isinstance(raw.get("sides"), list) else []
    normalized_sides: list[dict[str, Any]] = []
    total_cost = Decimal("0")
    total_sale = Decimal("0")
    for side in raw_sides[:MAX_SIDES]:
        if not isinstance(side, dict):
            continue
        key = _text(side.get("key"), 30)
        if key not in allowed:
            continue
        origin, destination = allowed[key]
        # Multicity lists with several candidate IATAs can omit a single IATA.
        if not origin or not destination:
            continue
        stops_input = side.get("stops") if isinstance(side.get("stops"), list) else []
        stops: list[str] = []
        if str(side.get("status") or "direct") == "stops":
            for stop in stops_input[:MAX_STOPS]:
                code = _iata(stop)
                if code and code not in {origin, destination}:
                    stops.append(code)
        airports = [origin, *stops, destination]
        leg_inputs = side.get("legs") if isinstance(side.get("legs"), list) else []
        legs: list[dict[str, Any]] = []
        for idx in range(len(airports) - 1):
            leg = leg_inputs[idx] if idx < len(leg_inputs) and isinstance(leg_inputs[idx], dict) else {}
            cabin = _text(leg.get("cabin"), 30)
            if cabin not in _ALLOWED_CLASSES:
                cabin = ""
            bags = _number(leg.get("included_bags"), 0, MAX_BAGS)
            added = _number(leg.get("extra_bags"), 0, MAX_BAGS)
            cost = _money(leg.get("extra_cost"))
            sale = _money(leg.get("extra_sale"))
            leg_cost = cost * added
            leg_sale = sale * added
            total_cost += leg_cost
            total_sale += leg_sale
            legs.append({
                "origin": airports[idx], "destination": airports[idx + 1],
                "partner": _text(leg.get("partner"), 180),
                "operator": _text(leg.get("operator"), 180),
                "cabin": cabin, "fare": _text(leg.get("fare"), 70),
                "included_bags": bags, "extra_bags": added,
                "extra_weight": _number(leg.get("extra_weight"), 0, 50),
                "extra_passenger": _text(leg.get("extra_passenger"), 100),
                "extra_cost": float(cost), "extra_sale": float(sale),
                "departure": _datetime(leg.get("departure")),
                "arrival": _datetime(leg.get("arrival")),
                "origin_tz": _tz(leg.get("origin_tz")),
                "destination_tz": _tz(leg.get("destination_tz")),
            })
        # Validate chronological order and compute duration ONLY when all
        # dates, times and explicit time zones are present.
        duration_minutes = None
        wait_minutes: list[int | None] = []
        if legs:
            start = _as_utc(legs[0]["departure"], legs[0]["origin_tz"])
            finish = _as_utc(legs[-1]["arrival"], legs[-1]["destination_tz"])
            valid = bool(start and finish and finish >= start)
            for idx in range(len(legs) - 1):
                arrive = _as_utc(legs[idx]["arrival"], legs[idx]["destination_tz"])
                depart = _as_utc(legs[idx + 1]["departure"], legs[idx + 1]["origin_tz"])
                wait = int((depart - arrive).total_seconds() // 60) if arrive and depart else None
                if wait is None or wait < 0:
                    valid = False
                    wait = None
                wait_minutes.append(wait)
            for leg in legs:
                depart = _as_utc(leg["departure"], leg["origin_tz"])
                arrive = _as_utc(leg["arrival"], leg["destination_tz"])
                if depart is None or arrive is None or arrive < depart:
                    valid = False
            if valid:
                duration_minutes = int((finish - start).total_seconds() // 60)
        normalized_sides.append({"key": key, "status": "stops" if stops else "direct", "stops": stops,
                                 "origin": origin, "destination": destination, "legs": legs,
                                 "wait_minutes": wait_minutes, "duration_minutes": duration_minutes})

    # Financial impact is opt-in to avoid charging bags twice when they were
    # already counted in the original calculation's bags_override.
    charge = raw.get("charge_extra_bags") is True
    total_cost = min(total_cost, _CURRENCY_LIMIT)
    total_sale = min(total_sale, _CURRENCY_LIMIT)
    return {"version": 1, "sides": normalized_sides, "charge_extra_bags": charge,
            "extra_bags_cost": float(total_cost), "extra_bags_sale": float(total_sale)}
