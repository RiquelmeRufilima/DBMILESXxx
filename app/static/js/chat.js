/* Chat DBMILESX: conversas privadas + chat da equipe.
 * - Envio sempre por HTTP (o Vercel não mantém WebSocket aberto).
 * - Atualização a cada 3 s só com a aba visível.
 * - Horário de Brasília em todas as mensagens.
 * - Anexos: PDF, Word (.doc/.docx), JPG e PNG — também colando um print (Ctrl+V).
 */
(() => {
  'use strict';
  const shell = document.getElementById('dbmChatV2');
  if (!shell) return;

  const userId = Number(shell.dataset.userId || 0);
  const csrf = shell.dataset.csrf || document.querySelector('meta[name="csrf-token"]')?.content || '';
  const hasCompany = shell.dataset.hasCompany === '1';
  const companyName = shell.dataset.companyName || 'Chat da equipe';

  const $ = (id) => document.getElementById(id);
  const list = $('dbmChatMessages');
  const form = $('dbmChatForm');
  const input = $('dbmChatInput');
  const title = $('dbmChatTitle');
  const subtitle = $('dbmChatSubtitle');
  const status = $('dbmChatStatus');
  const avatar = $('dbmHeaderAvatar');
  const fileInput = $('dbmChatFile');
  const attachButton = $('dbmAttachButton');
  const preview = $('dbmAttachPreview');
  const overlay = $('dbmAgendaOverlay');
  const contactInput = $('dbmContactIdInput');
  const agendaMessage = $('dbmAgendaMessage');

  const ALLOWED = ['.pdf', '.doc', '.docx', '.jpg', '.jpeg', '.png'];
  const MAX_BYTES = 4 * 1024 * 1024; // limite do Vercel por envio
  let view = shell.dataset.view === 'team' ? 'team' : 'conversations';
  let contactId = shell.dataset.selectedContact || '';
  let pendingFile = null;
  let sending = false;
  let lastSeenId = 0;
  let firstLoad = true;

  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'}[c]));
  const fmt = new Intl.DateTimeFormat('pt-BR', {timeZone: 'America/Sao_Paulo', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'});
  const fmtTime = new Intl.DateTimeFormat('pt-BR', {timeZone: 'America/Sao_Paulo', hour: '2-digit', minute: '2-digit'});
  const parse = (iso) => {
    if (!iso) return null;
    // Compatível com respostas antigas sem fuso: trata como UTC.
    const text = /[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`;
    const d = new Date(text);
    return Number.isNaN(d.getTime()) ? null : d;
  };
  const when = (iso) => { const d = parse(iso); return d ? fmt.format(d).replace(',', '') : ''; };
  const hhmm = (iso) => { const d = parse(iso); return d ? fmtTime.format(d) : ''; };
  const size = (n) => (n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);
  const scrollBottom = () => { list.scrollTop = list.scrollHeight; };
  const setStatus = (text) => { if (status) status.textContent = text || ''; };

  function fileIcon(name) {
    const ext = String(name || '').split('.').pop().toLowerCase();
    if (ext === 'pdf') return {label: 'PDF', cls: 'is-pdf'};
    if (ext === 'doc' || ext === 'docx') return {label: 'DOC', cls: 'is-doc'};
    return {label: ext.toUpperCase().slice(0, 4), cls: ''};
  }

  function attachmentHtml(att) {
    if (!att) return '';
    if (att.is_image) {
      return `<a class="dbm-att-image" href="${esc(att.url)}" target="_blank" rel="noopener"><img src="${esc(att.url)}" alt="${esc(att.name)}" loading="lazy"></a>`;
    }
    const icon = fileIcon(att.name);
    return `<a class="dbm-att-file" href="${esc(att.url)}" target="_blank" rel="noopener"><span class="dbm-att-icon ${icon.cls}">${esc(icon.label)}</span><span class="dbm-att-copy"><b>${esc(att.name)}</b><small>${esc(size(att.size || 0))} • abrir</small></span></a>`;
  }

  function messageHtml(item, prefix) {
    const mine = Number(item.user_id ?? item.sender_id ?? 0) === userId;
    const att = item.attachment;
    const text = att && String(item.message || '').startsWith('📎 ') ? '' : item.message;
    return `<article class="dbm-msg ${mine ? 'mine' : ''}" data-message-id="${prefix}-${Number(item.id)}"><div class="dbm-msg-bubble"><strong>${esc(mine ? 'Você' : (item.user_name || 'Usuário'))}</strong>${attachmentHtml(att)}${text ? `<p>${esc(text)}</p>` : ''}<small>${esc(when(item.created_at))}</small></div></article>`;
  }

  function emptyHtml(strong, span) {
    return `<div class="dbm-chat-center-empty"><strong>${esc(strong)}</strong><span>${esc(span)}</span></div>`;
  }

  function render(items, prefix) {
    const nearBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 120;
    const existing = new Set([...list.querySelectorAll('[data-message-id]')].map((el) => el.dataset.messageId));
    if (!items.length) {
      list.innerHTML = emptyHtml('Nenhuma mensagem ainda', 'Envie a primeira mensagem desta conversa.');
      return;
    }
    list.querySelector('.dbm-chat-center-empty,.dbm-team-locked')?.remove();
    // Remove mensagens "provisórias" que já chegaram do servidor
    list.querySelectorAll('[data-message-id^="temp-"]').forEach((el) => el.remove());
    let added = 0;
    let incoming = false;
    const html = [];
    for (const item of items) {
      const key = `${prefix}-${Number(item.id)}`;
      if (existing.has(key)) continue;
      html.push(messageHtml(item, prefix));
      added += 1;
      if (Number(item.user_id ?? item.sender_id) !== userId && Number(item.id) > lastSeenId) incoming = true;
    }
    if (firstLoad) { list.innerHTML = items.map((x) => messageHtml(x, prefix)).join(''); }
    else if (html.length) list.insertAdjacentHTML('beforeend', html.join(''));
    lastSeenId = Math.max(lastSeenId, ...items.map((x) => Number(x.id) || 0));
    if (firstLoad || nearBottom || added) scrollBottom();
    if (!firstLoad && incoming) window.dbmChatPlaySound?.();
    firstLoad = false;
  }

  function updateCompose() {
    form.hidden = view === 'team' ? !hasCompany : !contactId;
  }
  function setTabs() {
    document.querySelectorAll('[data-main-tab]').forEach((b) => b.classList.toggle('active', b.dataset.mainTab === view));
  }

  async function getJSON(url) {
    const res = await fetch(url, {cache: 'no-store', credentials: 'same-origin', headers: {Accept: 'application/json'}});
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.message || 'Falha ao carregar.');
    return data;
  }

  async function loadCurrent() {
    try {
      if (view === 'team') {
        if (!hasCompany) return;
        const data = await getJSON('/company/messages');
        render(data.messages || [], 'g');
      } else if (contactId) {
        const data = await getJSON(`/company/chat/private/${encodeURIComponent(contactId)}`);
        if (!data.ok) throw new Error(data.message);
        if (firstLoad && data.contact) {
          title.textContent = data.contact.name;
          subtitle.textContent = `${data.contact.contact_id} • Chat privado`;
          avatar.textContent = (data.contact.name || '?').charAt(0).toUpperCase();
        }
        render(data.messages || [], 'p');
      }
      setStatus(view === 'team' ? 'Chat da equipe' : (contactId ? 'Chat privado' : ''));
    } catch (_) {
      setStatus('Sem conexão — tentando de novo');
    }
  }

  function openPrivate(id) {
    if (!id) return;
    view = 'conversations'; contactId = id; firstLoad = true; lastSeenId = 0;
    list.innerHTML = emptyHtml('Carregando...', '');
    setTabs(); updateCompose(); clearPending();
    history.replaceState({}, '', `/company/chat?contact=${encodeURIComponent(id)}`);
    shell.classList.add('mobile-open');
    document.querySelectorAll('#dbmConversationSide [data-contact-id]').forEach((el) => el.classList.toggle('active', el.dataset.contactId === id));
    loadCurrent().then(() => input?.focus());
  }

  function openTeam() {
    if (!hasCompany) { location.href = '/company'; return; }
    view = 'team'; contactId = ''; firstLoad = true; lastSeenId = 0;
    title.textContent = companyName; subtitle.textContent = 'Grupo da empresa';
    avatar.textContent = (companyName || 'E').charAt(0).toUpperCase();
    list.innerHTML = emptyHtml('Carregando...', '');
    setTabs(); updateCompose(); clearPending();
    history.replaceState({}, '', '/company/chat?view=team');
    shell.classList.add('mobile-open');
    loadCurrent();
  }

  async function refreshSidebar() {
    try {
      const data = await getJSON('/company/chat/sidebar');
      const holder = $('dbmConversationSide');
      if (!data.ok || !holder) return;
      if (!data.conversations?.length) {
        holder.innerHTML = '<div class="dbm-empty-side"><div><strong>Nenhum chat iniciado</strong><span>Adicione um contato à sua agenda para começar uma conversa.</span></div></div>';
        return;
      }
      holder.innerHTML = data.conversations.map((item) => `<button class="dbm-chat-item ${contactId === item.contact_id ? 'active' : ''}" type="button" data-contact-id="${esc(item.contact_id)}" data-search="${esc(`${item.name} ${item.contact_id}`)}"><span class="dbm-avatar">${esc((item.name || '?').charAt(0).toUpperCase())}</span><span class="dbm-chat-copy"><strong>${esc(item.name)}</strong><small>${esc(item.last_message || '')}</small></span><span class="dbm-chat-meta">${esc(hhmm(item.last_at))}${item.unread ? `<b class="dbm-unread">${Number(item.unread)}</b>` : ''}</span></button>`).join('');
      const q = ($('dbmChatSearch')?.value || '').trim().toLowerCase();
      if (q) holder.querySelectorAll('[data-search]').forEach((el) => { el.hidden = !el.dataset.search.toLowerCase().includes(q); });
    } catch (_) { /* tenta na próxima */ }
  }

  // ------------------------- anexos -------------------------
  function clearPending() {
    pendingFile = null;
    if (fileInput) fileInput.value = '';
    if (preview) { preview.hidden = true; preview.innerHTML = ''; }
  }

  function setPending(file) {
    if (!file) return;
    const ext = `.${String(file.name || '').split('.').pop().toLowerCase()}`;
    if (!ALLOWED.includes(ext)) { setStatus('Envie somente PDF, Word, JPG ou PNG.'); return; }
    if (file.size > MAX_BYTES) { setStatus('Arquivo maior que 4 MB.'); return; }
    pendingFile = file;
    const isImg = /^image\//.test(file.type);
    const icon = fileIcon(file.name);
    preview.innerHTML = `${isImg ? `<img src="${URL.createObjectURL(file)}" alt="">` : `<span class="dbm-att-icon ${icon.cls}">${esc(icon.label)}</span>`}<span class="dbm-att-copy"><b>${esc(file.name)}</b><small>${esc(size(file.size))} • pronto para enviar</small></span><button type="button" class="dbm-att-remove" aria-label="Remover anexo">✕</button>`;
    preview.hidden = false;
    preview.querySelector('.dbm-att-remove').addEventListener('click', clearPending);
    input.focus();
  }

  attachButton?.addEventListener('click', () => fileInput?.click());
  fileInput?.addEventListener('change', () => setPending(fileInput.files?.[0]));
  input?.addEventListener('paste', (event) => {
    const item = [...(event.clipboardData?.items || [])].find((x) => x.kind === 'file' && /^image\/(png|jpeg)$/.test(x.type));
    if (!item) return;
    event.preventDefault();
    const blob = item.getAsFile();
    const ext = blob.type === 'image/png' ? 'png' : 'jpg';
    const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
    setPending(new File([blob], `print-${stamp}.${ext}`, {type: blob.type}));
  });
  ['dragover', 'drop'].forEach((name) => list.addEventListener(name, (e) => {
    if (form.hidden) return;
    e.preventDefault();
    if (name === 'drop') setPending(e.dataTransfer?.files?.[0]);
  }));

  // ------------------------- envio -------------------------
  function addTemp(text, label) {
    const key = `temp-${Date.now()}`;
    list.querySelector('.dbm-chat-center-empty')?.remove();
    list.insertAdjacentHTML('beforeend', `<article class="dbm-msg mine" data-message-id="${key}"><div class="dbm-msg-bubble"><strong>Você</strong>${text ? `<p>${esc(text)}</p>` : ''}<small>${esc(label)}</small></div></article>`);
    scrollBottom();
    return key;
  }

  form?.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (sending) return;
    const text = input.value.trim();
    if (!text && !pendingFile) return;
    if (view === 'team' && !hasCompany) { location.href = '/company'; return; }
    if (view !== 'team' && !contactId) return;

    sending = true;
    const tempKey = addTemp(text || (pendingFile ? `📎 ${pendingFile.name}` : ''), pendingFile ? 'enviando arquivo...' : 'enviando...');
    const base = view === 'team' ? '/company/messages' : `/company/chat/private/${encodeURIComponent(contactId)}`;
    try {
      let res;
      if (pendingFile) {
        const fd = new FormData();
        fd.append('csrf_token', csrf);
        fd.append('message', text);
        fd.append('file', pendingFile);
        res = await fetch(view === 'team' ? '/company/messages/arquivo' : `${base}/arquivo`, {method: 'POST', credentials: 'same-origin', body: fd});
      } else {
        res = await fetch(base, {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json', Accept: 'application/json'}, body: JSON.stringify({message: text, csrf_token: csrf})});
      }
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.ok) throw new Error(data.message || 'Não enviada');
      document.querySelector(`[data-message-id="${tempKey}"]`)?.remove();
      list.insertAdjacentHTML('beforeend', messageHtml(data.message, view === 'team' ? 'g' : 'p'));
      lastSeenId = Math.max(lastSeenId, Number(data.message.id) || 0);
      input.value = '';
      clearPending();
      scrollBottom();
      refreshSidebar();
    } catch (error) {
      const small = document.querySelector(`[data-message-id="${tempKey}"] small`);
      if (small) small.textContent = `${error.message || 'Não enviada'} — tente novamente`;
    } finally {
      sending = false;
    }
  });
  input?.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); } });

  // ------------------------- navegação / agenda -------------------------
  document.addEventListener('click', (event) => {
    const conversation = event.target.closest('[data-contact-id]');
    if (conversation && !conversation.closest('#dbmContactList')) { openPrivate(conversation.dataset.contactId); return; }
    const start = event.target.closest('[data-start-contact]');
    if (start) { overlay?.classList.remove('open'); openPrivate(start.dataset.startContact); }
  });
  document.querySelectorAll('[data-main-tab]').forEach((btn) => btn.addEventListener('click', () => {
    if (btn.dataset.mainTab === 'team') { openTeam(); return; }
    view = 'conversations'; contactId = ''; setTabs(); clearPending();
    title.textContent = 'Conversas'; subtitle.textContent = 'Selecione um contato'; avatar.textContent = 'C';
    list.innerHTML = emptyHtml('Selecione uma conversa', 'Ou use “Adicionar contatos” para iniciar um novo chat privado.');
    updateCompose(); history.replaceState({}, '', '/company/chat'); shell.classList.remove('mobile-open');
  }));
  $('dbmChatBack')?.addEventListener('click', () => shell.classList.remove('mobile-open'));
  $('dbmChatSearch')?.addEventListener('input', (e) => {
    const q = e.target.value.trim().toLowerCase();
    document.querySelectorAll('#dbmConversationSide [data-search]').forEach((el) => { el.hidden = !!q && !String(el.dataset.search || '').toLowerCase().includes(q); });
  });
  $('dbmOpenAgenda')?.addEventListener('click', () => { overlay.classList.add('open'); overlay.setAttribute('aria-hidden', 'false'); contactInput?.focus(); });
  $('dbmCloseAgenda')?.addEventListener('click', () => { overlay.classList.remove('open'); overlay.setAttribute('aria-hidden', 'true'); });
  overlay?.addEventListener('click', (e) => { if (e.target === overlay) $('dbmCloseAgenda').click(); });
  $('dbmAddContact')?.addEventListener('click', async () => {
    const button = $('dbmAddContact');
    const id = contactInput.value.trim().toUpperCase();
    if (!id) { agendaMessage.textContent = 'Digite o ID do contato.'; agendaMessage.className = 'dbm-agenda-message error'; return; }
    button.disabled = true; agendaMessage.textContent = 'Adicionando...'; agendaMessage.className = 'dbm-agenda-message';
    try {
      const res = await fetch('/company/chat/contacts', {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({contact_id: id, csrf_token: csrf})});
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.ok) throw new Error(data.message || 'Não foi possível adicionar.');
      agendaMessage.textContent = `${data.contact.name} adicionado à agenda.`;
      contactInput.value = '';
      const holder = $('dbmContactList');
      holder?.querySelector('.dbm-empty-side')?.remove();
      if (holder && !holder.querySelector(`[data-agenda-contact="${CSS.escape(data.contact.contact_id)}"]`)) {
        holder.insertAdjacentHTML('beforeend', `<div class="dbm-contact-row" data-agenda-contact="${esc(data.contact.contact_id)}"><span class="dbm-avatar">${esc(data.contact.name.charAt(0).toUpperCase())}</span><span class="dbm-chat-copy"><strong>${esc(data.contact.name)}</strong><small>${esc(data.contact.email || '')}</small><span class="dbm-contact-id">${esc(data.contact.contact_id)}</span></span><button type="button" data-start-contact="${esc(data.contact.contact_id)}">Conversar</button></div>`);
      }
    } catch (err) {
      agendaMessage.textContent = err.message || 'Erro ao adicionar contato.'; agendaMessage.className = 'dbm-agenda-message error';
    } finally { button.disabled = false; }
  });

  // ------------------------- ciclo -------------------------
  setTabs(); updateCompose();
  if (view === 'team' || contactId) loadCurrent();
  setInterval(() => { if (!document.hidden) loadCurrent(); }, 3000);
  setInterval(() => { if (!document.hidden) refreshSidebar(); }, 7000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) { loadCurrent(); refreshSidebar(); } });
})();
