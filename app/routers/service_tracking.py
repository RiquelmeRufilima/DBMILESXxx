"""Acompanhamentos vinculados às cotações aceitas; não duplica os dados."""
from __future__ import annotations
import json
from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy import select, func, desc, case, cast, or_
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session, selectinload
from ..database import get_db
from ..dependencies import require_user
from ..models import AcceptedQuote, QuoteGroup, WebUser
from ..web import templates, context

router = APIRouter(prefix="/acompanhamentos", tags=["acompanhamentos"])
KINDS = {
    "hospedagens": ("hotel", "Hospedagens"),
    "transportes": ("transport", "Transportes"),
    "experiencias": ("experiences", "Experiências turísticas"),
    "cruzeiros": ("cruise", "Cruzeiros"),
    "seguros": ("insurance", "Seguros"),
}

def _list_services(data, key):
    services = data.get("services") if isinstance(data, dict) else None
    rows = services.get(key, []) if isinstance(services, dict) else []
    return [entry for entry in rows if isinstance(entry, dict)] if isinstance(rows, list) else []

def _visible_filter(user):
    # Não confie em IDs enviados pelo navegador; empresa é imposta no backend.
    return AcceptedQuote.company_id == user.company_id if user.company_id else AcceptedQuote.user_id == user.id

@router.get("/{kind}")
def list_tracking(kind: str, request: Request, page: int = 1, q: str = "", db: Session = Depends(get_db)):
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
                            "updated_at": accepted.updated_at, "index": index})
    total = len(results)
    subset = results if backend == 'postgresql' else results[(page-1)*20:page*20]
    has_more = has_more if backend == 'postgresql' else total > page*20
    return templates.TemplateResponse(request, "cadastros/service_tracking.html", context(
        request, user=user, kind=kind, title=title, kinds=KINDS, items=subset,
        page=page, total=total, has_more=has_more, search=q[:90],
        scan_limited=(backend != 'postgresql' and len(candidates) == 2000)))
