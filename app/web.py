from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, timedelta, timezone

from fastapi import Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import object_session

from .models import CompanyTask

from .config import TEMPLATES_DIR
from .security import ensure_csrf_token


templates = Jinja2Templates(directory=str(TEMPLATES_DIR))



ROLE_LABELS = {
    "admin": "Administrador",
    "gerente": "Gerente",
    "membro": "Consultor",
}

THEME_PRESETS = {
    "ocean": {"name":"Oceano","primary":"#26c5e6","secondary":"#2f7cf6","deep":"#082238","soft":"#eaf8ff"},
    "royal": {"name":"Azul Royal","primary":"#4f8cff","secondary":"#6d5dfc","deep":"#101f4a","soft":"#eef2ff"},
    "emerald": {"name":"Esmeralda","primary":"#28d6a0","secondary":"#0fb6b0","deep":"#07352f","soft":"#e9fbf6"},
    "violet": {"name":"Violeta","primary":"#a56cff","secondary":"#6f7cff","deep":"#26183f","soft":"#f4efff"},
    "sunset": {"name":"Pôr do Sol","primary":"#ff9f43","secondary":"#ff5f7a","deep":"#3c2118","soft":"#fff3e9"},
    "graphite": {"name":"Grafite","primary":"#8fa6bc","secondary":"#5f748b","deep":"#1b2632","soft":"#f1f4f7"},
}


def parse_number(value, default: float = 0.0) -> float:
    """Converte números salvos em formatos variados sem derrubar a tela.

    Aceita 1200.5, "1200.50", "1.200,50", "R$ 1.200,50", "1,5" e None.
    Qualquer valor inválido (texto, dict, lista, NaN/infinito) vira ``default``.
    """
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = str(value).strip()
        text = re.sub(r"[^\d,.\-]", "", text)
        if not text or text in {"-", ",", "."}:
            return default
        if "," in text and "." in text:
            # O separador que aparece por último é o decimal.
            if text.rfind(",") > text.rfind("."):
                text = text.replace(".", "").replace(",", ".")
            else:
                text = text.replace(",", "")
        elif "," in text:
            text = text.replace(".", "").replace(",", ".")
        elif text.count(".") > 1:
            text = text.replace(".", "")
        try:
            number = float(text)
        except ValueError:
            return default
    if math.isnan(number) or math.isinf(number):
        return default
    return number


def money(value, currency: str = "BRL") -> str:
    symbols = {"BRL": "R$", "USD": "US$", "EUR": "€", "GBP": "£"}
    currency = str(currency or "BRL").strip().upper() or "BRL"
    number = parse_number(value)
    formatted = f"{number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{symbols.get(currency, currency)} {formatted}"


def percent_br(value, digits: int = 2) -> str:
    """Percentual no padrão brasileiro: 27,50."""
    number = parse_number(value)
    return f"{number:,.{int(digits)}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def commercial_meta(value) -> dict:
    """Metadados comerciais (entrada Pix, ancoragem, maquininha) sempre como dict.

    O campo ``observations`` também recebe texto livre das observações do PDF;
    nesses casos não existe metadado e a tela não pode quebrar.
    """
    if isinstance(value, dict):
        return value
    if value in (None, ""):
        return {}
    try:
        parsed = json.loads(str(value))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def commercial_meta_json(value) -> str:
    meta = commercial_meta(value)
    safe = {
        "anchor_value": parse_number(meta.get("anchor_value")),
        "machine_name": str(meta.get("machine_name") or "")[:120],
        "entry_amount": parse_number(meta.get("entry_amount")),
    }
    return json.dumps(safe, ensure_ascii=False)


def entry_amount(value) -> float:
    return max(0.0, parse_number(commercial_meta(value).get("entry_amount")))


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


# Horário de Brasília. O banco grava em UTC (datetime.utcnow). O Brasil não tem
# horário de verão desde 2019, então UTC-3 fixo é exato e não depende do tzdata.
BRT = timezone(timedelta(hours=-3), "BRT")


def to_brt(value):
    """Converte um datetime gravado em UTC (sem fuso) para o horário de Brasília."""
    if not isinstance(value, datetime):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(BRT)


def brt(value, fmt: str = "%d/%m/%Y %H:%M") -> str:
    """Filtro Jinja: {{ item.created_at|brt('%d/%m %H:%M') }}"""
    if not value:
        return ""
    if isinstance(value, datetime):
        return to_brt(value).strftime(fmt)
    return str(value)


def iso_utc(value) -> str | None:
    """ISO com fuso (+00:00) para o JavaScript converter certo no navegador."""
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def date_time_br(value, time_value=None) -> str:
    """Exibe data e horário no padrão brasileiro, separados por um traço."""
    if isinstance(value, datetime):
        return to_brt(value).strftime("%d/%m/%Y - %H:%M")
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
from .services.travel_data import IATA_CITY_GROUPS, airport_city_label, BR_AIRPORT_CODES, br_airport_utc_offset  # noqa: E402
# Fusos fixos dos aeroportos brasileiros (sem horário de verão) para calcular a duração na tela.
templates.env.globals["br_airport_offsets"] = {code: br_airport_utc_offset(code) for code in sorted(BR_AIRPORT_CODES)}
templates.env.filters["airport_city"] = airport_city_label


_MILES_FIELD_KEYS = {"milhas", "pontos", "milheiro", "milhas_ida", "milhas_volta"}


def catalog_group(airline) -> str:
    """Grupo de exibição do cadastro: miles | airlines | systems | consolidators.

    A categoria salva continua "airlines" para companhias e programas; aqui ela
    é separada em "Programas de milhas" e "Companhias aéreas":
    - padrão do sistema: conforme o organograma (MILES_AIRLINE_SLUGS);
    - personalizada: tem algum tipo de cálculo ativo com campo de milhas/pontos.
    """
    from .services.travel_data import MILES_AIRLINE_SLUGS

    category = str(getattr(airline, "catalog_category", "") or "airlines")
    if getattr(airline, "builtin", False):
        category = "airlines"
    if category != "airlines":
        return category
    if getattr(airline, "builtin", False):
        return "miles" if getattr(airline, "slug", "") in MILES_AIRLINE_SLUGS else "airlines"
    try:
        for calc_type in getattr(airline, "calculation_types", None) or []:
            if not getattr(calc_type, "active", True) or getattr(calc_type, "legacy_key", None) == "valor_site":
                continue
            if getattr(calc_type, "legacy_key", None):
                return "miles"
            if any(str(getattr(field, "key", "")).lower() in _MILES_FIELD_KEYS for field in getattr(calc_type, "fields", None) or []):
                return "miles"
    except Exception:
        pass
    return "airlines"


CATALOG_GROUPS = (
    ("miles", "Programas de milhas"),
    ("airlines", "Companhias aéreas"),
    ("systems", "Sistemas"),
    ("consolidators", "Consolidadoras e Operadoras"),
)
templates.env.filters["catalog_group"] = catalog_group
templates.env.globals["catalog_groups"] = CATALOG_GROUPS
templates.env.globals["iata_city_groups"] = IATA_CITY_GROUPS
templates.env.filters["percent_br"] = percent_br
templates.env.filters["commercial_meta"] = commercial_meta
templates.env.filters["commercial_meta_json"] = commercial_meta_json
templates.env.filters["entry_amount"] = entry_amount
templates.env.filters["date_br"] = date_br
templates.env.filters["date_time_br"] = date_time_br
templates.env.filters["brt"] = brt
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


def company_member_names(user) -> list[str]:
    """Nomes dos usuários ativos da mesma empresa (para selects de responsável).

    Sem empresa, devolve só o próprio usuário. Nunca derruba a página.
    """
    if user is None:
        return []
    own = str(getattr(user, "name", "") or "").strip()
    try:
        from .models import WebUser
        db = object_session(user)
        company_id = getattr(user, "company_id", None)
        if db is None or not company_id:
            return [own] if own else []
        rows = db.scalars(
            select(WebUser.name).where(WebUser.company_id == company_id, WebUser.active.is_(True)).order_by(WebUser.name)
        ).all()
        names = [str(name).strip() for name in rows if str(name or "").strip()]
        if own and own not in names:
            names.insert(0, own)
        return list(dict.fromkeys(names))
    except Exception:
        try:
            object_session(user).rollback()
        except Exception:
            pass
        return [own] if own else []


templates.env.globals["company_member_names"] = company_member_names


def flash(request: Request, message: str, kind: str = "info") -> None:
    # Reatribui a lista (em vez de .append) para a sessão perceber a mudança;
    # com o Starlette novo, mensagens seguidas se perdiam.
    flashes = list(request.session.get("flashes") or [])
    flashes.append({"message": message, "kind": kind})
    request.session["flashes"] = flashes[-8:]


def context(request: Request, *, user=None, **kwargs) -> dict:
    flashes = request.session.pop("flashes", [])
    preference = None
    profile = None
    if user is not None:
        # Relacionamentos opcionais podem não existir ainda em bancos antigos/Neon
        # durante um deploy. O layout nunca deve derrubar a aplicação por isso.
        db = object_session(user)
        try:
            preference = getattr(user, "preference", None)
        except Exception:
            if db is not None:
                db.rollback()
        try:
            profile = getattr(user, "profile", None)
        except Exception:
            if db is not None:
                db.rollback()
    # Sininho: só a CONTAGEM de não lidas, feita no banco. Antes todas as
    # notificações do usuário eram carregadas em toda página só para contar.
    # Atualizações automáticas de cotação pertencem ao chat e não entram.
    unread_count = 0
    if user is not None:
        try:
            from .models import Notification
            db = object_session(user)
            if db is not None:
                title = func.lower(func.trim(Notification.title))
                unread_count = int(db.scalar(
                    select(func.count(Notification.id)).where(
                        Notification.user_id == user.id,
                        Notification.read.is_(False),
                        func.lower(func.coalesce(Notification.kind, "")) != "quote",
                        ~title.like("atualização de cotação%"),
                        ~title.like("atualizacao de cotacao%"),
                    )
                ) or 0)
        except Exception:
            if db is not None:
                db.rollback()
            unread_count = 0

    pending_task_count = 0
    if user is not None:
        try:
            db = object_session(user)
            if db is not None:
                task_scope = (
                    CompanyTask.company_id == user.company_id
                    if user.company_id
                    else CompanyTask.created_by_user_id == user.id
                )
                pending_task_count = int(
                    db.scalar(
                        select(func.count(CompanyTask.id)).where(
                            task_scope,
                            CompanyTask.status == "pendente",
                        )
                    )
                    or 0
                )
        except Exception:
            # Mantém as demais páginas funcionando mesmo em banco antigo
            # antes da criação/migração da tabela de tarefas.
            pending_task_count = 0

    preset_key = getattr(preference, "theme_preset", "ocean") if preference else "ocean"
    preset = THEME_PRESETS.get(preset_key, THEME_PRESETS["ocean"])
    accent = getattr(preference, "accent_color", None) or preset["primary"]
    try:
        preference_settings = json.loads(getattr(preference, "settings_json", "{}") or "{}") if preference else {}
        if not isinstance(preference_settings, dict):
            preference_settings = {}
    except Exception:
        preference_settings = {}
    theme = {
        "mode": getattr(preference, "theme_mode", "dark") if preference else "dark",
        "preset": preset_key,
        "primary": accent,
        "secondary": preset["secondary"],
        "background_style": getattr(preference, "background_style", "gradient") if preference else "gradient",
        "compact_mode": bool(getattr(preference, "compact_mode", False)) if preference else False,
        "deep": preset.get("deep", "#082238"),
        "soft": preset.get("soft", "#eaf8ff"),
    }

    return {
        "request": request,
        "user": user,
        "profile": profile,
        "preference": preference,
        "theme": theme,
        "theme_presets": THEME_PRESETS,
        "preference_settings": preference_settings,
        "unread_count": unread_count,
        "pending_task_count": pending_task_count,
        "csrf_token": ensure_csrf_token(request.session),
        "flashes": flashes,
        **kwargs,
    }
def format_money(value, currency: str = "BRL") -> str:
    """Compatibilidade: mesmo formato brasileiro do filtro ``money``."""
    return money(value, currency or "BRL")
