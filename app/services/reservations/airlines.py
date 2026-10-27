"""Companhias disponíveis em "Adicionar reserva" e os campos que cada uma pede.

Os campos seguem o que o site/app de cada companhia exige para localizar uma
reserva (mesma lógica dos exemplos MilhasPix/Iddas). Para mudar uma companhia,
basta editar esta lista — a tela se ajusta sozinha.

Tipos de campo:
  locator          Localizador / código da reserva (5 a 8 letras/números)
  purchase_number  Número da compra (LATAM: começa com "LA")
  last_name        Último sobrenome do titular
  full_last_name   Sobrenome completo do titular (TAP)
  origin           Aeroporto de origem (código IATA, 3 letras)
"""
from __future__ import annotations

import re

from ..airline_logos import logo_from_name
from ..travel_data import CHECKIN_LINKS

FIELD_LABELS: dict[str, dict[str, str]] = {
    "locator": {"label": "Localizador", "placeholder": "Ex.: C3H8DF"},
    "purchase_number": {"label": "Número da compra", "placeholder": "LA***********"},
    "last_name": {"label": "Último sobrenome", "placeholder": "Ex.: Silva"},
    "full_last_name": {"label": "Sobrenome completo", "placeholder": "Ex.: da Silva Santos"},
    "origin": {"label": "Aeroporto de origem", "placeholder": "Ex.: FOR"},
}

_STANDARD = ["locator", "last_name"]

# Ordem = ordem dos cartões na tela (as mais usadas primeiro).
RESERVATION_AIRLINES: list[dict] = [
    {"slug": "gol", "name": "Gol", "fields": ["locator", "origin", "last_name"]},
    {"slug": "azul", "name": "Azul", "fields": ["locator", "origin"]},
    {"slug": "latam", "name": "LATAM", "fields": ["purchase_number", "last_name"]},
    {"slug": "avianca", "name": "Avianca", "fields": _STANDARD},
    {"slug": "iberia", "name": "Iberia", "fields": _STANDARD},
    {"slug": "tap", "name": "TAP Portugal", "fields": ["locator", "full_last_name"]},
    {"slug": "copa", "name": "Copa Airlines", "fields": _STANDARD},
    {"slug": "american", "name": "American Airlines", "fields": _STANDARD},
    {"slug": "united", "name": "United Airlines", "fields": _STANDARD},
    {"slug": "aireuropa", "name": "Air Europa", "fields": _STANDARD},
    {"slug": "british", "name": "British Airways", "fields": _STANDARD},
    {"slug": "jetsmart", "name": "JetSMART", "fields": _STANDARD},
    {"slug": "airfrance", "name": "Air France", "fields": _STANDARD},
    {"slug": "klm", "name": "KLM", "fields": _STANDARD},
    {"slug": "delta", "name": "Delta Air Lines", "fields": _STANDARD},
    {"slug": "aerolineas", "name": "Aerolíneas Argentinas", "fields": _STANDARD},
    {"slug": "emirates", "name": "Emirates", "fields": _STANDARD},
    {"slug": "sky", "name": "SKY Airline", "fields": _STANDARD},
    {"slug": "qatar", "name": "Qatar Airways", "fields": _STANDARD},
    {"slug": "turkish", "name": "Turkish Airlines", "fields": _STANDARD},
    {"slug": "royalairmaroc", "name": "Royal Air Maroc", "fields": _STANDARD},
    {"slug": "ethiopian", "name": "Ethiopian Airlines", "fields": _STANDARD},
    {"slug": "lufthansa", "name": "Lufthansa", "fields": _STANDARD},
]
_BY_SLUG = {item["slug"]: item for item in RESERVATION_AIRLINES}

_LOCATOR_RE = re.compile(r"^[A-Z0-9]{5,8}$")
_PURCHASE_RE = re.compile(r"^[A-Z]{2}[0-9A-Z]{6,18}$")
_IATA_RE = re.compile(r"^[A-Z]{3}$")


def get_airline(slug: str | None) -> dict | None:
    return _BY_SLUG.get(str(slug or "").strip().lower())


def airline_catalog() -> list[dict]:
    """Lista para a tela: nome, logo, campos (com rótulos) e link da cia."""
    catalog = []
    for item in RESERVATION_AIRLINES:
        catalog.append({
            "slug": item["slug"],
            "name": item["name"],
            "logo_url": logo_from_name(item["name"]) or logo_from_name(item["slug"]),
            "manage_url": CHECKIN_LINKS.get(item["slug"], ""),
            "fields": [{"key": key, **FIELD_LABELS[key]} for key in item["fields"]],
        })
    return catalog


def clean_inputs(airline: dict, data: dict) -> tuple[dict, str]:
    """Normaliza e valida os campos exigidos pela companhia.

    Retorna (valores, mensagem_de_erro). Sobrenome é guardado como digitado
    (sem espaços extras); códigos ficam em maiúsculas.
    """
    values: dict[str, str] = {}
    for key in airline["fields"]:
        raw = str(data.get(key) or "").strip()
        if key in {"locator", "purchase_number", "origin"}:
            raw = re.sub(r"[\s\-]", "", raw).upper()
        else:
            raw = re.sub(r"\s+", " ", raw)[:120]
        if not raw:
            return {}, f"Preencha: {FIELD_LABELS[key]['label']}."
        if key == "locator" and not _LOCATOR_RE.match(raw):
            return {}, "Localizador inválido: use de 5 a 8 letras/números (ex.: C3H8DF)."
        if key == "purchase_number" and not _PURCHASE_RE.match(raw):
            return {}, "Número da compra inválido (ex.: LA12345678901)."
        if key == "origin" and not _IATA_RE.match(raw):
            return {}, "Aeroporto de origem: use o código de 3 letras (ex.: FOR)."
        values[key] = raw
    return values, ""
