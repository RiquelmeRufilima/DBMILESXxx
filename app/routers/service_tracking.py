"""Acompanhamentos vinculados às cotações aceitas; não duplica os dados."""
from __future__ import annotations
import json
from fastapi import APIRouter, Depends, Request, HTTPException, Query
from sqlalchemy import select, func, desc, case, cast, or_
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session, selectinload
from ..database import get_db
from ..dependencies import require_user
from ..models import AcceptedQuote, QuoteGroup, WebUser
from ..web import templates, context
from ..services.tags import list_tags, tags_for_targets

router = APIRouter(prefix="/acompanhamentos", tags=["acompanhamentos"])
# Cada tipo possui sua própria faixa de 200 índices (evita repetir etiquetas
# de hospedagem em transportes, por exemplo), mantendo o ID dentro do grupo.
def _service_tag_id(group_id: int, kind: str, index: int) -> int:
    family = {"hospedagens": 0, "transportes": 1, "experiencias": 2, "cruzeiros": 3, "seguros": 4}.get(kind, 0)
    return int(group_id)*1000 + family*200 + max(0, min(199, int(index)))

KINDS = {
    "hospedagens": ("hotel", "Hospedagens"),
    "transportes": ("transport", "Transportes"),
    "experiencias": ("experiences", "Experiências turísticas"),
    "cruzeiros": ("cruise", "Cruzeiros"),
    "seguros": ("insurance", "Seguros"),
}

def _service_val(service: dict, *keys) -> str:
    """Compatibilidade com campos usados nas versões antigas do editor."""
    for key in keys:
        value = service.get(key)
        if value not in (None, "", [], {}):
            return str(value).strip()
    return ""


def _list_services(data, key):
    services = data.get("services") if isinstance(data, dict) else None
    rows = services.get(key, []) if isinstance(services, dict) else []
    return [entry for entry in rows if isinstance(entry, dict)] if isinstance(rows, list) else []

def _visible_filter(user):
    # Não confie em IDs enviados pelo navegador; empresa é imposta no backend.
    return AcceptedQuote.company_id == user.company_id if user.company_id else AcceptedQuote.user_id == user.id

@router.get("/{kind}")
def list_tracking(kind: str, request: Request, page: int = 1, q: str = "", tag: list[int] | None = Query(None), db: Session = Depends(get_db)):
    user = require_user(request, db)
    if kind not in KINDS:
        raise HTTPException(status_code=404, detail="Acompanhamento não encontrado")
    key, title = KINDS[kind]
    page = max(1, min(page, 100000))
    search = q.strip().casefold()[:90]
    # Consulta vinculada à empresa e limitada na origem. PostgreSQL/Neon filtra
    # cotações com serviços antes de transferir os registros para o Python.
    query = (select(AcceptedQuote)
             .where(_visible_filter(user))
             .options(selectinload(AcceptedQuote.group).selectinload(QuoteGroup.trip),
                      selectinload(AcceptedQuote.user))
             .order_by(desc(AcceptedQuote.updated_at), desc(AcceptedQuote.group_id)))
    backend = db.get_bind().dialect.name
    if backend == 'postgresql':
        services = cast(AcceptedQuote.extra_json, JSONB)['services'][key]
        present = case((func.jsonb_typeof(services) == 'array', func.jsonb_array_length(services)), else_=0)
        query = query.where(present > 0)
        if search:
            query = query.join(QuoteGroup, AcceptedQuote.group_id == QuoteGroup.id).where(
                or_(QuoteGroup.quote_name.ilike(f'%{search}%'), AcceptedQuote.extra_json.ilike(f'%{search}%')))
        # 20 cotações por lote. Se uma cotação tiver vários serviços, exibe-os juntos.
        candidates = db.scalars(query.offset((page-1)*20).limit(21)).all()
        has_more = len(candidates) > 20
        candidates = candidates[:20]
    else:
        # SQLite de testes: mantém comportamento sem expressão JSONB.
        candidates = db.scalars(query.limit(2000)).all()
        has_more = False
    results = []
    for accepted in candidates:
        try:
            data = json.loads(accepted.extra_json or "{}")
        except (TypeError, ValueError):
            continue
        group = accepted.group
        if not group or (group.company_id != user.company_id if user.company_id else group.user_id != user.id):
            continue
        name = str(data.get("client_name") or (group.trip.client_name if group.trip else "") or group.quote_name or "Cliente não informado")
        for index, service in enumerate(_list_services(data, key)):
            details = " • ".join(str(v) for k,v in service.items() if v not in (None, "", [], {}) and k.lower() not in ("internal_notes", "password"))[:240]
            if search and search not in (name+" "+details+" "+(group.quote_name or "")).casefold():
                continue
            results.append({"group_id": group.id, "client": name, "service": service,
                            "summary": details or title, "creator": (accepted.user.name if accepted.user else "Equipe"),
                            "code": str(data.get("quote_code") or f"m{group.id:04d}"),
                            "start_date": _service_val(service, "start_date", "checkin", "check_in", "checkin_date", "date_start", "arrival_date"),
                            "start_time": _service_val(service, "start_time", "checkin_time", "check_in_time"),
                            "end_date": _service_val(service, "end_date", "checkout", "check_out", "checkout_date", "date_end", "departure_date"),
                            "end_time": _service_val(service, "end_time", "checkout_time", "check_out_time"),
                            "reservation": _service_val(service, "reservation_number", "confirmation_number", "voucher", "locator"),
                            "hotel_name": _service_val(service, "name", "hotel", "hotel_name", "property_name", "type"),
                            "address": _service_val(service, "address", "hotel_address", "location"),
                            "status": str(accepted.status or ""),
                            "updated_at": accepted.updated_at, "index": index})
    tags_ready = True
    try:
        tag_map = tags_for_targets(db, user, "service", [_service_tag_id(x["group_id"], kind, x["index"]) for x in results])
        all_tags = list_tags(db, user, kind="acompanhamento")
    except Exception:
        tags_ready = False
        tag_map, all_tags = {}, []
    for row in results:
        row["tag_target_id"] = _service_tag_id(row["group_id"], kind, row["index"])
        row["tags"] = tag_map.get(row["tag_target_id"], [])
    selected_tags = sorted(set(tag or [])) if isinstance(tag, list) else []
    if selected_tags:
        results = [row for row in results if set(selected_tags).issubset({int(t['id']) for t in row['tags']})]
    total = len(results)
    subset = results if backend == 'postgresql' else results[(page-1)*20:page*20]
    has_more = has_more if backend == 'postgresql' else total > page*20
    return templates.TemplateResponse(request, "cadastros/service_tracking.html", context(
        request, user=user, kind=kind, title=title, kinds=KINDS, items=subset,
        page=page, total=total, has_more=has_more, search=q[:90],
        tags_ready=tags_ready, all_tags=all_tags, selected_tags=selected_tags,
        tag_query=''.join(f'&tag={i}' for i in selected_tags),
        scan_limited=(backend != 'postgresql' and len(candidates) == 2000)))
