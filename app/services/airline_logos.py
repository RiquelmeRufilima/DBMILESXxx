"""Encontra a logo da companhia aérea pelo nome (para voos, reservas etc.).

Ordem: logo da companhia ligada à cotação -> companhias cadastradas no sistema
(com logo) -> arquivos oficiais em app/imagens. Sem logo: devolve iniciais e cor.
"""
from __future__ import annotations

import re
import unicodedata

from ..config import AIRLINE_IMAGE_DIR

# apelido (já normalizado: minúsculo, sem acento, só letras/números) -> arquivo
_ALIASES: dict[str, str] = {
    "latam": "latam.png", "tam": "latam.png",
    "gol": "gol2.png", "smiles": "gol2.png",
    "azul": "azul.png", "tudoazul": "azul.png", "azulpelomundo": "azulpelomundo.png",
    "american": "american.png", "aadvantage": "american.png",
    "tap": "tap.png", "tapairportugal": "tap.png",
    "aerolineasargentinas": "aerolineas.png", "aerolineas": "aerolineas.png",
    "aeromexico": "aeromexico.png",
    "aircanada": "aircanada.png", "airchina": "airchina.png", "aireuropa": "aireuropa.png",
    "airfrance": "airfrance.png", "airnewzealand": "airnewzealand.png",
    "amaszonas": "amaszonas.png", "ana": "ana.png", "allnipponairways": "ana.png",
    "arajet": "arajet.png", "avianca": "avianca.png", "boa": "boa.png", "boliviana": "boa.png",
    "british": "british.png", "britishairways": "british.png", "condor": "condor.png",
    "copa": "copa.png", "delta": "delta.png", "elal": "elal.png", "emirates": "emirates.png",
    "ethiopian": "ethiopian.png", "iberia": "iberia.png", "ita": "ita.png", "itaairways": "ita.png",
    "jal": "jal.png", "japanairlines": "jal.png", "jetsmart": "jetsmart.png", "klm": "klm.png",
    "korean": "koreanair.png", "koreanair": "koreanair.png", "lufthansa": "lufthansa.png",
    "paranair": "paranair.png", "qantas": "qantas.png", "qatar": "qatar.png", "qatarairways": "qatar.png",
    "royalairmaroc": "royalairmaroc.png", "singapore": "singapore.png", "sky": "sky.png", "skyairline": "sky.png",
    "southafrican": "southafrican.png", "swiss": "swiss.png", "taag": "taag.jpg", "turkish": "turkish.png",
    "turkishairlines": "turkish.png", "united": "united.png",
    "voepass": "voepass.png", "passaredo": "voepass.png",
}
_NOISE = re.compile(r"\b(linhas aereas|linhas aéreas|airlines|airline|airways|air lines|s\.?a\.?|ltda|inteligentes)\b")
_PALETTE = ["#e11d48", "#2563eb", "#059669", "#d97706", "#7c3aed", "#0891b2", "#db2777", "#4f46e5"]


def _normalize(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii").lower()
    return text


def _compact(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", _normalize(value))


def _words(value: str | None) -> list[str]:
    return re.findall(r"[a-z0-9]+", _NOISE.sub(" ", _normalize(value)))


def _file_url(filename: str) -> str | None:
    try:
        if (AIRLINE_IMAGE_DIR / filename).is_file():
            return f"/imagens/{filename}"
    except Exception:
        return None
    return None


def _logo_path_url(path: str | None) -> str | None:
    path = str(path or "").strip()
    if not path:
        return None
    if path.startswith(("http://", "https://", "/")):
        return path
    return "/" + path.lstrip("/")


def logo_from_name(name: str | None) -> str | None:
    full = _compact(name)
    if not full:
        return None
    if full in _ALIASES:
        return _file_url(_ALIASES[full])
    words = _words(name)
    joined = "".join(words)
    if joined in _ALIASES:
        return _file_url(_ALIASES[joined])
    # Apelidos longos podem aparecer dentro do nome ("TAP Air Portugal Express").
    for alias in sorted(_ALIASES, key=len, reverse=True):
        if len(alias) >= 5 and alias in full:
            return _file_url(_ALIASES[alias])
    # Apelidos curtos (gol, tap, ana...) só valem como palavra inteira.
    for word in words:
        if word in _ALIASES:
            return _file_url(_ALIASES[word])
    return None


def initials(name: str | None) -> str:
    words = _words(name) or [_compact(name) or "?"]
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][:1] + words[1][:1]).upper()


def color_for(name: str | None) -> str:
    return _PALETTE[sum(ord(ch) for ch in _compact(name)) % len(_PALETTE)]


class AirlineLogoResolver:
    """Cache por requisição: resolve nome -> URL da logo."""

    def __init__(self, airlines: list | None = None) -> None:
        self._db_logos: dict[str, str] = {}
        for airline in airlines or []:
            url = _logo_path_url(getattr(airline, "logo_path", None))
            if url and getattr(airline, "name", None):
                self._db_logos[_compact(airline.name)] = url
        self._cache: dict[str, str | None] = {}

    def resolve(self, name: str | None, quote_airline=None) -> dict:
        label = str(name or "").strip() or (getattr(quote_airline, "name", "") or "")
        key = _compact(label)
        url = None
        if quote_airline is not None and _compact(getattr(quote_airline, "name", "")) == key:
            url = _logo_path_url(getattr(quote_airline, "logo_path", None))
        if not url and key:
            if key not in self._cache:
                self._cache[key] = self._db_logos.get(key) or logo_from_name(label)
            url = self._cache[key]
        return {"name": label, "logo_url": url, "initials": initials(label) if label else "✈", "color": color_for(label)}
