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
  const olderWrap = $('dbmOlderWrap');
  const olderButton = $('dbmLoadOlder');

  const ALLOWED = ['.pdf', '.doc', '.docx', '.jpg', '.jpeg', '.png'];
  const MAX_BYTES = 4 * 1024 * 1024; // limite do Vercel por envio
  let view = shell.dataset.view === 'team' ? 'team' : 'conversations';
  let contactId = shell.dataset.selectedContact || '';
  let pendingFile = null;
  let sending = false;
  let lastSeenId = 0;
  let oldestId = 0;
  let firstLoad = true;
  let loading = false;
  let generation = 0;
  let conversationLimit = 20;
  let favorites = new Set();
  let replyTo = null;
  let selecting = false;
  const selected = new Set();

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

  const messageInfo = new Map();
  const REPLY_MARK = '↩ ';
  const FORWARD_MARK = '↪ Encaminhada';

  function linkify(text) {
    return esc(text).replace(/(https?:\/\/[^\s<]+|\/calculations\/result\/\d+)/g, (url) => {
      const label = url.startsWith('/calculations/') ? 'Abrir cotação' : url;
      return `<a href="${url}" ${url.startsWith('http') ? 'target="_blank" rel="noopener"' : ''} class="dbm-msg-link">${label}</a>`;
    });
  }

  function splitMessage(raw) {
    let text = String(raw || '');
    let forwarded = false;
    let reply = null;
    if (text.startsWith(`${FORWARD_MARK}\n`)) { forwarded = true; text = text.slice(FORWARD_MARK.length + 1); }
    if (text.startsWith(REPLY_MARK) && text.includes('\n')) {
      const line = text.slice(REPLY_MARK.length, text.indexOf('\n'));
      const sep = line.indexOf(': ');
      reply = sep > 0 ? {name: line.slice(0, sep), text: line.slice(sep + 2)} : {name: '', text: line};
      text = text.slice(text.indexOf('\n') + 1);
    }
    return {forwarded, reply, text};
  }

  function bodyHtml(raw) {
    const part = splitMessage(raw);
    return `${part.forwarded ? '<em class="dbm-msg-forwarded">↪ Encaminhada</em>' : ''}${part.reply ? `<blockquote class="dbm-msg-quote"><b>${esc(part.reply.name)}</b>${esc(part.reply.text)}</blockquote>` : ''}${part.text ? `<p>${linkify(part.text)}</p>` : ''}`;
  }

  function messageHtml(item, prefix) {
    const mine = Number(item.user_id ?? item.sender_id ?? 0) === userId;
    const att = item.attachment;
    const text = att && String(item.message || '').startsWith('📎 ') ? '' : item.message;
    const key = `${prefix}-${Number(item.id)}`;
    messageInfo.set(key, {key, mine, name: mine ? 'Você' : (item.user_name || 'Usuário'), realName: item.user_name || 'Usuário', contactId: item.user_contact_id || '', message: String(item.message || ''), attachment: att || null});
    const fav = favorites.has(key) ? ' is-fav' : '';
    return `<article class="dbm-msg ${mine ? 'mine' : ''}${fav}" data-message-id="${key}"><span class="dbm-msg-check" aria-hidden="true"></span><div class="dbm-msg-bubble"><button type="button" class="dbm-msg-menu-btn" data-msg-menu="${key}" aria-label="Opções da mensagem" title="Opções">⌄</button><strong>${esc(mine ? 'Você' : (item.user_name || 'Usuário'))}</strong>${attachmentHtml(att)}${bodyHtml(text)}<small>${esc(when(item.created_at))}</small></div></article>`;
  }

  function emptyHtml(strong, span) {
    return `<div class="dbm-chat-center-empty"><strong>${esc(strong)}</strong><span>${esc(span)}</span></div>`;
  }

  function render(items, prefix) {
    const nearBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 120;
    const existing = new Set([...list.querySelectorAll('[data-message-id]')].map((el) => el.dataset.messageId));
    if (!items.length && firstLoad) {
      list.innerHTML = emptyHtml('Nenhuma mensagem ainda', 'Envie a primeira mensagem desta conversa.');
      firstLoad = false;
      return;
    }
    if (!items.length) return;
    list.querySelector('.dbm-chat-center-empty,.dbm-team-locked')?.remove();
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
    const batchOldest = Math.min(...items.map((x) => Number(x.id) || Infinity));
    oldestId = Math.min(oldestId || batchOldest, batchOldest);
    if (firstLoad || nearBottom) scrollBottom();
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
    if ((loading && !firstLoad) || document.hidden) return;
    loading = true;
    const currentGeneration = generation;
    const currentView = view;
    const currentContact = contactId;
    try {
      if (currentView === 'team') {
        if (!hasCompany) return;
        const data = await getJSON(`/company/messages${firstLoad || !lastSeenId ? '' : `?after_id=${lastSeenId}`}`);
        if (currentGeneration !== generation) return;
        const initial = firstLoad;
        render(data.messages || [], 'g');
        if (initial) olderWrap.hidden = !data.has_more;
      } else if (currentContact) {
        const data = await getJSON(`/company/chat/private/${encodeURIComponent(currentContact)}${firstLoad || !lastSeenId ? '' : `?after_id=${lastSeenId}`}`);
        if (currentGeneration !== generation) return;
        if (!data.ok) throw new Error(data.message);
        if (firstLoad && data.contact) {
          title.textContent = data.contact.name;
          subtitle.textContent = `${data.contact.contact_id} • Chat privado`;
          avatar.textContent = (data.contact.name || '?').charAt(0).toUpperCase();
        }
        const initial = firstLoad;
        render(data.messages || [], 'p');
        if (initial) olderWrap.hidden = !data.has_more;
      }
      setStatus(view === 'team' ? 'Chat da equipe' : (contactId ? 'Chat privado' : ''));
    } catch (_) {
      setStatus('Sem conexão — tentando de novo');
    } finally {
      if (currentGeneration === generation) loading = false;
    }
  }

  olderButton?.addEventListener('click', async () => {
    if (!oldestId || olderButton.disabled) return;
    const currentGeneration = generation;
    olderButton.disabled = true;
    olderButton.textContent = 'Carregando...';
    try {
      const url = view === 'team' ? '/company/messages' : `/company/chat/private/${encodeURIComponent(contactId)}`;
      const data = await getJSON(`${url}?before_id=${oldestId}`);
      if (currentGeneration !== generation) return;
      const items = data.messages || [];
      const before = list.scrollHeight;
      const html = items.filter(item => !list.querySelector(`[data-message-id="${view === 'team' ? 'g' : 'p'}-${Number(item.id)}"]`))
        .map(item => messageHtml(item, view === 'team' ? 'g' : 'p')).join('');
      if (html) list.insertAdjacentHTML('afterbegin', html);
      if (items.length) oldestId = Math.min(oldestId, ...items.map(x => Number(x.id)));
      list.scrollTop += list.scrollHeight - before;
      olderWrap.hidden = !data.has_more;
    } catch (_) { setStatus('Erro ao carregar mensagens anteriores'); }
    finally { olderButton.disabled = false; olderButton.textContent = 'Carregar mensagens anteriores'; }
  });

  function openPrivate(id) {
    if (!id) return;
    generation++; loading = false; view = 'conversations'; contactId = id; firstLoad = true; lastSeenId = 0; oldestId = 0;
    olderWrap.hidden = true; delete olderWrap.dataset.initialized;
    list.innerHTML = emptyHtml('Carregando...', '');
    setTabs(); updateCompose(); clearPending(); clearReply(); exitSelect(); favorites = new Set(); renderPins([]);
    history.replaceState({}, '', `/company/chat?contact=${encodeURIComponent(id)}`);
    loadFlags();
    shell.classList.add('mobile-open');
    document.querySelectorAll('#dbmConversationSide [data-contact-id]').forEach((el) => el.classList.toggle('active', el.dataset.contactId === id));
    loadCurrent().then(() => input?.focus());
  }

  function openTeam() {
    if (!hasCompany) { location.href = '/company'; return; }
    generation++; loading = false; view = 'team'; contactId = ''; firstLoad = true; lastSeenId = 0; oldestId = 0;
    olderWrap.hidden = true; delete olderWrap.dataset.initialized;
    title.textContent = companyName; subtitle.textContent = 'Grupo da empresa';
    avatar.textContent = (companyName || 'E').charAt(0).toUpperCase();
    list.innerHTML = emptyHtml('Carregando...', '');
    setTabs(); updateCompose(); clearPending(); clearReply(); exitSelect(); favorites = new Set(); renderPins([]);
    history.replaceState({}, '', '/company/chat?view=team');
    loadFlags();
    shell.classList.add('mobile-open');
    loadCurrent();
  }

  async function refreshSidebar() {
    try {
      const data = await getJSON(`/company/chat/sidebar?limit=${conversationLimit}`);
      const holder = $('dbmConversationSide');
      if (!data.ok || !holder) return;
      const more = $('dbmMoreConversations');
      if (more) more.hidden = !data.has_more;
      if (!data.conversations?.length) {
        holder.innerHTML = '<div class="dbm-empty-side"><div><strong>Nenhum chat iniciado</strong><span>Adicione um contato à sua agenda para começar uma conversa.</span></div></div>';
        return;
      }
      holder.innerHTML = data.conversations.map((item) => `<button class="dbm-chat-item ${contactId === item.contact_id ? 'active' : ''}" type="button" data-contact-id="${esc(item.contact_id)}" data-search="${esc(`${item.name} ${item.contact_id}`)}"><span class="dbm-avatar">${esc((item.name || '?').charAt(0).toUpperCase())}</span><span class="dbm-chat-copy"><strong>${esc(item.name)}</strong><small>${esc(item.last_message || '')}</small></span><span class="dbm-chat-meta">${esc(hhmm(item.last_at))}${item.unread ? `<b class="dbm-unread">${Number(item.unread)}</b>` : ''}</span></button>`).join('');
      const q = ($('dbmChatSearch')?.value || '').trim().toLowerCase();
      if (q) holder.querySelectorAll('[data-search]').forEach((el) => { el.hidden = !el.dataset.search.toLowerCase().includes(q); });
    } catch (_) { /* tenta na próxima */ }
  }

  $('dbmMoreConversations')?.addEventListener('click', () => {
    conversationLimit += 20;
    refreshSidebar();
  });

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
    const key = `temp-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    list.querySelector('.dbm-chat-center-empty')?.remove();
    list.insertAdjacentHTML('beforeend', `<article class="dbm-msg mine" data-message-id="${key}"><div class="dbm-msg-bubble"><strong>Você</strong>${text ? `<p>${esc(text)}</p>` : ''}<small>${esc(label)}</small></div></article>`);
    scrollBottom();
    return key;
  }

  form?.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (sending) return;
    const typed = input.value.trim();
    if (!typed && !pendingFile) return;
    const text = replyTo && typed ? `${REPLY_MARK}${replyTo.name}: ${replyTo.text}\n${typed}`.slice(0, 2000) : typed;
    if (view === 'team' && !hasCompany) { location.href = '/company'; return; }
    if (view !== 'team' && !contactId) return;

    sending = true;
    const destination = view === 'team' ? 'g' : 'p';
    const selectedGeneration = generation;
    const originalFile = pendingFile;
    const tempKey = addTemp(typed || (pendingFile ? `📎 ${pendingFile.name}` : ''), pendingFile ? 'enviando arquivo...' : 'enviando...');
    const base = view === 'team' ? '/company/messages' : `/company/chat/private/${encodeURIComponent(contactId)}`;
    input.value = '';
    clearPending();
    const savedReply = replyTo;
    clearReply();
    try {
      let res;
      if (originalFile) {
        const fd = new FormData();
        fd.append('csrf_token', csrf);
        fd.append('message', text);
        fd.append('file', originalFile);
        res = await fetch(view === 'team' ? '/company/messages/arquivo' : `${base}/arquivo`, {method: 'POST', credentials: 'same-origin', body: fd});
      } else {
        res = await fetch(base, {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json', Accept: 'application/json'}, body: JSON.stringify({message: text, csrf_token: csrf})});
      }
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.ok) throw new Error(data.message || 'Não enviada');
      document.querySelector(`[data-message-id="${tempKey}"]`)?.remove();
      if (selectedGeneration === generation && !list.querySelector(`[data-message-id="${destination}-${Number(data.message.id)}"]`))
        list.insertAdjacentHTML('beforeend', messageHtml(data.message, destination));
      if (selectedGeneration === generation) {
        lastSeenId = Math.max(lastSeenId, Number(data.message.id) || 0);
        scrollBottom();
      }
      refreshSidebar();
    } catch (error) {
      document.querySelector(`[data-message-id="${tempKey}"]`)?.remove();
      if (selectedGeneration === generation) {
        if (!input.value.trim()) input.value = typed;
        if (savedReply) setReply(savedReply);
        if (originalFile) setPending(originalFile);
        setStatus(`${error.message || 'Mensagem não enviada'} — tente novamente`);
        input.focus();
      }
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
    generation++; view = 'conversations'; contactId = ''; setTabs(); clearPending(); clearReply(); exitSelect(); renderPins([]);
    olderWrap.hidden = true; delete olderWrap.dataset.initialized;
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

  // ------------------------- opções das mensagens -------------------------
  const menu = document.createElement('div');
  menu.className = 'dbm-msg-menu';
  menu.hidden = true;
  menu.setAttribute('role', 'menu');
  document.body.appendChild(menu);
  const replyBar = $('dbmReplyBar');
  const selectBar = $('dbmSelectBar');
  const pinBar = $('dbmPinBar');
  const fwd = $('dbmForwardOverlay');
  let pinned = [];
  let pinIndex = 0;
  let forwardKeys = [];

  const info = (key) => {
    if (messageInfo.has(key)) return messageInfo.get(key);
    const el = list.querySelector(`[data-message-id="${CSS.escape(key)}"]`);
    return el ? {key, mine: el.classList.contains('mine'), name: el.querySelector('strong')?.textContent || 'Usuário', realName: el.querySelector('strong')?.textContent || 'Usuário', contactId: '', message: el.querySelector('p')?.textContent || '', attachment: null} : null;
  };
  const plain = (m) => { const part = splitMessage(m.message); return part.text || (m.attachment ? `📎 ${m.attachment.name}` : ''); };
  const short = (t) => { const x = String(t || '').replace(/\s+/g, ' ').trim(); return x.length > 90 ? `${x.slice(0, 90)}…` : x; };
  const pinnedKeys = () => new Set(pinned.map((p) => p.key));

  const ICON = {
    reply: '<svg viewBox="0 0 24 24"><path d="M9 14 4 9l5-5"/><path d="M4 9h10a6 6 0 0 1 6 6v4"/></svg>',
    replyPrivate: '<svg viewBox="0 0 24 24"><circle cx="9" cy="8" r="3.2"/><path d="M3.5 19a5.5 5.5 0 0 1 9.5-3.8"/><path d="m16 13-3 3 3 3"/><path d="M13 16h5a3 3 0 0 1 3 3"/></svg>',
    chat: '<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="14" rx="2"/><path d="M7 9h10M7 13h6"/></svg>',
    copy: '<svg viewBox="0 0 24 24"><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/></svg>',
    forward: '<svg viewBox="0 0 24 24"><path d="m15 14 5-5-5-5"/><path d="M20 9H10a6 6 0 0 0-6 6v4"/></svg>',
    pin: '<svg viewBox="0 0 24 24"><path d="M12 17v5"/><path d="M9 3h6l-1 6 3 3v2H7v-2l3-3z"/></svg>',
    star: '<svg viewBox="0 0 24 24"><path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.3 6.5 20.2l1-6.2L3 9.6l6.2-.9z"/></svg>',
    select: '<svg viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="3"/><path d="m8 12 3 3 5-6"/></svg>',
    report: '<svg viewBox="0 0 24 24"><path d="M10 15H5a2 2 0 0 1-2-2l1.5-7A2 2 0 0 1 6.5 4H17v10l-4 6a2 2 0 0 1-3-1.5z"/><path d="M17 4h3v10h-3"/></svg>',
    trash: '<svg viewBox="0 0 24 24"><path d="M4 7h16M10 11v6M14 11v6"/><path d="M6 7l1 13h10l1-13M9 7V4h6v3"/></svg>',
  };

  function closeMenu() { menu.hidden = true; menu.innerHTML = ''; }

  function openMenu(key, anchor) {
    const m = info(key);
    if (!m) return;
    const team = view === 'team';
    const firstName = String(m.realName || '').split(' ')[0] || 'contato';
    const items = [
      ['reply', 'Responder'],
      ...(team && !m.mine && m.contactId ? [['replyPrivate', 'Responder em particular'], ['chat', `Conversar com ${firstName}`]] : []),
      ['copy', 'Copiar'],
      ['forward', 'Encaminhar'],
      [pinnedKeys().has(key) ? 'unpin' : 'pin', pinnedKeys().has(key) ? 'Desafixar' : 'Fixar'],
      [favorites.has(key) ? 'unfav' : 'fav', favorites.has(key) ? 'Desfavoritar' : 'Favoritar'],
      '-',
      ['select', 'Selecionar'],
      '-',
      ...(!m.mine ? [['report', 'Denunciar']] : []),
      ...(m.mine ? [['delete', 'Apagar']] : []),
    ];
    const icon = {unpin: 'pin', fav: 'star', unfav: 'star', delete: 'trash'};
    menu.innerHTML = items.map((it) => it === '-' ? '<hr>' : `<button type="button" role="menuitem" data-menu-action="${it[0]}" data-key="${esc(key)}" class="${it[0] === 'delete' || it[0] === 'report' ? 'danger' : ''}">${ICON[icon[it[0]] || it[0]] || ''}<span>${esc(it[1])}</span></button>`).join('').replace(/(<hr>)+$/, '').replace(/<hr><hr>/g, '<hr>');
    menu.hidden = false;
    const r = anchor.getBoundingClientRect();
    const w = menu.offsetWidth, h = menu.offsetHeight;
    let left = Math.min(window.innerWidth - w - 8, Math.max(8, r.right - w));
    let top = r.bottom + 4;
    if (top + h > window.innerHeight - 8) top = Math.max(8, r.top - h - 4);
    menu.style.left = `${left}px`;
    menu.style.top = `${top}px`;
    menu.querySelector('button')?.focus({preventScroll: true});
  }

  function setReply(m) {
    replyTo = {key: m.key, name: m.realName || m.name, text: short(plain(m))};
    if (!replyBar) return;
    replyBar.innerHTML = `<div><b>Respondendo a ${esc(replyTo.name)}</b><span>${esc(replyTo.text)}</span></div><button type="button" aria-label="Cancelar resposta" id="dbmReplyCancel">✕</button>`;
    replyBar.hidden = false;
    $('dbmReplyCancel')?.addEventListener('click', clearReply);
    input?.focus();
  }
  function clearReply() { replyTo = null; if (replyBar) { replyBar.hidden = true; replyBar.innerHTML = ''; } }

  async function postJSON(url, body) {
    const res = await fetch(url, {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json', Accept: 'application/json'}, body: JSON.stringify({...body, csrf_token: csrf})});
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.ok) throw new Error(data.message || 'Não foi possível concluir.');
    return data;
  }

  async function copyKeys(keys) {
    const text = keys.map(info).filter(Boolean).map((m) => keys.length > 1 ? `${m.realName}: ${plain(m)}` : plain(m)).join('\n');
    try { await navigator.clipboard.writeText(text); setStatus(keys.length > 1 ? 'Mensagens copiadas' : 'Mensagem copiada'); }
    catch (_) { setStatus('Não foi possível copiar'); }
  }

  async function messageAction(action, keys, extra = {}) {
    try {
      const data = await postJSON('/company/chat/messages/action', {action, message_ids: keys, ...extra});
      if (action === 'delete') {
        (data.deleted || keys).forEach((k) => { list.querySelector(`[data-message-id="${CSS.escape(k)}"]`)?.remove(); messageInfo.delete(k); });
        setStatus(keys.length > 1 ? 'Mensagens apagadas' : 'Mensagem apagada');
        refreshSidebar();
      } else if (action === 'report') setStatus('Denúncia enviada aos administradores');
      else if (action === 'pin') setStatus('Mensagem fixada');
      else if (action === 'unpin') setStatus('Mensagem desafixada');
      else if (action === 'fav') setStatus('Adicionada às favoritas');
      else if (action === 'unfav') setStatus('Removida das favoritas');
      await loadFlags();
    } catch (err) { setStatus(err.message || 'Erro'); }
  }

  function applyFavorites() {
    list.querySelectorAll('[data-message-id]').forEach((el) => el.classList.toggle('is-fav', favorites.has(el.dataset.messageId)));
  }

  function renderPins(items) {
    pinned = items || [];
    list.querySelectorAll('.dbm-msg.is-pinned').forEach((el) => el.classList.remove('is-pinned'));
    pinned.forEach((p) => list.querySelector(`[data-message-id="${CSS.escape(p.key)}"]`)?.classList.add('is-pinned'));
    if (!pinBar) return;
    if (!pinned.length) { pinBar.hidden = true; pinBar.innerHTML = ''; return; }
    if (pinIndex >= pinned.length) pinIndex = 0;
    const p = pinned[pinIndex];
    pinBar.innerHTML = `<button type="button" class="dbm-pin-main" data-pin-go="${esc(p.key)}">${ICON.pin}<span><b>${esc(p.user_name)}${pinned.length > 1 ? ` · ${pinIndex + 1}/${pinned.length}` : ''}</b>${esc(short(splitMessage(p.text).text || p.text))}</span></button><button type="button" class="dbm-pin-x" data-pin-remove="${esc(p.key)}" title="Desafixar" aria-label="Desafixar">✕</button>`;
    pinBar.hidden = false;
  }

  async function loadFlags() {
    const team = view === 'team';
    if (!team && !contactId) { favorites = new Set(); renderPins([]); return; }
    const current = generation;
    try {
      const data = await getJSON(`/company/chat/flags?${team ? 'view=team' : `contact=${encodeURIComponent(contactId)}`}`);
      if (current !== generation) return;
      favorites = new Set(data.favorites || []);
      applyFavorites();
      renderPins(data.pinned || []);
    } catch (_) { /* tenta na próxima */ }
  }

  function goToMessage(key) {
    const el = list.querySelector(`[data-message-id="${CSS.escape(key)}"]`);
    if (!el) { setStatus('Mensagem fixada mais antiga — use "Carregar mensagens anteriores"'); return; }
    el.scrollIntoView({behavior: 'smooth', block: 'center'});
    el.classList.add('is-flash');
    setTimeout(() => el.classList.remove('is-flash'), 1600);
  }

  // ----- seleção -----
  function updateSelectBar() {
    if (!selectBar) return;
    const keys = [...selected];
    const allMine = keys.length && keys.every((k) => info(k)?.mine);
    selectBar.querySelector('[data-sel-count]').textContent = `${keys.length} selecionada(s)`;
    selectBar.querySelectorAll('[data-sel-action]').forEach((b) => { b.disabled = !keys.length || (b.dataset.selAction === 'delete' && !allMine); });
  }
  function enterSelect(firstKey) {
    selecting = true;
    selected.clear();
    shell.classList.add('is-selecting');
    if (firstKey) toggleSelect(firstKey);
    if (selectBar) selectBar.hidden = false;
    form.classList.add('is-hidden-by-select');
    updateSelectBar();
  }
  function exitSelect() {
    selecting = false;
    selected.clear();
    shell.classList.remove('is-selecting');
    list.querySelectorAll('.dbm-msg.is-selected').forEach((el) => el.classList.remove('is-selected'));
    if (selectBar) selectBar.hidden = true;
    form?.classList.remove('is-hidden-by-select');
  }
  function toggleSelect(key) {
    const el = list.querySelector(`[data-message-id="${CSS.escape(key)}"]`);
    if (!el || key.startsWith('temp-')) return;
    if (selected.has(key)) selected.delete(key); else selected.add(key);
    el.classList.toggle('is-selected', selected.has(key));
    updateSelectBar();
  }

  // ----- encaminhar -----
  async function openForward(keys) {
    forwardKeys = keys.filter((k) => !k.startsWith('temp-'));
    if (!forwardKeys.length || !fwd) return;
    const holder = $('dbmForwardList');
    const note = $('dbmForwardNotice');
    $('dbmForwardSearch').value = '';
    note.textContent = '';
    holder.innerHTML = '<div class="dbm-fwd-empty">Carregando contatos...</div>';
    fwd.classList.add('open');
    fwd.setAttribute('aria-hidden', 'false');
    $('dbmForwardSend').disabled = true;
    try {
      const data = await getJSON('/company/chat/sidebar?limit=50');
      const seen = new Set();
      const rows = [];
      if (hasCompany) rows.push({contact_id: 'group', name: data.group?.name || companyName, sub: 'Chat da empresa', group: true});
      [...(data.conversations || []), ...(data.contacts || [])].forEach((c) => {
        if (!c?.contact_id || c.is_me || c.active === false || seen.has(c.contact_id)) return;
        seen.add(c.contact_id);
        rows.push({contact_id: c.contact_id, name: c.name, sub: c.last_at ? `Última mensagem ${when(c.last_at)} • ${c.contact_id}` : `ID ${c.contact_id}`});
      });
      holder.innerHTML = rows.map((c) => `<label class="dbm-fwd-row" data-fwd-search="${esc(`${c.name} ${c.contact_id}`.toLowerCase())}"><input type="checkbox" value="${esc(c.contact_id)}"><span class="dbm-avatar">${c.group ? '👥' : esc((c.name || '?').charAt(0).toUpperCase())}</span><span class="dbm-chat-copy"><strong>${esc(c.name)}</strong><small>${esc(c.sub)}</small></span></label>`).join('') || '<div class="dbm-fwd-empty">Nenhum contato. Adicione pela agenda.</div>';
    } catch (_) { holder.innerHTML = '<div class="dbm-fwd-empty">Erro ao carregar os contatos.</div>'; }
  }
  function closeForward() { fwd?.classList.remove('open'); fwd?.setAttribute('aria-hidden', 'true'); }

  fwd?.addEventListener('change', () => { $('dbmForwardSend').disabled = !fwd.querySelector('#dbmForwardList input:checked'); });
  $('dbmForwardSearch')?.addEventListener('input', (e) => {
    const q = e.target.value.trim().toLowerCase();
    fwd.querySelectorAll('[data-fwd-search]').forEach((el) => { el.hidden = !!q && !el.dataset.fwdSearch.includes(q); });
  });
  $('dbmForwardClose')?.addEventListener('click', closeForward);
  fwd?.addEventListener('click', (e) => { if (e.target === fwd) closeForward(); });
  $('dbmForwardSend')?.addEventListener('click', async () => {
    const button = $('dbmForwardSend');
    const targets = [...fwd.querySelectorAll('#dbmForwardList input:checked')].map((i) => i.value);
    if (!targets.length) return;
    button.disabled = true;
    $('dbmForwardNotice').textContent = 'Encaminhando...';
    try {
      await postJSON('/company/chat/forward', {message_ids: forwardKeys, targets});
      $('dbmForwardNotice').textContent = 'Encaminhado ✓';
      exitSelect();
      setTimeout(closeForward, 700);
      loadCurrent(); refreshSidebar();
    } catch (err) { $('dbmForwardNotice').textContent = err.message || 'Erro ao encaminhar'; button.disabled = false; }
  });

  async function runAction(action, key) {
    const m = info(key);
    if (!m) return;
    if (action === 'reply') setReply(m);
    else if (action === 'replyPrivate' || action === 'chat') {
      const reply = action === 'replyPrivate' ? m : null;
      openPrivate(m.contactId);
      if (reply) setReply(reply);
    } else if (action === 'copy') copyKeys([key]);
    else if (action === 'forward') openForward([key]);
    else if (action === 'select') enterSelect(key);
    else if (action === 'report') {
      const reason = window.prompt('Denunciar mensagem aos administradores da empresa.\nMotivo (opcional):', '');
      if (reason === null) return;
      messageAction('report', [key], {reason});
    } else if (action === 'delete') {
      if (!window.confirm('Apagar esta mensagem para todos?')) return;
      messageAction('delete', [key]);
    } else messageAction(action, [key]);
  }

  list.addEventListener('click', (event) => {
    const btn = event.target.closest('[data-msg-menu]');
    if (btn) { event.preventDefault(); event.stopPropagation(); if (!menu.hidden && menu.dataset.for === btn.dataset.msgMenu) { closeMenu(); return; } menu.dataset.for = btn.dataset.msgMenu; openMenu(btn.dataset.msgMenu, btn); return; }
    if (selecting) {
      const row = event.target.closest('[data-message-id]');
      if (row && !event.target.closest('a')) { event.preventDefault(); toggleSelect(row.dataset.messageId); }
    }
  });
  list.addEventListener('contextmenu', (event) => {
    const row = event.target.closest('[data-message-id]');
    if (!row || row.dataset.messageId.startsWith('temp-') || event.target.closest('a')) return;
    event.preventDefault();
    const btn = row.querySelector('[data-msg-menu]');
    if (btn) { menu.dataset.for = btn.dataset.msgMenu; openMenu(btn.dataset.msgMenu, btn); }
  });
  menu.addEventListener('click', (event) => {
    const b = event.target.closest('[data-menu-action]');
    if (!b) return;
    const {menuAction, key} = b.dataset;
    closeMenu();
    runAction(menuAction, key);
  });
  document.addEventListener('click', (e) => { if (!menu.hidden && !menu.contains(e.target)) closeMenu(); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { closeMenu(); if (selecting) exitSelect(); closeForward(); } });
  list.addEventListener('scroll', closeMenu, {passive: true});
  window.addEventListener('resize', closeMenu);

  selectBar?.addEventListener('click', (e) => {
    const b = e.target.closest('[data-sel-action]');
    if (!b) return;
    const keys = [...selected];
    const action = b.dataset.selAction;
    if (action === 'cancel') { exitSelect(); return; }
    if (!keys.length) return;
    if (action === 'copy') { copyKeys(keys.sort((a, c) => Number(a.slice(2)) - Number(c.slice(2)))); exitSelect(); }
    else if (action === 'forward') openForward(keys);
    else if (action === 'fav') { messageAction('fav', keys); exitSelect(); }
    else if (action === 'delete') {
      if (!window.confirm(`Apagar ${keys.length} mensagem(ns) para todos?`)) return;
      messageAction('delete', keys).then(exitSelect);
    }
  });
  pinBar?.addEventListener('click', (e) => {
    const remove = e.target.closest('[data-pin-remove]');
    if (remove) { messageAction('unpin', [remove.dataset.pinRemove]); return; }
    const go = e.target.closest('[data-pin-go]');
    if (go) { goToMessage(go.dataset.pinGo); if (pinned.length > 1) { pinIndex = (pinIndex + 1) % pinned.length; renderPins(pinned); } }
  });

  // Mantém estrelas/fixadas nas mensagens novas que chegam.
  new MutationObserver(() => {
    if (favorites.size) applyFavorites();
    if (pinned.length) pinned.forEach((p) => list.querySelector(`[data-message-id="${CSS.escape(p.key)}"]`)?.classList.add('is-pinned'));
  }).observe(list, {childList: true});

  // ------------------------- ciclo -------------------------
  setTabs(); updateCompose();
  if (view === 'team' || contactId) { loadCurrent(); loadFlags(); }
  setInterval(() => { if (!document.hidden) loadCurrent(); }, 1600);
  setInterval(() => { if (!document.hidden) { refreshSidebar(); loadFlags(); } }, 7000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) { loadCurrent(); refreshSidebar(); } });
})();
