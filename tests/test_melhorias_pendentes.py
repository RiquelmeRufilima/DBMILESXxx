from sqlalchemy import create_engine,select,func
from sqlalchemy.orm import Session
from app.database import Base
from app.models import WebCompany,WebUser,QuoteGroup,ChatGroup,ChatGroupMember,ChatGroupMessage,ChatMessage
from app.services import quote_activity
from app.routers import company

def test_aerial_group_only_log():
  eng=create_engine('sqlite+pysqlite:///:memory:')
  Base.metadata.create_all(eng)
  with Session(eng) as db:
    co=WebCompany(name='Empresa test');db.add(co);db.flush()
    users=[WebUser(email=f'g{i}@example.test', name=f'G{i}', password_hash='x',company_id=co.id) for i in range(2)]
    db.add_all(users);db.flush()
    gr=QuoteGroup(user_id=users[0].id,company_id=co.id,quote_name='ABC',origin='FOR',destination='GRU')
    db.add(gr);db.flush()
    quote_activity._AERIAL_SCHEMA_READY=False
    quote_activity.record_quote_activity(db, users[0],gr,'Cotação criada',event='quote_created')
    db.flush()
    assert db.scalar(select(func.count(ChatMessage.id))) == 0
    aerial=db.scalar(select(ChatGroup))
    assert aerial.name=='Grupo aéreo da Empresa test'
    assert db.scalar(select(func.count(ChatGroupMessage.id))) == 1
    assert set(db.scalars(select(ChatGroupMember.user_id))) == {u.id for u in users}
    import types
    before=company.current_user
    company.current_user=lambda *args:users[1]
    try:
      response=company.chat_unread_api(None,db)
      assert response['groups_unread']==1, response
    finally:company.current_user=before


def test_entrada_pix_reduz_saldo_cartao_sem_mudar_lucro(monkeypatch):
  import asyncio, json
  from types import SimpleNamespace
  from sqlalchemy import create_engine
  from app.database import Base
  from app.models import WebCompany,WebUser,WebQuote
  from app.routers import calculations
  eng=create_engine('sqlite+pysqlite:///:memory:')
  Base.metadata.create_all(eng)
  with Session(eng) as db:
    co=WebCompany(name='Financeiro');db.add(co);db.flush()
    user=WebUser(email='financeiro@example.test', name='Admin',password_hash='x', company_id=co.id)
    db.add(user);db.flush()
    quote=WebQuote(user_id=user.id,company_id=co.id,quote_name='Voo',origin='FOR',destination='GRU',total=974,passengers=1)
    db.add(quote);db.flush()
    monkeypatch.setattr(calculations,'current_user',lambda request, db:user)
    monkeypatch.setattr(calculations,'validate_csrf_token',lambda *a:True)
    fields={'csrf_token':'ok','profit_value':'185,06','profit_percent':'19','profit_source':'value',
      'card_interest_mode':'with_interest','card_installments':'3',
      'entry_amount':'200,00','card_difference_value':'55,00','card_value_source':'difference'}
    async def form():return fields
    req=SimpleNamespace(headers={'x-requested-with':'XMLHttpRequest'},session={},form=form)
    out=asyncio.run(calculations.save_option_profit(quote.id,req,db))
    payload=json.loads(out.body)
    assert payload['ok'], payload
    item=payload['items'][0]
    assert round(item['sale_value'],2)==1159.06
    assert round(item['entry_amount'],2)==200
    assert round(item['card_total_value'],2)==1014.06
    assert round(item['card_difference_value'],2)==55
    db.refresh(quote)
    assert json.loads(quote.commercial.observations)['entry_amount']==200
    # Entrada igual à venda total: cartão zero, sem juros.
    fields.update({'entry_amount':'1159,06','card_interest_mode':'cash','card_installments':'1',
                   'card_difference_value':'0','card_value_source':'difference'})
    out=asyncio.run(calculations.save_option_profit(quote.id,req,db))
    payload=json.loads(out.body)
    assert payload['ok'],payload
    assert payload['items'][0]['card_total_value']==0


def test_abrir_notificacoes_zera_sino_sem_marcar_chat(monkeypatch):
  from sqlalchemy import create_engine, select, func
  from sqlalchemy.orm import Session
  from app.database import Base
  from app.models import WebCompany, WebUser, Notification, PrivateChatMessage
  from app.routers import notifications
  eng=create_engine('sqlite+pysqlite:///:memory:')
  Base.metadata.create_all(eng)
  with Session(eng) as db:
    co=WebCompany(name='Empresa teste');db.add(co);db.flush()
    u1=WebUser(name='A',email='a2@ex.test',password_hash='x',company_id=co.id)
    u2=WebUser(name='B',email='b2@ex.test',password_hash='x',company_id=co.id)
    db.add_all([u1,u2]);db.flush()
    db.add(Notification(user_id=u2.id,title='Alerta', message='Teste',kind='general',read=False))
    db.add(PrivateChatMessage(sender_id=u1.id, recipient_id=u2.id, message='Mensagem', is_read=False))
    db.commit()
    monkeypatch.setattr(notifications, 'current_user', lambda req, db:u2)
    monkeypatch.setattr(notifications, 'context', lambda *a, **kw:kw)
    monkeypatch.setattr(notifications.templates, 'TemplateResponse', lambda *a,**kw:object())
    notifications.notifications_page(object(), db=db)
    assert db.scalar(select(func.count(Notification.id)).where(Notification.user_id==u2.id,Notification.read.is_(False)))==0
    assert db.scalar(select(func.count(PrivateChatMessage.id)).where(PrivateChatMessage.recipient_id==u2.id,PrivateChatMessage.is_read.is_(False)))==1
