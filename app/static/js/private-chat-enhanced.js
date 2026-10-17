(() => {
  const shell = document.getElementById('dbmChatV2') || document.getElementById('dbmChat3');
  if (!shell) return;
  const list = document.getElementById('dbmChatMessages') || document.getElementById('dbmMessages');
  const form = document.getElementById('dbmChatForm') || document.getElementById('dbmCompose');
  const input = document.getElementById('dbmChatInput') || document.getElementById('dbmInput');
  if (!list || !form || !input) return;

  form.dataset.noLoader='1';
  form.setAttribute('data-no-loader','1');

  const userId = Number(shell.dataset.userId || 0);
  const csrf = shell.dataset.csrf || '';
  const hasCompany = shell.dataset.hasCompany === '1';
  let view = shell.dataset.view === 'team' ? 'team' : 'conversations';
  let contactId = shell.dataset.selectedContact || '';
  let groupSocket = null;
  let lastPrivateIds = new Set(
    [...list.querySelectorAll('[data-message-id^="p-"],[data-mid^="p-"]')]
      .map(el => Number((el.dataset.messageId || el.dataset.mid || '').replace('p-','')))
      .filter(Boolean)
  );

  const esc = v => String(v ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
  const when = iso => { const d=new Date(iso); return Number.isNaN(d.getTime())?'':d.toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}); };
  const hideLoader = () => { try{window.dbmHideLoader?.()}catch(_){} document.getElementById('globalLoader')?.classList.remove('is-visible'); };
  const isV3 = shell.id === 'dbmChat3';

  function messageHtml(item,prefix,tempId=''){
    const senderId = Number(item.user_id ?? item.sender_id ?? 0);
    const mine = senderId === userId;
    const attr = isV3 ? 'data-mid' : 'data-message-id';
    const bubble = isV3 ? 'dbm-bubble' : 'dbm-msg-bubble';
    const idValue = tempId || `${prefix}-${Number(item.id)}`;
    return `<article class="dbm-msg ${mine?'mine':''}" ${attr}="${esc(idValue)}"><div class="${bubble}"><strong>${esc(item.user_name || (mine?'Você':'Usuário'))}</strong><p>${esc(item.message)}</p><small>${esc(item._status || when(item.created_at))}</small></div></article>`;
  }

  function addMessage(item,prefix){
    const key=`${prefix}-${Number(item.id)}`;
    if(!item?.id || list.querySelector(`[data-message-id="${key}"],[data-mid="${key}"]`)) return false;
    list.querySelector('.dbm-chat-center-empty,.dbm-empty')?.remove();
    list.insertAdjacentHTML('beforeend',messageHtml(item,prefix));
    list.scrollTop=list.scrollHeight;
    return true;
  }

  async function pollPrivate(){
    if(view!=='conversations' || !contactId) return;
    try{
      const res=await fetch(`/chat/private/${encodeURIComponent(contactId)}`,{cache:'no-store'});
      const data=await res.json();
      if(!data.ok) return;
      let gotNew=false;
      for(const item of data.messages||[]){
        const id=Number(item.id); if(!id) continue;
        if(!lastPrivateIds.has(id)){
          if(addMessage(item,'p') && Number(item.sender_id)!==userId) gotNew=true;
          lastPrivateIds.add(id);
        }
      }
      if(gotNew) window.dbmChatPlaySound?.();
    }catch(_){}
  }

  function connectGroup(){
    if(!hasCompany) return;
    const protocol=location.protocol==='https:'?'wss':'ws';
    groupSocket=new WebSocket(`${protocol}://${location.host}/company/ws/chat`);
    groupSocket.addEventListener('message',event=>{
      try{
        const item=JSON.parse(event.data);
        if(view==='team'){
          const other=Number(item.user_id)!==userId;
          if(addMessage(item,'g') && other) window.dbmChatPlaySound?.();
        }
      }catch(_){}
    });
    groupSocket.addEventListener('close',()=>setTimeout(connectGroup,1800));
    groupSocket.addEventListener('error',()=>{try{groupSocket.close()}catch(_){}});
  }

  form.addEventListener('submit',async event=>{
    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation?.();
    hideLoader();
    const message=input.value.trim();
    if(!message) return;

    if(view==='team'){
      if(!hasCompany){location.href='/company';return;}
      if(!groupSocket || groupSocket.readyState!==WebSocket.OPEN) return;
      input.value=''; input.focus();
      groupSocket.send(JSON.stringify({message}));
      hideLoader();
      return;
    }

    if(!contactId) return;
    const tempId=`temp-${Date.now()}`;
    const optimistic={user_id:userId,sender_id:userId,user_name:'Você',message,created_at:new Date().toISOString(),_status:when(new Date().toISOString())};
    list.querySelector('.dbm-chat-center-empty,.dbm-empty')?.remove();
    list.insertAdjacentHTML('beforeend',messageHtml(optimistic,'p',tempId));
    input.value=''; input.focus(); list.scrollTop=list.scrollHeight; hideLoader();

    try{
      const res=await fetch(`/chat/private/${encodeURIComponent(contactId)}`,{
        method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message,csrf_token:csrf})
      });
      const data=await res.json();
      hideLoader();
      if(!data.ok) throw new Error(data.message||'Falha');
      const node=list.querySelector(`[data-message-id="${tempId}"],[data-mid="${tempId}"]`);
      if(node){ const wrap=document.createElement('div'); wrap.innerHTML=messageHtml(data.message,'p'); node.replaceWith(wrap.firstElementChild); }
      else addMessage(data.message,'p');
      lastPrivateIds.add(Number(data.message.id));
    }catch(_){
      const node=list.querySelector(`[data-message-id="${tempId}"],[data-mid="${tempId}"]`);
      const small=node?.querySelector('small');
      if(small) small.textContent='Não enviada — tente novamente';
      hideLoader();
    }
  },true);

  document.addEventListener('click',e=>{
    const target=e.target.closest('[data-contact-id],[data-contact]');
    if(target){
      contactId=target.dataset.contactId || target.dataset.contact || '';
      view='conversations';
      lastPrivateIds.clear();
    }
    if(e.target.closest('[data-main-tab="team"],[data-tab="team"]')) view='team';
    if(e.target.closest('[data-main-tab="conversations"],[data-tab="conversations"]')) view='conversations';
  });

  hideLoader();
  connectGroup();
  setInterval(pollPrivate,1600);
})();
