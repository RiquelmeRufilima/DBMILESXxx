#!/usr/bin/env python3
"""Patch incremental DBMILESX. Não substitui main.py, MFA, estilos anteriores.
Uso: python scripts/aplicar_melhorias_pendentes.py [--dry-run] [--root .]
"""
from __future__ import annotations
import argparse
import ast
import datetime
import json
from pathlib import Path
import shutil
import sys

MARK = 'DBM-MELHORIAS-20261101'
CHANGES = {}

def replace_once(text, old, new, file):
    if old not in text:
        raise RuntimeError(f'{file}: trecho esperado não encontrado: {old[:100]!r}. Nenhum arquivo será alterado.')
    if text.count(old) != 1:
        raise RuntimeError(f'{file}: trecho ambíguo ({text.count(old)} ocorrências): {old[:70]!r}')
    return text.replace(old, new, 1)

def process(file, func):
    path = ROOT/file
    if not path.is_file(): raise RuntimeError(f'Arquivo obrigatório não encontrado: {file}')
    old = path.read_text(encoding='utf-8')
    if MARK in old:
        print(f'JÁ APLICADO: {file}')
        return
    new = func(old, file)
    if new != old: CHANGES[file] = (old, new)

def chat_html(s, f):
    s = replace_once(s, '<input class="dbm-chat-search" id="dbmChatSearch"', '''{% if has_company %}<button id="dbmNewGroup" class="secondary-button dbm-create-group" type="button">＋ Criar grupo</button>{% endif %}
      <input class="dbm-chat-search" id="dbmChatSearch"''', f)
    s = replace_once(s, '<span class="dbm-chat-status" id="dbmChatStatus"></span>', '''<span class="dbm-chat-status" id="dbmChatStatus"></span>
      <button id="dbmGroupInfo" class="secondary-button" type="button" hidden title="Participantes do grupo">👥 Participantes</button>''', f)
    s = replace_once(s, '<textarea id="dbmChatInput"', '''<div class="dbm-mention-pop" id="dbmMentionPop" role="listbox" hidden></div>
      <textarea id="dbmChatInput"''', f)
    s = replace_once(s, '<div class="dbm-reply-bar" id="dbmReplyBar" hidden></div>', '<div class="dbm-reply-bar" id="dbmReplyBar" hidden></div><button type="button" id="dbmReplyCancel" hidden>Cancelar resposta</button>', f)
    anchor = '<div class="dbm-agenda-overlay" id="dbmForwardOverlay"'
    overlay = '''<div class="dbm-agenda-overlay" id="dbmGroupOverlay" aria-hidden="true">
  <section class="dbm-agenda" role="dialog" aria-label="Criar ou gerenciar grupo">
    <header class="dbm-agenda-head"><div><h3 id="dbmGroupModalTitle">Novo grupo</h3><p id="dbmGroupModalSub">Escolha participantes</p></div><button class="dbm-close" id="dbmGroupClose" type="button">×</button></header>
    <div id="dbmGroupNameRow" class="dbm-add-contact"><label>Nome do grupo <input id="dbmGroupName" maxlength="80" placeholder="Nome do grupo"></label></div>
    <div id="dbmGroupMembersNow" class="dbm-current-group-members" hidden></div>
    <div class="dbm-add-contact"><input id="dbmGroupSearch" placeholder="Buscar membros" autocomplete="off"></div>
    <div class="dbm-fwd-list dbm-group-people" id="dbmGroupPeople"></div>
    <p id="dbmGroupNotice" role="status"></p>
    <div class="dbm-fwd-foot"><button type="button" class="ghost-button danger" id="dbmGroupLeave" hidden>Sair do grupo</button><button type="button" id="dbmGroupSave" class="primary-button">Criar grupo</button></div>
  </section>
</div>
'''
    s=replace_once(s,anchor,overlay+anchor,f)
    s = s.replace('{% block scripts %}', '''<style>
.dbm-create-group{margin:8px 16px 0;width:calc(100% - 32px)}
.dbm-mention-pop[hidden],#dbmGroupOverlay[aria-hidden="true"],#dbmGroupInfo[hidden]{display:none!important}
.dbm-compose{position:relative}.dbm-mention-pop{position:absolute;bottom:100%;left:40px;min-width:235px;max-height:230px;overflow:auto;z-index:15;background:var(--panel);border:1px solid var(--border);border-radius:12px;box-shadow:0 10px 30px #0003}
.dbm-mention-item{display:flex;gap:8px;align-items:center;width:100%;text-align:left;padding:8px;border:0;background:transparent;color:var(--text);cursor:pointer}.dbm-mention-item.active,.dbm-mention-item:hover{background:var(--panel-2)}
.dbm-mention-item small{display:block;color:var(--muted)}.dbm-group-people{max-height:350px;overflow-y:auto}.dbm-current-group-members{padding:10px;display:flex;flex-wrap:wrap;gap:5px}.dbm-current-group-members span{padding:5px;border:1px solid var(--border);border-radius:12px}
html[data-theme="light"] #dbmGroupOverlay .dbm-agenda{background:#fff!important;color:#123451!important}
</style>
{% block scripts %}''',1)
    return s+'\n<!-- '+MARK+' -->\n'

def company_py(s, f):
    # Separate unread badge, only one count query for personal messages plus group aggregation.
    old='''    return {"ok": True, "unread": int(count)}\n\n\n@router.post("/chat/contacts")'''
    new='''    groups_unread = 0
    if user.company_id:
        _ensure_chat_schema(db)
        groups_unread = int(db.scalar(select(func.count(ChatGroupMessage.id)).join(
            ChatGroupMember,
            (ChatGroupMember.group_id == ChatGroupMessage.group_id)
            & (ChatGroupMember.user_id == user.id),
        ).join(ChatGroup, ChatGroup.id == ChatGroupMessage.group_id).where(
            ChatGroup.company_id == user.company_id,
            ChatGroupMessage.id > ChatGroupMember.last_read_id,
            ChatGroupMessage.user_id != user.id,
        )) or 0)
    return {"ok": True, "unread": int(count) + groups_unread,
            "private_unread": int(count), "groups_unread": groups_unread}


@router.post("/chat/contacts")'''
    s=replace_once(s,old,new,f)
    # For the automatic aerial group add new members when chat is opened, without changing the general chat group.
    old='''    company = db.get(WebCompany, user.company_id) if user.company_id else None
    if user.company_id:
        _ensure_company_contact_ids(db, user.company_id)
'''
    new='''    company = db.get(WebCompany, user.company_id) if user.company_id else None
    if user.company_id:
        _ensure_company_contact_ids(db, user.company_id)
        from ..services.quote_activity import ensure_aerial_group
        ensure_aerial_group(db, user.company_id, user.id, create_if_missing=True)
        if db.new:
            db.commit()
'''
    s=replace_once(s,old,new,f)
    return s+'\n# '+MARK+'\n'

def notifications_py(s, f):
    s=replace_once(s,'from sqlalchemy import desc, func, select','from sqlalchemy import desc, func, select, update',f)
    old='''    offset = min(max(offset, 0), 100000)
    rows = db.scalars(select(Notification)'''
    new='''    offset = min(max(offset, 0), 100000)
    # Abrir a central zera o contador do sino. O contador do chat é independente.
    if not partial and offset == 0:
        db.execute(update(Notification).where(
            Notification.user_id == user.id, Notification.read.is_(False)
        ).values(read=True).execution_options(synchronize_session=False))
        db.commit()
        db.expire(user, ["notifications"])
    rows = db.scalars(select(Notification)'''
    s=replace_once(s,old,new,f)
    return s+'\n# '+MARK+'\n'

def base_html(s, f):
    old='<a href="/company/chat" class="nav-link {% if request.url.path == \'/company/chat\' %}active{% endif %}"><svg class="ui-icon"><use href="#icon-chat"></use></svg> Chat</a>'
    new=old.replace(' Chat</a>',' Chat <b id="dbmChatUnreadBadge" hidden></b></a>')
    s=replace_once(s,old,new,f)
    s=replace_once(s,'<script src="/static/js/chat-notifications.js?v=20261027b" defer></script>',
         '<script src="/static/js/chat-notifications.js?v=20261101a" defer></script><script src="/static/js/dbm-fast-navigation-20261101.js?v=1" defer></script>',f)
    # Keep original loader for form submits and heavy pages; delay for lighter pages only.
    s=replace_once(s,"showLoader(link.dataset.loaderMessage || 'Abrindo página...');", """if (/^\\/(?:dashboard|tags|settings|notifications|profile)(?:\\/|$)/.test(new URL(link.href).pathname)) {
        link.dataset.noLoader = '1'; // A página leve já navega sem bloqueio.
        return;
      }
      showLoader(link.dataset.loaderMessage || 'Abrindo página...');""",f)
    return s+'\n<!-- '+MARK+' -->\n'

def partner_py(s,f):
    s=replace_once(s,'''        if item.active
        and (selected_airline is None or item.id != selected_airline.id)''',
       '''        if item.active
        and str(getattr(item, "catalog_category", "airlines") or "airlines") == "airlines"
        and (selected_airline is None or item.id != selected_airline.id)''',f)
    # no object outside airline category
    s=replace_once(s,'''        if not getattr(airline, "active", True):
            continue
        if selected_airline is not None''', '''        if not getattr(airline, "active", True):
            continue
        if str(getattr(airline, "catalog_category", "airlines") or "airlines") != "airlines":
            continue
        if selected_airline is not None''',f)
    # Explicit category field for interface filters (no ORM object in JSON).
    s=replace_once(s, '''            "builtin": bool(getattr(airline, "builtin", False)),''', '''            "catalog_category": str(getattr(airline, "catalog_category", "airlines") or "airlines"),
            "builtin": bool(getattr(airline, "builtin", False)),''', f)
    return s+'\n# '+MARK+'\n'

def partner_html(s,f):
    old='''      configured: Boolean(item?.configured)
'''
    s=replace_once(s,old,'''      configured: Boolean(item?.configured),
      catalog_category: String(item?.catalog_category || 'airlines')
''',f)
    old='''      visible = options
        .filter(item => !query || norm(item.name).includes(query))'''
    new='''      const operation = String(document.getElementById('operationScopeSelect')?.value || '').toLowerCase();
      visible = options
        .filter(item => item.catalog_category === 'airlines')
        .filter(item => operation !== 'national' || /^(azul|latam|gol)(\\b|\\s)/.test(norm(item.name)))
        .filter(item => !query || norm(item.name).includes(query))'''
    s=replace_once(s,old,new,f)
    return s+'\n<!-- '+MARK+' -->\n'

def chat_notification_js(s,f):
    s=replace_once(s, "if(!baselineReady){ previousUnread=current; baselineReady=true; return; }", 
       "if(!baselineReady){ previousUnread=current; baselineReady=true; window.dispatchEvent(new CustomEvent('dbm:chat-unread',{detail:{count:current,data}})); return; }", f)
    return s+'\n// '+MARK+'\n'

def quote_activity_py(s,f):
    # Automatic aviation group instead of posting system messages into the team conversation.
    s=replace_once(s,'from ..models import ChatMessage, QuoteActivity, QuoteGroup, WebUser',
       'from ..models import ChatMessage, ChatGroup, ChatGroupMember, ChatGroupMessage, WebCompany, QuoteActivity, QuoteGroup, WebUser',f)
    anchor='''def record_quote_activity(
'''
    helper='''_AERIAL_SCHEMA_READY = False

def ensure_aerial_group(db: Session, company_id: int, actor_id: int, *, create_if_missing: bool = True):
    """Garante o grupo aéreo da empresa e seus participantes atuais.

    Só executado ao abrir o chat ou salvar uma atividade, não nas páginas normais.
    """
    if not company_id:
        return None
    global _AERIAL_SCHEMA_READY
    # Na Vercel cada instância verifica o esquema somente uma vez.
    if not _AERIAL_SCHEMA_READY:
        for table in (ChatGroup.__table__, ChatGroupMember.__table__, ChatGroupMessage.__table__):
            table.create(bind=db.get_bind(), checkfirst=True)
        _AERIAL_SCHEMA_READY = True
    company = db.get(WebCompany, company_id)
    if not company:
        return None
    group_name = f"Grupo aéreo da {company.name}"[:80]
    existing = db.scalar(select(ChatGroup).where(
        ChatGroup.company_id == company_id, ChatGroup.name == group_name).limit(1))
    if existing is None:
        if not create_if_missing:
            return None
        existing = ChatGroup(company_id=company_id, name=group_name, created_by=actor_id)
        db.add(existing)
        db.flush()
    member_ids = set(db.scalars(select(ChatGroupMember.user_id).where(
        ChatGroupMember.group_id == existing.id)).all())
    people = db.scalars(select(WebUser.id).where(
        WebUser.company_id == company_id, WebUser.active.is_(True))).all()
    for person_id in people:
        if person_id not in member_ids:
            db.add(ChatGroupMember(group_id=existing.id, user_id=person_id,
                                   is_admin=person_id == actor_id, last_read_id=0))
    return existing


'''
    s=replace_once(s,anchor,helper+anchor,f)
    old='''    should_chat = event in CHAT_ACTIVITY_EVENTS if send_to_chat is None else bool(send_to_chat)
    if not should_chat or not actor.company_id:
        return None, None
'''
    new='''    # Todas as ações de cotações com auditoria vão para o grupo AÉREO.
    # O grupo tradicional da empresa recebe somente conversa humana.
    if actor.company_id and record_audit and group is not None:
        aerial = ensure_aerial_group(db, actor.company_id, actor.id)
        if aerial:
            db.add(ChatGroupMessage(group_id=aerial.id, user_id=actor.id, message=text))
            db.flush()
    return None, None  # JS atual já consulta novos grupos incrementalmente.

    should_chat = event in CHAT_ACTIVITY_EVENTS if send_to_chat is None else bool(send_to_chat)
    if not should_chat or not actor.company_id:
        return None, None
'''
    s=replace_once(s,old,new,f)
    # Remove fluxo antigo que publicava eventos no chat de conversas.
    start=s.index('    should_chat = event in CHAT_ACTIVITY_EVENTS', s.index('def record_quote_activity('))
    end=s.index('async def publish_quote_activity(',start)
    s=s[:start]+s[end:]
    return s+'\n# '+MARK+'\n'

def history_html(s,f):
    # Replace only author line on option cards; avoid removing audit info from other pages.
    s=replace_once(s,'''<small class="quote-option-author">Calculado por <strong>{{ quote.user.name if quote.user else 'Usuário não identificado' }}</strong></small>''',
      '''<label class="dbm-entry-inline">Entrada (Pix/R$)
       <input class="dbm-quick-entry" inputmode="decimal" type="text" aria-label="Entrada por Pix"
         data-quote-id="{{ quote.id }}"
         value="{{ ((quote.commercial.observations|from_json({})).get('entry_amount', 0) if quote.commercial else 0)|money('BRL') }}"
         placeholder="R$ 0,00" title="Sincronizada com Editar lucro"></label>''',f)
    # lightweight entry component in modal (same field also in historical card)
    s=replace_once(s,'''      <div class="profit-grid">
        <label>Condição<select name="card_interest_mode"''',
      '''      <div class="profit-grid"><label>Entrada (Pix / dinheiro) em R$
        <input type="text" inputmode="decimal" name="entry_amount" id="profitEntryAmount" value="0,00" placeholder="0,00"></label>
        <div class="dbm-entry-explain">Valor que o cliente paga fora do cartão. O saldo é parcelado no cartão.</div></div>
      <div class="profit-grid">
        <label>Condição<select name="card_interest_mode"''',f)
    # button data for both editing and quick control - repeat all occurrences intentionally
    s=s.replace('data-card-difference="{{ quote.commercial.card_difference_value if quote.commercial and quote.commercial.card_difference_value is not none else 0 }}"',
      'data-card-difference="{{ quote.commercial.card_difference_value if quote.commercial and quote.commercial.card_difference_value is not none else 0 }}" data-entry-amount="{{ (quote.commercial.observations|from_json({})).get(\'entry_amount\',0) if quote.commercial else 0 }}"')
    # first_profit_quote button
    s=s.replace('data-card-difference="{{ first_profit_quote.commercial.card_difference_value if first_profit_quote.commercial and first_profit_quote.commercial.card_difference_value is not none else 0 }}"',
      'data-card-difference="{{ first_profit_quote.commercial.card_difference_value if first_profit_quote.commercial and first_profit_quote.commercial.card_difference_value is not none else 0 }}" data-entry-amount="{{ (first_profit_quote.commercial.observations|from_json({})).get(\'entry_amount\',0) if first_profit_quote.commercial else 0 }}"')
    s=replace_once(s,"  const inst = document.getElementById('cardInstallments');", "  const inst = document.getElementById('cardInstallments');\n  const entryInput = document.getElementById('profitEntryAmount');",f)
    s=replace_once(s,"  const cashSale = () => cost + Math.max(0, num(valueInput.value));",'''  const cashSale = () => cost + Math.max(0, num(valueInput.value));
  const entrySale = () => Math.min(cashSale(), Math.max(0, num(entryInput?.value)));
  const cardBase = () => Math.max(0, cashSale() - entrySale());''',f)
    # financeState only: replace sale basis for card while preserving sale full total (all 5 occurrences in function)
    begin=s.index('  function financeState('); end=s.index('\n  function syncCard(',begin)
    fragment=s[begin:end]
    fragment=fragment.replace('const sale = cashSale();','const sale = cashSale();\n    const basis = cardBase();\n    if (entryInput) entryInput.max = sale;')
    fragment=fragment.replace('total = sale;','total = basis;')
    fragment=fragment.replace('total = sale + difference;','total = basis + difference;')
    fragment=fragment.replace('total - sale','total - basis')
    fragment=fragment.replace('Math.max(sale, total)','Math.max(basis, total)')
    fragment=fragment.replace('Math.max(sale, source', 'Math.max(basis, source')
    fragment=fragment.replace('sale + difference : total || sale','basis + difference : total || basis')
    fragment=fragment.replace('normalizedTotal - sale','normalizedTotal - basis')
    fragment=fragment.replace('sale > 0 ? normalizedDifference / sale * 100', 'basis > 0 ? normalizedDifference / basis * 100')
    fragment=fragment.replace('`${money(sale)} • sem juros`','`${money(entrySale())} de entrada + ${money(basis)} no cartão`')
    fragment=fragment.replace('`Total ${money(normalizedTotal)} • mesmo valor da venda à vista`','`Entrada ${money(entrySale())} + cartão ${money(normalizedTotal)} sem juros`')
    fragment=fragment.replace('      sale,\n      total:', '      sale,\n      entry: entrySale(),\n      basis,\n      total:')
    s=s[:begin]+fragment+s[end:]
    s=replace_once(s,'"    mode.value = btn.dataset.cardMode || \'cash\';"' if False else "    mode.value = btn.dataset.cardMode || 'cash';", "    mode.value = btn.dataset.cardMode || 'cash';\n    entryInput.value = dec(Math.max(0,num(btn.dataset.entryAmount)));",f)
    s=replace_once(s,"  mode?.addEventListener('change', () => syncCard('mode', true));", "  entryInput?.addEventListener('input', () => syncCard('difference', false));\n  entryInput?.addEventListener('blur', () => { entryInput.value = dec(entrySale()); syncCard('difference', true); });\n  mode?.addEventListener('change', () => syncCard('mode', true));",f)
    s=replace_once(s,"      btn.dataset.cardDifference = String(item.card_difference_value || 0);", "      btn.dataset.cardDifference = String(item.card_difference_value || 0);\n      btn.dataset.entryAmount = String(item.entry_amount || 0);",f)
    s=replace_once(s,"      data.set('card_total_value', String(finance.total));", "      data.set('entry_amount', String(finance.entry));\n      data.set('card_total_value', String(finance.total));",f)
    # Sync quick control with modal. user saves using normal profit save; avoids silent financial edits.
    s=replace_once(s,"  document.querySelectorAll('.js-profit-open').forEach(btn => btn.addEventListener('click', () => showProfitDialog(btn)));", '''  document.querySelectorAll('.js-profit-open').forEach(btn => btn.addEventListener('click', () => showProfitDialog(btn)));
  document.querySelectorAll('.dbm-quick-entry').forEach((field) => {
    field.addEventListener('click', event => event.stopPropagation());
    field.addEventListener('change', () => {
      const btn = document.querySelector(`.js-profit-open[data-quote-id="${Number(field.dataset.quoteId)}"]`);
      if (!btn) return;
      showProfitDialog(btn);
      entryInput.value = dec(Math.min(cashSale(), Math.max(0, num(field.value))));
      syncCard('difference', true);
      field.value = money(Math.max(0,num(btn.dataset.entryAmount)));
      // A confirmação permanece no modal; não salvamos valores financeiros sem confirmação.
      entryInput.focus();
    });
  });''',f)
    s=replace_once(s,"      btn.dataset.entryAmount = String(item.entry_amount || 0);", "      btn.dataset.entryAmount = String(item.entry_amount || 0);\n      document.querySelectorAll(`.dbm-quick-entry[data-quote-id=\"${Number(item.quote_id)}\"]`).forEach(field => {field.value = money(Number(item.entry_amount || 0));});",f)
    # modal preview says 
    s=s.replace('O campo <strong>Juros / diferença</strong> é somado ao valor à vista para formar o total no cartão.',
       'A entrada (Pix/dinheiro) é descontada antes do cartão. Os juros incidem apenas sobre o saldo do cartão.')
    s=s.replace('Total = venda à vista + juros','Cartão = venda à vista − entrada + juros')
    s=s.replace('profit-card-note">','profit-card-note">',1)
    # O total zero é válido (por exemplo entrada 100% no Pix).
    s=replace_once(s, '    const total = Number(item.card_total_value || sale);',
      '    const entry = Math.max(0, Number(item.entry_amount || 0));\n    const basis = Math.max(0, sale - entry);\n    const total = Number(item.card_total_value ?? basis);', f)
    s=replace_once(s, '    const differencePercent = sale > 0 ? (difference / sale * 100) : 0;',
       '    const differencePercent = basis > 0 ? (difference / basis * 100) : 0;', f)
    s=replace_once(s, '      btn.dataset.cardTotal = String(item.card_total_value || item.sale_value || item.cost || 0);',
       '      btn.dataset.cardTotal = String(item.card_total_value ?? Math.max(0, Number(item.sale_value ?? item.cost ?? 0) - Number(item.entry_amount || 0)));', f)
    s=replace_once(s, '    cardTotal.value = dec(Math.max(0, num(btn.dataset.cardTotal)) || cost + profit);',
       '    cardTotal.value = dec(Math.max(0, Number(btn.dataset.cardTotal ?? cost + profit)));', f)
    s=replace_once(s, '    cardDifference.value = dec(Math.max(0, num(btn.dataset.cardDifference)) || Math.max(0, num(btn.dataset.cardTotal) - (cost + profit)));',
       '    cardDifference.value = dec(Math.max(0, Number(btn.dataset.cardDifference ?? 0)));', f)
    s=replace_once(s, "    data.set('card_total_value', String(cost));",
       "    data.set('entry_amount', '0');\n    data.set('card_total_value', String(cost));", f)
    s=s.replace('      ${payment}`;', "      ${entry > 0 ? `<span class=\"profit-entry-chip\">Entrada ${money(entry)} • Cartão ${money(total)}</span>` : ''}\n      ${payment}`;")
    # include CSS at end (after last script)
    s += '''\n<style> .profit-entry-chip{display:inline-flex;color:#087449;font-weight:800;font-size:.74rem}.dbm-entry-inline{display:inline-flex;align-items:center;flex-wrap:wrap;gap:7px;color:var(--text);font-size:.8rem;font-weight:700}.dbm-quick-entry{width:125px;max-width:100%;border-radius:8px;border:1px solid #9acbc2;background:var(--panel);color:var(--text);padding:6px 8px;font-weight:850}.dbm-entry-explain{align-self:center;font-size:.79rem;color:var(--muted)} html[data-theme="light"] .dbm-entry-inline{color:#154266} html[data-theme="light"] .profit-dialog .dbm-entry-explain{color:#315875!important} </style>\n<!-- '''+MARK+''' -->\n'''
    return s

def history_modern_html(s,f):
    """Tela mais recente: modal de lucro está em _profit_modal_shared.html."""
    s=replace_once(s,'''<small class="quote-option-author">Calculado por <strong>{{ quote.user.name if quote.user else 'Usuário não identificado' }}</strong></small>''',
      '''<label class="dbm-entry-inline">Entrada (Pix/R$)
        <input class="dbm-quick-entry" inputmode="decimal" type="text" aria-label="Entrada por Pix"
         data-quote-id="{{ quote.id }}"
         value="{{ ((quote.commercial.observations|from_json({})).get('entry_amount', 0) if quote.commercial else 0)|money('BRL') }}"
         placeholder="R$ 0,00" title="Abra Editar lucro para confirmar alterações"></label>''', f)
    # In the latest template, commercial metadata is in the existing button dataset.
    s=s.replace('''data-commercial-meta="{{ quote.commercial.observations if quote.commercial and quote.commercial.observations else '{}' }}"''',
      '''data-commercial-meta="{{ quote.commercial.observations if quote.commercial and quote.commercial.observations else '{}' }}"''')
    # Make zero total valid, rather than falling back to full cash sale.
    s=s.replace('''(c.card_total_value or c.sale_value or quote.total)|money(quote.currency)''',
      '''(c.card_total_value if c.card_total_value is not none else (c.sale_value or quote.total))|money(quote.currency)''')
    s += '''\n<style>
.dbm-entry-inline{display:inline-flex;align-items:center;flex-wrap:wrap;gap:7px;font-size:.8rem;font-weight:700;color:var(--text)}
.dbm-quick-entry{width:128px;max-width:100%;border:1px solid #9acbc2;border-radius:8px;background:var(--panel);color:var(--text);padding:6px 8px;font-weight:850}
html[data-theme="light"] .dbm-entry-inline{color:#154266}
</style>\n<!-- '''+MARK+''' -->\n'''
    return s


def shared_profit_html(s,f):
    # Add entry control outside machine section to preserve existing card processor.
    old='''      <div class="profit-grid">
        <label>Condição<select name="card_interest_mode"'''
    new='''      <div class="profit-grid">
        <label>Entrada (Pix / dinheiro) em R$
          <input type="text" name="entry_amount" id="profitEntryAmount" inputmode="decimal" value="0,00" placeholder="0,00"></label>
        <div class="dbm-entry-explain">Valor recebido por Pix ou dinheiro, descontado do saldo a cobrar no cartão.</div>
      </div>
      <div class="profit-grid">
        <label>Condição<select name="card_interest_mode"'''
    s=replace_once(s,old,new,f)
    s=replace_once(s,'''  const inst = document.getElementById('cardInstallments');''',
      '''  const inst = document.getElementById('cardInstallments');
  const entryInput = document.getElementById('profitEntryAmount');''',f)
    s=replace_once(s,'''  const cashSale = () => cost + Math.max(0, num(valueInput.value));''',
      '''  const cashSale = () => cost + Math.max(0, num(valueInput.value));
  const entrySale = () => Math.min(cashSale(), Math.max(0, num(entryInput?.value)));
  const cardBase = () => Math.max(0, cashSale() - entrySale());''',f)
    # An enabled machine rate must apply only to the card amount.
    s=replace_once(s,'''    const sale=cashSale();
    const total=passFees.checked ? Math.round(sale/(1-rate/100)*100)/100 : sale;''',
      '''    const sale=cardBase();
    const total=passFees.checked ? Math.round(sale/(1-rate/100)*100)/100 : sale;''',f)
    s=replace_once(s,'''    const sale = cashSale();
    let times =''',
      '''    const sale = cashSale();
    const basis = cardBase();
    let times =''',f)
    begin=s.index('  function financeState(');end=s.index('\n  function syncCard(',begin)
    frag=s[begin:end]
    frag=frag.replace('total = sale;', 'total = basis;')
    frag=frag.replace('total = sale + difference;', 'total = basis + difference;')
    frag=frag.replace('total - sale','total - basis')
    frag=frag.replace('Math.max(sale, total)','Math.max(basis, total)')
    frag=frag.replace('Math.max(sale, source','Math.max(basis, source')
    frag=frag.replace('sale + difference : total || sale','basis + difference : total || basis')
    frag=frag.replace('normalizedTotal - sale','normalizedTotal - basis')
    frag=frag.replace('sale > 0 ? normalizedDifference / sale * 100','basis > 0 ? normalizedDifference / basis * 100')
    frag=frag.replace('`${money(sale)} • sem juros`','`${money(entrySale())} de entrada + ${money(basis)} no cartão`')
    frag=frag.replace('`Total ${money(normalizedTotal)} • mesmo valor da venda à vista`','`Entrada ${money(entrySale())} + cartão ${money(normalizedTotal)} sem juros`')
    frag=frag.replace('      sale,\n      total:', '      sale,\n      entry:entrySale(),\n      basis,\n      total:')
    s=s[:begin]+frag+s[end:]
    s=replace_once(s,'''    cardTotal.value = dec(Math.max(0, num(btn.dataset.cardTotal)) || cost + profit);''',
      '''    cardTotal.value = dec(Math.max(0, Number(btn.dataset.cardTotal ?? cost + profit)));''',f)
    s=replace_once(s,'''    cardDifference.value = dec(Math.max(0, num(btn.dataset.cardDifference)) || Math.max(0, num(btn.dataset.cardTotal) - (cost + profit)));''',
      '''    cardDifference.value = dec(Math.max(0, Number(btn.dataset.cardDifference ?? 0)));''',f)
    s=replace_once(s,'''    anchorInput.value=Number(metadata.anchor_value||0)>0?dec(metadata.anchor_value):'';''',
      '''    anchorInput.value=Number(metadata.anchor_value||0)>0?dec(metadata.anchor_value):'';
    entryInput.value=dec(Math.max(0,Number(metadata.entry_amount||0)));''',f)
    # Don't introduce extra DB calls while typing; only recompute in browser.
    s=replace_once(s,'''  mode?.addEventListener('change', () => syncCard('mode', true));''',
      '''  entryInput?.addEventListener('input',()=>{ if(machineEnabled.checked)simulateMachine();syncCard(machineEnabled.checked?'total':'difference',false); });
  entryInput?.addEventListener('blur',()=>{entryInput.value=dec(entrySale());if(machineEnabled.checked)simulateMachine();syncCard(machineEnabled.checked?'total':'difference',true);});
  mode?.addEventListener('change', () => syncCard('mode', true));''',f)
    s=replace_once(s,'''      data.set('card_total_value', String(finance.total));''',
      '''      data.set('entry_amount', String(finance.entry));
      data.set('card_total_value', String(finance.total));''',f)
    s=replace_once(s,'''    data.set('card_total_value', String(cost));''',
      '''    data.set('entry_amount','0');
    data.set('card_total_value', String(cost));''',f)
    s=replace_once(s,'''      btn.dataset.cardTotal = String(item.card_total_value || item.sale_value || item.cost || 0);''',
      '''      btn.dataset.cardTotal = String(item.card_total_value ?? Math.max(0,Number(item.sale_value ?? item.cost ?? 0)-Number(item.entry_amount||0)));''',f)
    s=replace_once(s,'''      btn.dataset.commercialMeta = JSON.stringify({anchor_value:item.anchor_value||0,machine_name:item.machine_name||''});''',
      '''      btn.dataset.commercialMeta = JSON.stringify({anchor_value:item.anchor_value||0,machine_name:item.machine_name||'',entry_amount:item.entry_amount||0});
      document.querySelectorAll(`.dbm-quick-entry[data-quote-id="${Number(item.quote_id)}"]`).forEach(field=>{field.value=money(Number(item.entry_amount||0))});''',f)
    s=replace_once(s,'''  document.querySelectorAll('.js-profit-open').forEach(btn => btn.addEventListener('click', () => showProfitDialog(btn)));''',
      '''  document.querySelectorAll('.js-profit-open').forEach(btn => btn.addEventListener('click', () => showProfitDialog(btn)));
  document.querySelectorAll('.dbm-quick-entry').forEach(field=>{
    field.addEventListener('click',event=>event.stopPropagation());
    field.addEventListener('change',()=>{
      const btn=document.querySelector(`.js-profit-open[data-quote-id="${Number(field.dataset.quoteId)}"]`);
      if(!btn)return;
      showProfitDialog(btn);
      entryInput.value=dec(Math.min(cashSale(),Math.max(0,num(field.value))));
      if(machineEnabled.checked)simulateMachine();
      syncCard(machineEnabled.checked?'total':'difference',true);
      field.value=money(Number(JSON.parse(btn.dataset.commercialMeta||'{}').entry_amount||0));
      entryInput.focus();
    });
  });''',f)
    s=replace_once(s,'''    const total = Number(item.card_total_value || sale);''',
      '''    const entry = Math.max(0,Number(item.entry_amount||0));
    const basis = Math.max(0,sale-entry);
    const total = Number(item.card_total_value ?? basis);''',f)
    s=replace_once(s,'''    const differencePercent = sale > 0 ? (difference / sale * 100) : 0;''',
      '''    const differencePercent = basis > 0 ? (difference / basis * 100) : 0;''',f)
    s=s.replace('      ${payment}`;', "      ${entry>0?`<span class=\"profit-entry-chip\">Entrada ${money(entry)} • Cartão ${money(total)}</span>`:''}\\n      ${payment}`;")
    s=s.replace('Total = venda à vista + juros','Cartão = venda à vista − entrada + juros')
    s=s.replace('O campo <strong>Juros / diferença</strong> é somado ao valor à vista para formar o total no cartão.',
      'A entrada (Pix/dinheiro) é descontada antes do cartão e as taxas incidem sobre o saldo cobrado no cartão.')
    s+='''\n<style>.dbm-entry-explain{align-self:center;font-size:.77rem;color:var(--muted)} .profit-entry-chip{display:inline-flex;color:#087449;font-weight:800;font-size:.74rem} html[data-theme="light"] .profit-dialog .dbm-entry-explain{color:#315875!important}</style>
<!-- '''+MARK+''' -->\n'''
    return s

def calculations_py(s,f):
    old='''        entered_total = max(
            0.0,
            _commercial_number(
                form.get("card_total_value")
            ),
        )'''
    new='''        # Entrada Pix/dinheiro: reduz o saldo a cobrar no cartão.
        # Persistida em observations JSON, sem migração do banco Neon.
        entry_amount = round(max(0.0, min(cash_sale,
            _commercial_number(form.get("entry_amount")))), 2)
        card_basis = round(cash_sale - entry_amount, 2)

'''+old
    s=replace_once(s,old,new,f)
    start=s.index('        # RELAÇÃO:\n        #\n        # TOTAL CARTÃO = VENDA À VISTA + JUROS')
    end=s.index('        difference_percent = (',start)
    frag=s[start:end]
    frag=frag.replace('TOTAL CARTÃO = VENDA À VISTA + JUROS', 'TOTAL CARTÃO = VENDA À VISTA - ENTRADA + JUROS')
    frag=frag.replace('card_total = cash_sale','card_total = card_basis')
    frag=frag.replace('cash_sale + difference','card_basis + difference')
    frag=frag.replace('                        cash_sale,','                        card_basis,')
    frag=frag.replace('card_total - cash_sale','card_total - card_basis')
    frag=frag.replace('max(\n                    cash_sale,\n                    entered_total or cash_sale,',
                          'max(\n                    card_basis,\n                    entered_total or card_basis,')
    s=s[:start]+frag+s[end:]
    # variable profit percent difference divide by card basis
    s=replace_once(s,'''            difference / cash_sale * 100
            if cash_sale > 0''', '''            difference / card_basis * 100
            if card_basis > 0''',f)
    # apply all proportional entry; keep difference percent on balance
    old='''                # juros proporcionais no "aplicar todos"

                if apply_all:'''
    new='''                # A entrada proporcional por opção é descontada antes dos juros.
                target_entry = (round(entry_amount * target_sale / cash_sale, 2)
                                if apply_all and cash_sale > 0 else entry_amount)
                target_entry = min(target_sale, max(0.0, target_entry))
                target_card_basis = round(target_sale - target_entry, 2)

                # juros proporcionais no "aplicar todos"

                if apply_all:'''
    s=replace_once(s,old,new,f)
    s=replace_once(s,'''                        target_sale
                        * difference_percent''', '''                        target_card_basis
                        * difference_percent''',f)
    # os dois ramos devem usar o saldo, não a venda total
    s=s.replace("                        target_sale\n                        + target_difference", "                        target_card_basis\n                        + target_difference")
    s=replace_once(s,'''                    previous_meta.pop("anchor_value", None)''', '''                    previous_meta.pop("entry_amount", None)
                    previous_meta.pop("anchor_value", None)''',f)
    s=replace_once(s,'''                    "machine_name": machine_name,
                })''', '''                    "machine_name": machine_name,
                    "entry_amount": round(target_entry, 2),
                })''',f)
    s=replace_once(s,'''                        "card_installments":
                            installments,''', '''                        "entry_amount": target_entry,
                        "card_installments":
                            installments,''',f)
    # Porcentagem de juros calculada sobre o saldo do cartão.
    s=replace_once(s, "                            or target_sale <= 0", "                            or target_card_basis <= 0", f)
    s=replace_once(s, "                                / target_sale\n                                * 100,", "                                / target_card_basis\n                                * 100,", f)
    # response payload: one occurrence only
    old='''                    "card_total_value":
                        target_card_total,'''
    s=replace_once(s,old,'''                    "entry_amount": 0 if remove_commercial else target_entry,
                    "card_total_value":
                        target_card_total,''',f)
    return s+'\n# '+MARK+'\n'

# external module is new; script copies it as part install, no existing overwrites
NEW_NAV='''(() => {
  // Links leves: transição sem loader bloqueante, preserva as navegações normais.
  const badge = document.getElementById('dbmChatUnreadBadge');
  function updateBadge(n){if(!badge)return;const count=Math.max(0,Number(n)||0);badge.textContent=String(Math.min(99,count))+(count>99?'+':'');badge.hidden=!count;}
  window.addEventListener('dbm:chat-unread', e => updateBadge(e.detail?.count));
  // Renderização progressiva para listas muito longas, apenas quando necessário.
  if (/^\\/(?:calculations\\/history|cadastros\\/cotacoes)/.test(location.pathname)) {
    const style=document.createElement('style');
    style.textContent='@supports (content-visibility:auto){.history-group-card,.quote-option-card{content-visibility:auto;contain-intrinsic-size:auto 260px}}';
    document.head.append(style);
  }
  // Retomada da aba usa atualização normal da aplicação, sem polling adicional.
})();
'''

def main():
    parser=argparse.ArgumentParser(description='Instalador incremental: entrada Pix, grupos, parceiros, notificações e navegação.')
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--root',default='.')
    args=parser.parse_args()
    global ROOT
    ROOT=Path(args.root).resolve()
    jobs={
        'app/templates/company/chat.html':chat_html,
        'app/routers/company.py':company_py,
        'app/routers/notifications.py':notifications_py,
        'app/templates/base.html':base_html,
        'app/routers/calculations.py':lambda s,f: calculations_py(partner_py(s,f),f),
        'app/templates/calculations/new.html':partner_html,
        'app/services/quote_activity.py':quote_activity_py,
        'app/static/js/chat-notifications.js': chat_notification_js,
        'app/templates/calculations/history.html':lambda s,f: history_modern_html(s,f) if '_profit_modal_shared.html' in s else history_html(s,f),
    }
    try:
        for file, func in jobs.items(): process(file,func)
        if '_profit_modal_shared.html' in (ROOT/'app/templates/calculations/history.html').read_text(encoding='utf-8'):
            process('app/templates/calculations/_profit_modal_shared.html', shared_profit_html)
        module='app/static/js/dbm-fast-navigation-20261101.js'
        if not (ROOT/module).exists(): CHANGES[module]=(None,NEW_NAV)
        for file, (_,new) in CHANGES.items():
            if file.endswith('.py'): ast.parse(new, filename=file)
        if not CHANGES:
            print('Nada a alterar: atualização já aplicada.');return
        print('Mudanças previstas:')
        for file in CHANGES:print(' -',file)
        if args.dry_run:
            print('DRY-RUN OK: nenhuma alteração feita.');return
        backups=ROOT/('backup_melhorias_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S'))
        for file,(old,new) in CHANGES.items():
            dest=ROOT/file
            dest.parent.mkdir(parents=True,exist_ok=True)
            if old is not None:
                backup=backups/file
                backup.parent.mkdir(parents=True,exist_ok=True)
                backup.write_text(old,encoding='utf-8')
        for file,(_,new) in CHANGES.items():
            dest=ROOT/file
            tmp=dest.with_suffix(dest.suffix+'.tmp_melhorias')
            tmp.write_text(new,encoding='utf-8')
            tmp.replace(dest)
        print('INSTALAÇÃO OK. Backup local:',backups)
    except Exception as ex:
        print('INSTALAÇÃO NÃO APLICADA:',ex,file=sys.stderr)
        sys.exit(2)

if __name__=='__main__':main()
