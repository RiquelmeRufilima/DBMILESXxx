from __future__ import annotations
import secrets
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session, selectinload
from ..chat_models import ChatIdentity, PrivateChatMessage, UserChatContact
from ..database import get_db
from ..dependencies import current_user
from ..models import ChatMessage, WebCompany, WebUser, WebQuote, QuoteTripDetail, QuoteCommercial
from ..security import validate_csrf_token
from ..services.notifications import create_notification
from ..web import context, templates
router=APIRouter(prefix='/chat',tags=['private-chat'])

def _new_contact_id(db):
    for _ in range(60):
        v=f'DBM-{secrets.randbelow(1_000_000):06d}'
        if not db.scalar(select(ChatIdentity.user_id).where(ChatIdentity.contact_id==v)): return v
    raise RuntimeError('Não foi possível gerar ID de contato.')

def _identity(db,user):
    x=db.get(ChatIdentity,user.id)
    if x is None:
        x=ChatIdentity(user_id=user.id,contact_id=_new_contact_id(db)); db.add(x); db.commit(); db.refresh(x)
    return x

def _public(db,u,me):
    return {'id':u.id,'name':u.name,'email':u.email,'contact_id':_identity(db,u).contact_id,'role':u.role,'active':bool(u.active),'is_me':u.id==me}

def _resolve(db,me,cid):
    x=db.scalar(select(ChatIdentity).where(ChatIdentity.contact_id==str(cid or '').strip().upper()))
    if not x or x.user_id==me.id: return None
    u=db.get(WebUser,x.user_id)
    return u if u and u.active else None

def _msgs(db,me,p):
    rows=db.scalars(select(PrivateChatMessage).where(or_((PrivateChatMessage.sender_id==me.id)&(PrivateChatMessage.recipient_id==p.id),(PrivateChatMessage.sender_id==p.id)&(PrivateChatMessage.recipient_id==me.id))).order_by(desc(PrivateChatMessage.created_at)).limit(120)).all(); rows=list(reversed(rows))
    ch=False
    for r in rows:
        if r.recipient_id==me.id and not r.is_read: r.is_read=True; ch=True
    if ch: db.commit()
    return rows

def _payload(r,me):
    return {'id':r.id,'sender_id':r.sender_id,'recipient_id':r.recipient_id,'user_id':r.sender_id,'user_name':r.sender.name if r.sender else ('Você' if r.sender_id==me.id else 'Usuário'),'message':r.message,'is_read':bool(r.is_read),'created_at':r.created_at.isoformat()}

def _convs(db,me):
    rows=db.scalars(select(PrivateChatMessage).where(or_(PrivateChatMessage.sender_id==me.id,PrivateChatMessage.recipient_id==me.id)).order_by(desc(PrivateChatMessage.created_at)).limit(500)).all(); out=[]; seen=set()
    for r in rows:
        pid=r.recipient_id if r.sender_id==me.id else r.sender_id
        if pid in seen: continue
        p=db.get(WebUser,pid)
        if not p or not p.active: continue
        unread=db.scalar(select(func.count(PrivateChatMessage.id)).where(PrivateChatMessage.sender_id==p.id,PrivateChatMessage.recipient_id==me.id,PrivateChatMessage.is_read.is_(False))) or 0
        out.append({'member':_public(db,p,me.id),'last_message':r.message,'last_at':r.created_at,'unread':int(unread)}); seen.add(pid)
    return out

def _agenda(db,me):
    rows=db.scalars(select(UserChatContact).where(UserChatContact.owner_user_id==me.id).order_by(UserChatContact.created_at)).all(); out=[]
    for r in rows:
        p=db.get(WebUser,r.contact_user_id)
        if p and p.active: out.append(_public(db,p,me.id))
    return out

@router.get('')
def page(request:Request,contact:str='',view:str='conversations',db:Session=Depends(get_db)):
    me=current_user(request,db)
    if me is None:return RedirectResponse('/login',303)
    ident=_identity(db,me); company=db.get(WebCompany,me.company_id) if me.company_id else None; p=_resolve(db,me,contact); priv=_msgs(db,me,p) if p else []
    group=[]
    if company:
        group=db.scalars(select(ChatMessage).where(ChatMessage.company_id==company.id).order_by(desc(ChatMessage.created_at)).limit(100)).all(); group=list(reversed(group))
    return templates.TemplateResponse(request,'chat/index.html',context(request,user=me,company=company,has_company=bool(company),my_contact_id=ident.contact_id,conversations=_convs(db,me),contacts=_agenda(db,me),selected_contact=_public(db,p,me.id) if p else None,private_messages=priv,messages=group,chat_view='team' if view=='team' else 'conversations'))

@router.get('/sidebar')
def sidebar(request:Request,db:Session=Depends(get_db)):
    me=current_user(request,db)
    if me is None:return JSONResponse({'ok':False},401)
    return {'ok':True,'conversations':[{**x['member'],'last_message':x['last_message'],'last_at':x['last_at'].isoformat(),'unread':x['unread']} for x in _convs(db,me)],'contacts':_agenda(db,me)}

@router.post('/contacts')
async def add_contact(request:Request,db:Session=Depends(get_db)):
    me=current_user(request,db)
    if me is None:return JSONResponse({'ok':False},401)
    try:d=await request.json()
    except Exception:d={}
    if not validate_csrf_token(request.session,str(d.get('csrf_token') or '')): return JSONResponse({'ok':False,'message':'Sessão expirada.'},403)
    p=_resolve(db,me,d.get('contact_id'))
    if p is None:return JSONResponse({'ok':False,'message':'ID de contato não encontrado.'},404)
    if not db.scalar(select(UserChatContact.id).where(UserChatContact.owner_user_id==me.id,UserChatContact.contact_user_id==p.id)):
        db.add(UserChatContact(owner_user_id=me.id,contact_user_id=p.id)); db.commit()
    return {'ok':True,'contact':_public(db,p,me.id)}

@router.get('/private/{contact_id}')
def private_messages(contact_id:str,request:Request,db:Session=Depends(get_db)):
    me=current_user(request,db)
    if me is None:return JSONResponse({'ok':False},401)
    p=_resolve(db,me,contact_id)
    if p is None:return JSONResponse({'ok':False,'message':'Contato não encontrado.'},404)
    return {'ok':True,'contact':_public(db,p,me.id),'messages':[_payload(r,me) for r in _msgs(db,me,p)]}

@router.post('/private/{contact_id}')
async def send_private(contact_id:str,request:Request,db:Session=Depends(get_db)):
    me=current_user(request,db)
    if me is None:return JSONResponse({'ok':False},401)
    p=_resolve(db,me,contact_id)
    if p is None:return JSONResponse({'ok':False,'message':'Contato não encontrado.'},404)
    try:d=await request.json()
    except Exception:d={}
    if not validate_csrf_token(request.session,str(d.get('csrf_token') or '')): return JSONResponse({'ok':False,'message':'Sessão expirada.'},403)
    text=str(d.get('message') or '').strip()[:2000]
    if not text:return JSONResponse({'ok':False,'message':'Digite uma mensagem.'},400)
    if not db.scalar(select(UserChatContact.id).where(UserChatContact.owner_user_id==me.id,UserChatContact.contact_user_id==p.id)): db.add(UserChatContact(owner_user_id=me.id,contact_user_id=p.id))
    row=PrivateChatMessage(sender_id=me.id,recipient_id=p.id,message=text,is_read=False); db.add(row); db.flush()
    create_notification(db,p.id,f'Mensagem privada de {me.name}',text[:300],kind='chat',link=f'/chat?contact={_identity(db,me).contact_id}',commit=False); db.commit(); db.refresh(row)
    return {'ok':True,'message':_payload(row,me)}


@router.post('/private/messages/delete')
async def delete_private_messages(request: Request, db: Session = Depends(get_db)):
    me = current_user(request, db)
    if me is None:
        return JSONResponse({'ok': False, 'message': 'Não autenticado.'}, 401)
    try:
        data = await request.json()
    except Exception:
        data = {}
    if not validate_csrf_token(request.session, str(data.get('csrf_token') or '')):
        return JSONResponse({'ok': False, 'message': 'Sessão expirada.'}, 403)
    raw_ids = data.get('message_ids', [])
    if not isinstance(raw_ids, list) or not (1 <= len(raw_ids) <= 100):
        return JSONResponse({'ok': False, 'message': 'Selecione de 1 a 100 mensagens.'}, 400)
    try:
        ids = set(int(i) for i in raw_ids)
    except (TypeError, ValueError):
        return JSONResponse({'ok': False, 'message': 'IDs inválidos.'}, 400)
    if any(i <= 0 for i in ids):
        return JSONResponse({'ok': False, 'message': 'IDs inválidos.'}, 400)
    rows = db.scalars(select(PrivateChatMessage).where(PrivateChatMessage.id.in_(ids), PrivateChatMessage.sender_id == me.id)).all()
    if len(rows) != len(ids):
        return JSONResponse({'ok': False, 'message': 'Só é possível excluir mensagens que você enviou.'}, 403)
    for row in rows:
        db.delete(row)
    db.commit()
    return {'ok': True, 'deleted_ids': sorted(ids)}


@router.post('/group/messages/delete')
async def delete_group_messages(request: Request, db: Session = Depends(get_db)):
    me = current_user(request, db)
    if me is None or not me.company_id:
        return JSONResponse({'ok': False, 'message': 'Grupo indisponível.'}, 403)
    try:
        data = await request.json()
    except Exception:
        data = {}
    if not validate_csrf_token(request.session, str(data.get('csrf_token') or '')):
        return JSONResponse({'ok': False, 'message': 'Sessão expirada.'}, 403)
    values = data.get('message_ids', [])
    if not isinstance(values, list) or not (1 <= len(values) <= 100):
        return JSONResponse({'ok': False, 'message': 'Selecione de 1 a 100 mensagens.'}, 400)
    try:
        ids = set(int(v) for v in values)
    except (ValueError, TypeError):
        return JSONResponse({'ok': False, 'message': 'IDs inválidos.'}, 400)
    if any(i <= 0 for i in ids):
        return JSONResponse({'ok': False, 'message': 'IDs inválidos.'}, 400)
    rows = db.scalars(select(ChatMessage).where(ChatMessage.id.in_(ids), ChatMessage.company_id == me.company_id, ChatMessage.user_id == me.id)).all()
    if len(rows) != len(ids):
        return JSONResponse({'ok': False, 'message': 'Só é possível excluir mensagens suas deste grupo.'}, 403)
    for row in rows:
        db.delete(row)
    db.commit()
    return {'ok': True, 'deleted_ids': sorted(ids)}


@router.post('/quotes/forward')
async def forward_quote(request: Request, db: Session = Depends(get_db)):
    """Compartilha uma referência verificável à cotação (sem custo visível no texto)."""
    me = current_user(request, db)
    if me is None or not me.company_id:
        return JSONResponse({'ok': False, 'message': 'É necessário pertencer a uma empresa.'}, 403)
    try:
        d = await request.json()
        qid = int(d.get('quote_id'))
    except (ValueError, TypeError, AttributeError):
        return JSONResponse({'ok': False, 'message': 'Cotação inválida.'}, 400)
    if not validate_csrf_token(request.session, str(d.get('csrf_token') or '')):
        return JSONResponse({'ok': False, 'message': 'Sessão expirada.'}, 403)
    quote = db.get(WebQuote, qid)
    if not quote or quote.company_id != me.company_id:
        return JSONResponse({'ok': False, 'message': 'Cotação indisponível.'}, 404)
    target = str(d.get('target') or '').strip()
    message_text = f'✈️ Cotação compartilhada | {quote.quote_name[:100]} | {quote.origin or "—"} → {quote.destination or "—"}\n[DBM_QUOTE:{qid}]'
    if target == 'group':
        row = ChatMessage(company_id=me.company_id, user_id=me.id, message=message_text)
        db.add(row)
        recipients = db.scalars(select(WebUser).where(WebUser.company_id == me.company_id, WebUser.id != me.id, WebUser.active.is_(True))).all()
        for recipient in recipients:
            create_notification(db, recipient.id, 'Cotação compartilhada', f'{me.name} encaminhou uma cotação.', kind='chat', link='/company/chat?view=team', commit=False)
    else:
        recipient = _resolve(db, me, target)
        if not recipient or recipient.company_id != me.company_id:
            return JSONResponse({'ok': False, 'message': 'Compartilhe apenas com contatos da sua empresa.'}, 403)
        row = PrivateChatMessage(sender_id=me.id, recipient_id=recipient.id, message=message_text, is_read=False)
        db.add(row)
        create_notification(db, recipient.id, 'Cotação compartilhada', f'{me.name} encaminhou uma cotação.', kind='chat', link=f'/chat?contact={_identity(db,me).contact_id}', commit=False)
    db.commit()
    return {'ok': True, 'quote_id': qid}


def _shared_quote_for(db: Session, me: WebUser, quote_id: int):
    quote = db.scalar(select(WebQuote).where(WebQuote.id == quote_id).options(selectinload(WebQuote.trip), selectinload(WebQuote.commercial)))
    if quote is None or not me.company_id or quote.company_id != me.company_id:
        return None
    # O usuário precisa receber a cotação no grupo ou no chat privado.
    shared_tag = f'[DBM_QUOTE:{quote_id}]'
    group = db.scalar(select(ChatMessage.id).where(ChatMessage.company_id == me.company_id, ChatMessage.message.contains(shared_tag)).limit(1))
    private = db.scalar(select(PrivateChatMessage.id).where(PrivateChatMessage.message.contains(shared_tag), or_(PrivateChatMessage.recipient_id == me.id, PrivateChatMessage.sender_id == me.id)).limit(1))
    return quote if group or private else None


@router.get('/quotes/{quote_id}/view')
def quote_shared_view(quote_id: int, request: Request, db: Session = Depends(get_db)):
    from ..routers.calculations import _decorate_quote_scope, _safe_json
    from ..models import QuoteOptionIndex
    me = current_user(request, db)
    if me is None:
        return RedirectResponse('/login', 303)
    quote = _shared_quote_for(db, me, quote_id)
    if quote is None:
        return JSONResponse({'detail': 'Cotação compartilhada não disponível.'}, 404)
    quote = _decorate_quote_scope(quote)
    link = db.get(QuoteOptionIndex, quote.id)
    return templates.TemplateResponse(request, 'calculations/result.html', context(request, user=me, quote=quote, group_id=link.group_id if link else None, inputs=_safe_json(quote.input_json, {}), breakdown=_safe_json(quote.breakdown_json, {}), segments=_safe_json(quote.trip.segments_json, []) if quote.trip else [], shared_view=True))


@router.post('/quotes/{quote_id}/save')
async def save_shared_quote(quote_id: int, request: Request, db: Session = Depends(get_db)):
    me = current_user(request, db)
    if me is None:
        return JSONResponse({'ok': False}, 401)
    try:
        d = await request.json()
    except Exception:
        d = {}
    if not validate_csrf_token(request.session, str(d.get('csrf_token') or '')):
        return JSONResponse({'ok': False, 'message': 'Sessão expirada.'}, 403)
    source = _shared_quote_for(db, me, quote_id)
    if not source:
        return JSONResponse({'ok': False, 'message': 'Cotação não disponível.'}, 404)
    clone = WebQuote(user_id=me.id, company_id=me.company_id, airline_id=source.airline_id, calculation_type_id=source.calculation_type_id, quote_name=f'Cópia recebida: {source.quote_name}'[:180], origin=source.origin, destination=source.destination, passengers=source.passengers, babies=source.babies, bags=source.bags, currency=source.currency, input_json=source.input_json, breakdown_json=source.breakdown_json, total=source.total)
    db.add(clone)
    db.flush()
    if source.trip:
        t=source.trip
        db.add(QuoteTripDetail(quote_id=clone.id, travel_type=t.travel_type, departure_date=t.departure_date, return_date=t.return_date, segments_json=t.segments_json, client_name=t.client_name, client_email=t.client_email, client_phone=t.client_phone, notes=t.notes, client_person_id=None))
    if source.commercial:
        c=source.commercial
        db.add(QuoteCommercial(quote_id=clone.id, sale_value=c.sale_value, cost_basis=c.cost_basis, profit_value=c.profit_value, profit_percent=c.profit_percent, sent_to_client_at=c.sent_to_client_at, card_installments=c.card_installments or 1, card_interest_mode=c.card_interest_mode or 'cash', card_total_value=c.card_total_value, card_installment_value=c.card_installment_value, card_difference_value=c.card_difference_value, observations=c.observations))
    db.commit()
    return {'ok': True, 'saved_quote_id': clone.id, 'url': f'/calculations/result/{clone.id}'}
