(() => {
  const shell = document.getElementById('dbmMessenger');
  const list = document.getElementById('dbmChatMessages');
  const form = document.getElementById('dbmChatForm');
  const input = document.getElementById('dbmChatInput');
  const status = document.getElementById('dbmChatStatus');
  const title = document.getElementById('dbmChatTitle');
  const subtitle = document.getElementById('dbmChatSubtitle');
  const headerAvatar = document.getElementById('dbmHeaderAvatar');
  const search = document.getElementById('dbmChatSearch');
  const back = document.getElementById('dbmChatBack');
  if (!shell || !list || !form || !input) return;

  const currentUserId = Number(shell.dataset.userId || 0);
  const companyName = shell.dataset.companyName || 'Empresa';
  const csrfToken = shell.dataset.csrf || '';
  let mode = shell.dataset.selectedContact ? 'private' : 'group';
  let contactId = shell.dataset.selectedContact || '';
  let groupSocket = null;
  let privatePollTimer = null;
  let sidebarPollTimer = null;
  let lastPrivateIncomingId = 0;
  let audioContext = null;

  function unlockAudio(){
    try{
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return;
      audioContext ||= new Ctx();
      if (audioContext.state === 'suspended') audioContext.resume().catch(()=>{});
    }catch(_){}
  }
  ['pointerdown','keydown','touchstart'].forEach(evt => window.addEventListener(evt, unlockAudio, {once:true, passive:true}));

  function sound(){
    unlockAudio();
    if (!audioContext || audioContext.state !== 'running') return;
    const start = audioContext.currentTime + .01;
    [[0,760,.12,.045],[.10,1020,.16,.052]].forEach(([off,freq,dur,vol]) => {
      const osc = audioContext.createOscillator();
      const gain = audioContext.createGain();
      osc.type='sine'; osc.frequency.value=freq;
      gain.gain.setValueAtTime(.0001,start+off);
      gain.gain.exponentialRampToValueAtTime(vol,start+off+.018);
      gain.gain.exponentialRampToValueAtTime(.0001,start+off+dur);
      osc.connect(gain); gain.connect(audioContext.destination);
      osc.start(start+off); osc.stop(start+off+dur+.02);
    });
  }

  function esc(value){
    return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
  }
  function when(iso){
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '';
    return d.toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
  }
  function scrollBottom(){ list.scrollTop = list.scrollHeight; }

  function messageHtml(item, prefix){
    const senderId = Number(item.user_id ?? item.sender_id ?? 0);
    const mine = senderId === currentUserId;
    return `<article class="dbm-message ${mine?'mine':''}" data-message-id="${prefix}-${Number(item.id)}">
      <div class="dbm-message-bubble">
        <strong>${esc(item.user_name || (mine ? 'Você':'Usuário'))}</strong>
        <p>${esc(item.message)}</p>
        <small>${esc(when(item.created_at))}</small>
      </div>
    </article>`;
  }

  function addMessage(item, prefix='g'){
    const key = `${prefix}-${Number(item.id)}`;
    if (!item?.id || list.querySelector(`[data-message-id="${key}"]`)) return;
    list.insertAdjacentHTML('beforeend', messageHtml(item,prefix));
    scrollBottom();
  }

  function setMessages(items, prefix){
    list.innerHTML = (items || []).map(item => messageHtml(item,prefix)).join('');
    if (!items?.length) {
      list.innerHTML = `<div class="dbm-chat-empty"><strong>Nenhuma mensagem ainda</strong><span>Envie a primeira mensagem desta conversa.</span></div>`;
    }
    scrollBottom();
  }

  function setActiveTarget(kind, id=''){
    document.querySelectorAll('[data-chat-target]').forEach(el => {
      el.classList.toggle('active', el.dataset.chatTarget === kind && (kind !== 'private' || el.dataset.contactId === id));
    });
  }

  async function openGroup(){
    mode='group'; contactId=''; form.dataset.mode='group';
    title.textContent=companyName;
    subtitle.textContent='Grupo da empresa';
    headerAvatar.textContent=(companyName.trim().charAt(0)||'E').toUpperCase();
    setActiveTarget('group');
    history.replaceState({},'', '/company/chat');
    try{
      const res=await fetch('/company/messages',{cache:'no-store'});
      const data=await res.json();
      setMessages(data.messages || [],'g');
    }catch(_){}
    shell.classList.add('mobile-conversation-open');
    input.focus();
  }

  async function openPrivate(id){
    if (!id) return;
    mode='private'; contactId=id; form.dataset.mode='private';
    setActiveTarget('private',id);
    status.textContent='Atualizando...';
    try{
      const res=await fetch(`/company/chat/private/${encodeURIComponent(id)}`,{cache:'no-store'});
      const data=await res.json();
      if (!data.ok) throw new Error(data.message || 'Contato indisponível');
      title.textContent=data.contact.name;
      subtitle.textContent=`${data.contact.contact_id} • Chat privado`;
      headerAvatar.textContent=(data.contact.name.trim().charAt(0)||'?').toUpperCase();
      setMessages(data.messages || [],'p');
      const incoming=(data.messages||[]).filter(x=>Number(x.sender_id)!==currentUserId);
      lastPrivateIncomingId = incoming.length ? Number(incoming[incoming.length-1].id) : 0;
      history.replaceState({},'',`/company/chat?contact=${encodeURIComponent(id)}`);
      status.textContent='Chat privado';
      shell.classList.add('mobile-conversation-open');
      input.focus();
    }catch(err){
      status.textContent='Contato indisponível';
    }
  }

  async function pollPrivate(){
    if (mode!=='private' || !contactId) return;
    try{
      const res=await fetch(`/company/chat/private/${encodeURIComponent(contactId)}`,{cache:'no-store'});
      const data=await res.json();
      if (!data.ok) return;
      const incoming=(data.messages||[]).filter(x=>Number(x.sender_id)!==currentUserId);
      const newest = incoming.length ? Number(incoming[incoming.length-1].id) : 0;
      if (newest && lastPrivateIncomingId && newest > lastPrivateIncomingId) sound();
      lastPrivateIncomingId = Math.max(lastPrivateIncomingId,newest);
      (data.messages||[]).forEach(item=>addMessage(item,'p'));
    }catch(_){}
  }

  async function refreshSidebar(){
    try{
      const res=await fetch('/company/chat/sidebar',{cache:'no-store'});
      const data=await res.json();
      if (!data.ok) return;
      const holder=document.getElementById('dbmConversationList');
      if (!holder) return;
      holder.innerHTML=(data.conversations||[]).map(item=>`
        <button class="dbm-chat-item ${mode==='private'&&contactId===item.contact_id?'active':''}" type="button" data-chat-target="private" data-contact-id="${esc(item.contact_id)}" data-search="${esc(item.name+' '+item.contact_id)}">
          <span class="dbm-chat-avatar">${esc((item.name||'?').charAt(0).toUpperCase())}</span>
          <span class="dbm-chat-item-copy"><strong>${esc(item.name)}</strong><small>${esc(item.last_message||'')}</small></span>
          <span class="dbm-chat-meta">${item.last_at ? esc(when(item.last_at).split(' ').pop()) : ''}${item.unread ? `<b class="dbm-chat-badge">${Number(item.unread)}</b>`:''}</span>
        </button>`).join('');
    }catch(_){}
  }

  function connectGroup(){
    const protocol=location.protocol==='https:'?'wss':'ws';
    groupSocket=new WebSocket(`${protocol}://${location.host}/company/ws/chat`);
    groupSocket.addEventListener('open',()=>{ if(mode==='group') status.textContent='Conectado em tempo real'; });
    groupSocket.addEventListener('message',(event)=>{
      try{
        const item=JSON.parse(event.data);
        if(mode==='group'){
          const isOther=Number(item.user_id)!==currentUserId;
          addMessage(item,'g');
          if(isOther && document.hidden) sound();
        }else if(Number(item.user_id)!==currentUserId){
          refreshSidebar();
        }
      }catch(_){}
    });
    groupSocket.addEventListener('close',()=>{ if(mode==='group') status.textContent='Reconectando...'; setTimeout(connectGroup,1800); });
    groupSocket.addEventListener('error',()=>{ try{groupSocket.close()}catch(_){} });
  }

  form.addEventListener('submit', async (event)=>{
    event.preventDefault();
    const message=input.value.trim();
    if(!message) return;

    if(mode==='group'){
      if(!groupSocket || groupSocket.readyState!==WebSocket.OPEN){ status.textContent='Reconectando...'; return; }
      groupSocket.send(JSON.stringify({message}));
      input.value=''; input.focus(); return;
    }

    if(mode==='private' && contactId){
      const tempId=`temp-${Date.now()}`;
      const optimistic={id:tempId,user_id:currentUserId,user_name:'Você',message,created_at:new Date().toISOString()};
      list.insertAdjacentHTML('beforeend', `<article class="dbm-message mine" data-message-id="${tempId}"><div class="dbm-message-bubble"><strong>Você</strong><p>${esc(message)}</p><small>enviando...</small></div></article>`);
      scrollBottom(); input.value=''; input.focus();
      try{
        const res=await fetch(`/company/chat/private/${encodeURIComponent(contactId)}`,{
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({message,csrf_token:csrfToken}),
        });
        const data=await res.json();
        document.querySelector(`[data-message-id="${tempId}"]`)?.remove();
        if(!data.ok) throw new Error(data.message||'Falha ao enviar');
        addMessage(data.message,'p');
        refreshSidebar();
      }catch(err){
        const temp=document.querySelector(`[data-message-id="${tempId}"] small`);
        if(temp) temp.textContent='não enviada';
      }
    }
  });

  document.addEventListener('click',(event)=>{
    const target=event.target.closest('[data-chat-target]');
    if(!target) return;
    if(target.dataset.chatTarget==='group') openGroup();
    else openPrivate(target.dataset.contactId);
  });

  document.querySelectorAll('.dbm-chat-tab').forEach(btn=>{
    btn.addEventListener('click',()=>{
      document.querySelectorAll('.dbm-chat-tab').forEach(x=>x.classList.toggle('active',x===btn));
      document.querySelectorAll('.dbm-chat-pane').forEach(p=>p.hidden=p.dataset.pane!==btn.dataset.tab);
    });
  });

  search?.addEventListener('input',()=>{
    const q=search.value.trim().toLowerCase();
    document.querySelectorAll('[data-search]').forEach(el=>{
      el.hidden=q && !String(el.dataset.search||'').toLowerCase().includes(q);
    });
  });

  back?.addEventListener('click',()=>shell.classList.remove('mobile-conversation-open'));

  input.addEventListener('keydown',(event)=>{
    if(event.key==='Enter' && !event.shiftKey){
      event.preventDefault(); form.requestSubmit();
    }
  });

  scrollBottom();
  connectGroup();
  privatePollTimer=setInterval(pollPrivate,1800);
  sidebarPollTimer=setInterval(refreshSidebar,3500);
  window.addEventListener('beforeunload',()=>{ clearInterval(privatePollTimer);clearInterval(sidebarPollTimer);try{groupSocket?.close()}catch(_){} });
})();