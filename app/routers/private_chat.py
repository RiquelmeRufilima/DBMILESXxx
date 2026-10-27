from __future__ import annotations
import secrets
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session
from ..chat_models import ChatIdentity, PrivateChatMessage, UserChatContact
from ..database import get_db
from ..dependencies import current_user
from ..models import ChatMessage, WebCompany, WebUser
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
