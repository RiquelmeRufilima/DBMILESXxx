from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import find_legacy_database
from ..models import Airline, CalculationType, WebCompany, WebQuote, WebUser

logger = logging.getLogger(__name__)


def _row_dict(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in row.keys()}


def _parse_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value
    if value:
        text = str(value).replace("T", " ")
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M"):
            try:
                return datetime.strptime(text[:19], fmt)
            except ValueError:
                continue
    return datetime.utcnow()


def _infer_airline_slug(name: str | None) -> str | None:
    text = (name or "").lower()
    if "azul pelo mundo" in text or "voeazul" in text:
        return "azulpelomundo"
    if "latam" in text:
        return "latam"
    if "gol" in text or "smiles" in text:
        return "gol"
    if "american" in text or "aadvantage" in text:
        return "american"
    if "azul" in text:
        return "azul"
    return None


def _infer_calc_type(airline: Airline | None, type_name: str | None) -> CalculationType | None:
    if airline is None or not airline.calculation_types:
        return None
    text = (type_name or "").lower()
    for calc in airline.calculation_types:
        key = (calc.legacy_key or "").lower()
        if "desagio" in key and ("desagio" in text or "deságio" in text):
            return calc
        if "pontos_dinheiro" in key and ("dinheiro" in text):
            return calc
        if "pontos" in key and "dinheiro" not in key and "pontos" in text:
            return calc
        if "smiles" in key and "smiles" in text:
            return calc
        if "latam" in key and "latam" in text:
            return calc
        if "american" in key and ("american" in text or "aadvantage" in text):
            return calc
    return airline.calculation_types[0]


def migrate_legacy_data(db: Session, legacy_path: Path | None = None, force: bool = False) -> dict[str, int | str]:
    path = legacy_path or find_legacy_database()
    if path is None or not path.exists():
        return {"status": "sem_banco_legado", "companies": 0, "users": 0, "quotes": 0}

    existing_users = db.scalar(select(func.count(WebUser.id))) or 0
    if existing_users and not force:
        return {"status": "ja_migrado", "companies": 0, "users": 0, "quotes": 0}

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    result = {"status": "ok", "companies": 0, "users": 0, "quotes": 0}
    company_map: dict[int, int] = {}
    user_map: dict[int, int] = {}

    try:
        tables = {row[0] for row in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

        if "empresas" in tables:
            for row in cursor.execute("SELECT * FROM empresas ORDER BY id"):
                item = _row_dict(row)
                legacy_id = int(item["id"])
                company = db.get(WebCompany, legacy_id)
                if company is None:
                    company = WebCompany(
                        id=legacy_id,
                        name=item.get("nome") or f"Empresa {legacy_id}",
                        cnpj=item.get("cnpj"),
                        phone=item.get("telefone"),
                        email=item.get("email"),
                        logo_path=item.get("logo"),
                        created_at=_parse_datetime(item.get("data_criacao")),
                    )
                    db.add(company)
                    db.flush()
                    result["companies"] += 1
                company_map[legacy_id] = company.id

        if "usuarios" in tables:
            for row in cursor.execute("SELECT * FROM usuarios ORDER BY id"):
                item = _row_dict(row)
                legacy_id = int(item["id"])
                email = (item.get("email") or f"usuario{legacy_id}@local.invalid").strip().lower()
                existing = db.scalar(select(WebUser).where(WebUser.email == email))
                if existing:
                    user_map[legacy_id] = existing.id
                    continue
                user = WebUser(
                    id=legacy_id,
                    legacy_id=legacy_id,
                    company_id=company_map.get(item.get("empresa_id")),
                    email=email,
                    password_hash=item.get("senha_hash") or "!sem_senha!",
                    name=item.get("nome") or email.split("@")[0],
                    phone=item.get("telefone"),
                    role=item.get("nivel_acesso") or "membro",
                    active=bool(item.get("ativo", 1)),
                    created_at=_parse_datetime(item.get("data_criacao") or item.get("created_at")),
                )
                db.add(user)
                db.flush()
                user_map[legacy_id] = user.id
                result["users"] += 1

        db.commit()

        airlines = {airline.slug: airline for airline in db.scalars(select(Airline)).all()}

        if "historico_cotacoes" in tables:
            for row in cursor.execute("SELECT * FROM historico_cotacoes ORDER BY id"):
                item = _row_dict(row)
                legacy_id = int(item["id"])
                if db.scalar(select(WebQuote.id).where(WebQuote.legacy_id == legacy_id)):
                    continue

                user_id = user_map.get(item.get("usuario_id"))
                if not user_id:
                    continue

                slug = _infer_airline_slug(item.get("companhia"))
                airline = airlines.get(slug) if slug else None
                calc_type = _infer_calc_type(airline, item.get("tipo_calculo"))

                metadata = {}
                raw_metadata = item.get("metadata")
                if raw_metadata:
                    try:
                        metadata = json.loads(raw_metadata) if isinstance(raw_metadata, str) else raw_metadata
                    except Exception:
                        metadata = {}

                inputs = {
                    "milhas": item.get("milhas_total") or 0,
                    "milheiro": item.get("valor_milheiro") or 0,
                    "taxa": item.get("taxa_embarque") or 0,
                    "metadata_legado": metadata,
                }
                breakdown = {
                    "importado_do_sistema_anterior": True,
                    "valor_base": item.get("valor_base") or 0,
                    "valor_bagagens": item.get("valor_bagagens") or 0,
                    "tipo_calculo_legado": item.get("tipo_calculo"),
                }

                quote = WebQuote(
                    legacy_id=legacy_id,
                    user_id=user_id,
                    company_id=company_map.get(item.get("empresa_id")),
                    airline_id=airline.id if airline else None,
                    calculation_type_id=calc_type.id if calc_type else None,
                    quote_name=item.get("nome_cotacao") or item.get("companhia") or "Cotação importada",
                    origin=item.get("origem"),
                    destination=item.get("destino"),
                    passengers=int(item.get("passageiros") or 1),
                    babies=int(item.get("bebes") or 0),
                    bags=int(item.get("num_bagagens") or 0),
                    currency=item.get("moeda") or "BRL",
                    input_json=json.dumps(inputs, ensure_ascii=False),
                    breakdown_json=json.dumps(breakdown, ensure_ascii=False),
                    total=float(item.get("total_geral") or 0),
                    created_at=_parse_datetime(item.get("data_calculo")),
                )
                db.add(quote)
                result["quotes"] += 1

                if result["quotes"] % 100 == 0:
                    db.flush()

        db.commit()
        logger.info("Migração do legado concluída: %s", result)
        return result
    except Exception:
        db.rollback()
        logger.exception("Falha ao migrar banco legado")
        raise
    finally:
        conn.close()
