(() => {
  const shell = document.getElementById('dbmChatV2');
  if (!shell) return;

  const userId = Number(shell.dataset.userId || 0);
  const csrf = shell.dataset.csrf || '';
  const hasCompany = shell.dataset.hasCompany === '1';
  const companyName = shell.dataset.companyName || 'Chat da equipe';

  const list = document.getElementById('dbmChatMessages');
  const form = document.getElementById('dbmChatForm');
  const input = document.getElementById('dbmChatInput');
  const title = document.getElementById('dbmChatTitle');
  const subtitle = document.getElementById('dbmChatSubtitle');
  const status = document.getElementById('dbmChatStatus');
  const avatar = document.getElementById('dbmHeaderAvatar');
  const back = document.getElementById('dbmChatBack');
  const search = document.getElementById('dbmChatSearch');

  const overlay = document.getElementById('dbmAgendaOverlay');
  const openAgenda = document.getElementById('dbmOpenAgenda');
  const closeAgenda = document.getElementById('dbmCloseAgenda');
  const addContact = document.getElementById('dbmAddContact');
  const contactInput = document.getElementById('dbmContactIdInput');
  const agendaMessage = document.getElementById('dbmAgendaMessage');

  let view = shell.dataset.view === 'team' ? 'team' : 'conversations';
  let contactId = shell.dataset.selectedContact || '';
  let groupSocket = null;
  let privatePoll = null;
  let sidebarPoll = null;
  let lastIncomingPrivate = 0;

  const esc = v => String(v ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
  const when = iso => {
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? '' : d.toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
  };
  const scrollBottom = () => { if (list) list.scrollTop = list.scrollHeight; };

  function messageHtml(item,prefix){
    const senderId=Number(item.user_id ?? item.sender_id ?? 0);
    const mine=senderId===userId;
    return `<article class="dbm-msg ${mine?'mine':''}" data-message-id="${prefix}-${Number(item.id)}"><div class="dbm-msg-bubble"><strong>${esc(item.user_name || (mine?'Você':'Usuário'))}</strong><p>${esc(item.message)}</p><small>${esc(when(item.created_at))}</small></div></article>`;
  }

  function setMessages(items,prefix){
    if (!items?.length){
      list.innerHTML='<div class="dbm-chat-center-empty"><strong>Nenhuma mensagem ainda</strong><span>Envie a primeira mensagem desta conversa.</span></div>';
    } else {
      list.innerHTML=items.map(x=>messageHtml(x,prefix)).join('');
    }
    scrollBottom();
  }

  function addMessage(item,prefix){
    const key=`${prefix}-${Number(item.id)}`;
    if (!item?.id || list.querySelector(`[data-message-id="${key}"]`)) return;
    const empty=list.querySelector('.dbm-chat-center-empty'); if(empty) empty.remove();
    list.insertAdjacentHTML('beforeend',messageHtml(item,prefix)); scrollBottom();
  }

  function updateCompose(){
    if (view==='team') form.hidden=!hasCompany;
    else form.hidden=!contactId;
  }

  function setTabs(){
    document.querySelectorAll('[data-main-tab]').forEach(btn=>btn.classList.toggle('active',btn.dataset.mainTab===view));
  }

  async function openPrivate(id){
    if(!id) return;
    view='conversations'; contactId=id; setTabs(); updateCompose();
    try{
      const res=await fetch(`/chat/private/${encodeURIComponent(id)}`,{cache:'no-store'});
      const data=await res.json();
      if(!data.ok) throw new Error(data.message||'Contato indisponível');
      title.textContent=data.contact.name;
      subtitle.textContent=`${data.contact.contact_id} • Chat privado`;
      avatar.textContent=(data.contact.name||'?').charAt(0).toUpperCase();
      setMessages(data.messages||[],'p');
      const incoming=(data.messages||[]).filter(x=>Number(x.sender_id)!==userId);
      lastIncomingPrivate=incoming.length?Number(incoming[incoming.length-1].id):0;
      history.replaceState({},'',`/company/chat?contact=${encodeURIComponent(id)}`);
      shell.classList.add('mobile-open');
      status.textContent='Chat privado';
      input?.focus();
    }catch(_){ status.textContent='Contato indisponível'; }
  }

  async function openTeam(){
    view='team'; contactId=''; setTabs();
    if(!hasCompany){
      location.href='/company';
      return;
    }
    title.textContent=companyName; subtitle.textContent='Grupo da empresa'; avatar.textContent=(companyName||'E').charAt(0).toUpperCase();
    try{
      const res=await fetch('/company/messages',{cache:'no-store'});
      const data=await res.json();
      setMessages(data.messages||[],'g');
    }catch(_){}
    updateCompose();
    history.replaceState({},'', '/company/chat?view=team');
    shell.classList.add('mobile-open');
    status.textContent='Conectado em tempo real';
  }

  async function pollPrivateMessages(){
    if(view!=='conversations'||!contactId) return;
    try{
      const res=await fetch(`/chat/private/${encodeURIComponent(contactId)}`,{cache:'no-store'});
      const data=await res.json();
      if(!data.ok) return;
      (data.messages||[]).forEach(x=>addMessage(x,'p'));
      const incoming=(data.messages||[]).filter(x=>Number(x.sender_id)!==userId);
      const newest=incoming.length?Number(incoming[incoming.length-1].id):0;
      lastIncomingPrivate=Math.max(lastIncomingPrivate,newest);
    }catch(_){}
  }

  async function refreshSidebar(){
    try{
      const res=await fetch('/chat/sidebar',{cache:'no-store'});
      const data=await res.json();
      if(!data.ok) return;
      const holder=document.getElementById('dbmConversationSide');
      if(!holder) return;
      if(!data.conversations?.length){
        holder.innerHTML='<div class="dbm-empty-side"><div><strong>Nenhum chat iniciado</strong><span>Adicione um contato à sua agenda para começar uma conversa.</span></div></div>';
      }else{
        holder.innerHTML=data.conversations.map(item=>`<button class="dbm-chat-item ${contactId===item.contact_id?'active':''}" type="button" data-contact-id="${esc(item.contact_id)}" data-search="${esc(item.name+' '+item.contact_id)}"><span class="dbm-avatar">${esc((item.name||'?').charAt(0).toUpperCase())}</span><span class="dbm-chat-copy"><strong>${esc(item.name)}</strong><small>${esc(item.last_message||'')}</small></span><span class="dbm-chat-meta">${item.last_at?esc(when(item.last_at).split(' ').pop()):''}${item.unread?`<b class="dbm-unread">${Number(item.unread)}</b>`:''}</span></button>`).join('');
      }
    }catch(_){}
  }

  function connectGroup(){
    if(!hasCompany) return;
    const protocol=location.protocol==='https:'?'wss':'ws';
    groupSocket=new WebSocket(`${protocol}://${location.host}/company/ws/chat`);
    groupSocket.addEventListener('open',()=>{ if(view==='team') status.textContent='Conectado em tempo real'; });
    groupSocket.addEventListener('message',event=>{
      try{
        const item=JSON.parse(event.data);
        if(view==='team') addMessage(item,'g');
        refreshSidebar();
      }catch(_){}
    });
    groupSocket.addEventListener('close',()=>setTimeout(connectGroup,1800));
    groupSocket.addEventListener('error',()=>{try{groupSocket.close()}catch(_){}});
  }

  form?.addEventListener('submit',async event=>{
    event.preventDefault();
    const message=input.value.trim(); if(!message) return;

    if(view==='team'){
      if(!hasCompany) return location.href='/company';
      if(!groupSocket||groupSocket.readyState!==WebSocket.OPEN){status.textContent='Reconectando...';return;}
      groupSocket.send(JSON.stringify({message})); input.value=''; return;
    }

    if(!contactId) return;
    const temp=`temp-${Date.now()}`;
    list.insertAdjacentHTML('beforeend',`<article class="dbm-msg mine" data-message-id="${temp}"><div class="dbm-msg-bubble"><strong>Você</strong><p>${esc(message)}</p><small>enviando...</small></div></article>`);
    scrollBottom(); input.value='';
    try{
      const res=await fetch(`/chat/private/${encodeURIComponent(contactId)}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message,csrf_token:csrf})});
      const data=await res.json();
      document.querySelector(`[data-message-id="${temp}"]`)?.remove();
      if(!data.ok) throw new Error(data.message||'Falha');
      addMessage(data.message,'p'); refreshSidebar();
    }catch(_){
      const small=document.querySelector(`[data-message-id="${temp}"] small`); if(small)small.textContent='não enviada';
    }
  });

  document.addEventListener('click',event=>{
    const conversation=event.target.closest('[data-contact-id]');
    if(conversation && !conversation.closest('#dbmContactList')){ openPrivate(conversation.dataset.contactId); return; }
    const start=event.target.closest('[data-start-contact]');
    if(start){ overlay.classList.remove('open'); openPrivate(start.dataset.startContact); return; }
  });

  document.querySelectorAll('[data-main-tab]').forEach(btn=>btn.addEventListener('click',()=>{
    if(btn.dataset.mainTab==='team') openTeam();
    else{
      view='conversations'; setTabs(); contactId='';
      title.textContent='Conversas'; subtitle.textContent='Selecione um contato'; avatar.textContent='C';
      list.innerHTML='<div class="dbm-chat-center-empty"><strong>Selecione uma conversa</strong><span>Ou use “Adicionar contatos” para iniciar um novo chat privado.</span></div>';
      updateCompose(); history.replaceState({},'', '/company/chat'); shell.classList.remove('mobile-open');
    }
  }));

  openAgenda?.addEventListener('click',()=>{overlay.classList.add('open');overlay.setAttribute('aria-hidden','false');contactInput?.focus();});
  closeAgenda?.addEventListener('click',()=>{overlay.classList.remove('open');overlay.setAttribute('aria-hidden','true');});
  overlay?.addEventListener('click',e=>{if(e.target===overlay)closeAgenda.click();});

  addContact?.addEventListener('click',async()=>{
    const id=contactInput.value.trim().toUpperCase();
    if(!id){agendaMessage.textContent='Digite o ID do contato.';agendaMessage.className='dbm-agenda-message error';return;}
    addContact.disabled=true; agendaMessage.textContent='Adicionando...'; agendaMessage.className='dbm-agenda-message';
    try{
      const res=await fetch('/chat/contacts',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({contact_id:id,csrf_token:csrf})});
      const data=await res.json();
      if(!data.ok) throw new Error(data.message||'Não foi possível adicionar.');
      agendaMessage.textContent=`${data.contact.name} adicionado à agenda.`;
      contactInput.value='';
      const holder=document.getElementById('dbmContactList');
      if(holder){
        holder.querySelector('.dbm-empty-side')?.remove();
        if(!holder.querySelector(`[data-agenda-contact="${CSS.escape(data.contact.contact_id)}"]`)){
          holder.insertAdjacentHTML('beforeend',`<div class="dbm-contact-row" data-agenda-contact="${esc(data.contact.contact_id)}"><span class="dbm-avatar">${esc(data.contact.name.charAt(0).toUpperCase())}</span><span class="dbm-chat-copy"><strong>${esc(data.contact.name)}</strong><small>${esc(data.contact.email||'')}</small><span class="dbm-contact-id">${esc(data.contact.contact_id)}</span></span><button type="button" data-start-contact="${esc(data.contact.contact_id)}">Conversar</button></div>`);
        }
      }
    }catch(err){agendaMessage.textContent=err.message||'Erro ao adicionar contato.';agendaMessage.className='dbm-agenda-message error';}
    finally{addContact.disabled=false;}
  });

  search?.addEventListener('input',()=>{
    const q=search.value.trim().toLowerCase();
    document.querySelectorAll('#dbmConversationSide [data-search]').forEach(el=>el.hidden=q&&!String(el.dataset.search||'').toLowerCase().includes(q));
  });

  back?.addEventListener('click',()=>shell.classList.remove('mobile-open'));
  input?.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();form.requestSubmit();}});

  scrollBottom(); setTabs(); updateCompose(); connectGroup();
  privatePoll=setInterval(pollPrivateMessages,1800);
  sidebarPoll=setInterval(refreshSidebar,3500);
  window.addEventListener('beforeunload',()=>{clearInterval(privatePoll);clearInterval(sidebarPoll);try{groupSocket?.close()}catch(_){}});
})();