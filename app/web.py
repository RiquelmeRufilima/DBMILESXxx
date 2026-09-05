from __future__ import annotations

import json
from datetime import date, datetime

from fastapi import Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import object_session

from .models import CompanyTask, Notification

from .config import TEMPLATES_DIR
from .security import ensure_csrf_token


templates = Jinja2Templates(directory=str(TEMPLATES_DIR))



ROLE_LABELS = {
    "admin": "Administrador",
    "gerente": "Gerente",
    "membro": "Consultor",
}

THEME_PRESETS = {
    "ocean": {"name": "Oceano", "primary": "#26c5e6", "secondary": "#2f7cf6"},
    "royal": {"name": "Azul Royal", "primary": "#4f8cff", "secondary": "#6d5dfc"},
    "emerald": {"name": "Esmeralda", "primary": "#28d6a0", "secondary": "#0fb6b0"},
    "violet": {"name": "Violeta", "primary": "#a56cff", "secondary": "#6f7cff"},
    "sunset": {"name": "Pôr do Sol", "primary": "#ff9f43", "secondary": "#ff5f7a"},
    "graphite": {"name": "Grafite", "primary": "#8fa6bc", "secondary": "#5f748b"},
}


def money(value, currency: str = "BRL") -> str:
    symbols = {"BRL": "R$", "USD": "US$", "EUR": "€", "GBP": "£"}
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        number = 0.0
    formatted = f"{number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{symbols.get(currency, currency)} {formatted}"


def date_br(value) -> str:
    if not value:
        return "—"
    if isinstance(value, (datetime, date)):
        return value.strftime("%d/%m/%Y")
    text = str(value).strip()
    date_part = text[:10]
    parts = date_part.split("-")
    if len(parts) == 3 and len(parts[0]) == 4:
        return f"{parts[2]}/{parts[1]}/{parts[0]}"
    return text


def date_time_br(value, time_value=None) -> str:
    """Exibe data e horário no padrão brasileiro, separados por um traço."""
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y - %H:%M")
    date_text = "" if value in (None, "") else date_br(value)
    if date_text == "—":
        date_text = ""
    time_text = str(time_value or "").strip()[:5]
    if not time_text and value not in (None, ""):
        raw = str(value).strip().replace("T", " ")
        if len(raw) >= 16 and ":" in raw[10:]:
            time_text = raw[11:16]
    if date_text and time_text:
        return f"{date_text} - {time_text}"
    return date_text or time_text or "—"


templates.env.filters["money"] = money
templates.env.filters["date_br"] = date_br
templates.env.filters["date_time_br"] = date_time_br
templates.env.filters["role_label"] = lambda value: ROLE_LABELS.get(str(value or "membro"), str(value or "Membro").title())
def safe_from_json(value, default=None):
    """Filtro tolerante para bancos antigos ou campos JSON parcialmente corrompidos."""
    fallback = [] if default is None else default
    if value in (None, ""):
        return fallback
    if isinstance(value, (list, dict)):
        return value
    try:
        parsed = json.loads(str(value))
        return parsed if isinstance(parsed, (list, dict)) else fallback
    except Exception:
        return fallback


templates.env.filters["from_json"] = safe_from_json


def flash(request: Request, message: str, kind: str = "info") -> None:
    request.session.setdefault("flashes", []).append({"message": message, "kind": kind})


def context(request: Request, *, user=None, **kwargs) -> dict:
    flashes = request.session.pop("flashes", [])
    preference = getattr(user, "preference", None) if user else None
    profile = getattr(user, "profile", None) if user else None

    unread_count = 0
    pending_task_count = 0
    if user is not None:
        try:
            db = object_session(user)
            if db is not None:
                # Em vez de carregar TODAS as notificações e ainda executar outra
                # consulta para tarefas, usamos dois subselects em um único roundtrip.
                title_lower = func.lower(Notification.title)
                unread_sq = (
                    select(func.count(Notification.id))
                    .where(
                        Notification.user_id == user.id,
                        Notification.read.is_(False),
                        func.lower(Notification.kind) != "quote",
                        ~title_lower.like("atualização de cotação%"),
                        ~title_lower.like("atualizacao de cotacao%"),
                    )
                    .scalar_subquery()
                )
                task_scope = (
                    CompanyTask.company_id == user.company_id
                    if user.company_id
                    else CompanyTask.created_by_user_id == user.id
                )
                tasks_sq = (
                    select(func.count(CompanyTask.id))
                    .where(task_scope, CompanyTask.status == "pendente")
                    .scalar_subquery()
                )
                counts = db.execute(select(unread_sq, tasks_sq)).one()
                unread_count = int(counts[0] or 0)
                pending_task_count = int(counts[1] or 0)
        except Exception:
            # Mantém a interface disponível mesmo durante atualização de schema.
            unread_count = 0
            pending_task_count = 0

    preset_key = getattr(preference, "theme_preset", "ocean") if preference else "ocean"
    preset = THEME_PRESETS.get(preset_key, THEME_PRESETS["ocean"])
    accent = getattr(preference, "accent_color", None) or preset["primary"]
    theme = {
        "mode": getattr(preference, "theme_mode", "dark") if preference else "dark",
        "preset": preset_key,
        "primary": accent,
        "secondary": preset["secondary"],
        "background_style": getattr(preference, "background_style", "gradient") if preference else "gradient",
        "compact_mode": bool(getattr(preference, "compact_mode", False)) if preference else False,
    }

    return {
        "request": request,
        "user": user,
        "profile": profile,
        "preference": preference,
        "theme": theme,
        "theme_presets": THEME_PRESETS,
        "unread_count": unread_count,
        "pending_task_count": pending_task_count,
        "csrf_token": ensure_csrf_token(request.session),
        "flashes": flashes,
        **kwargs,
    }

# Adicione esta função no seu arquivo web.py

def format_money(value: float, currency: str = "BRL") -> str:
    """Lógica para formatação de campos numéricos (moedas)."""
    try:
        val = float(value or 0.0)
    except (ValueError, TypeError):
        return "R$ 0,00"

    if currency == "BRL" or not currency:
        # Formata para o padrão brasileiro: R$ 1.234,56
        return f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    elif currency == "USD":
        return f"US$ {val:,.2f}"
    elif currency == "EUR":
        return f"€ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    else:
        return f"{currency} {val:,.2f}"

# Registre o filtro no ambiente do Jinja2 logo após instanciar o templates:
# templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.filters["money"] = format_money