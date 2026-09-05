(() => {
  const shell = document.querySelector('.chat-shell');
  const list = document.getElementById('chatMessages');
  const form = document.getElementById('chatForm');
  const input = document.getElementById('chatInput');
  const attachmentInput = document.getElementById('chatAttachment');
  const filePreview = document.getElementById('chatFilePreview');
  const status = document.getElementById('chatStatus');
  if (!shell || !list || !form || !input || !status) return;

  const userId = Number(shell.dataset.userId || 0);
  const csrfToken = shell.dataset.csrfToken || '';
  let connected = Boolean(window.DBMILESXRealtime?.isConnected?.());
  let sending = false;
  let pendingFile = null;
  list.scrollTop = list.scrollHeight;

  const formatSize = (bytes) => bytes > 1024 * 1024
    ? `${(bytes / 1024 / 1024).toFixed(1)} MB`
    : `${Math.max(1, Math.round(bytes / 1024))} KB`;

  function currentFile() {
    return pendingFile || attachmentInput?.files?.[0] || null;
  }

  function avatarNode(item) {
    const avatar = item.avatar_url ? document.createElement('img') : document.createElement('span');
    avatar.className = `chat-avatar${item.avatar_url ? ' avatar-image' : ''}`;
    if (item.avatar_url) {
      avatar.src = item.avatar_url;
      avatar.alt = item.user_name || 'Usuário';
    } else {
      avatar.textContent = (item.user_name || '?').trim().charAt(0).toUpperCase() || '?';
    }
    avatar.dataset.userAvatarId = String(item.user_id);
    avatar.dataset.userName = item.user_name || '';
    return avatar;
  }

  function attachmentNode(item) {
    if (!item.attachment_url) return null;
    const isImage = String(item.attachment_type || '').startsWith('image/');
    const link = document.createElement('a');
    link.className = `chat-attachment ${isImage ? 'chat-image-attachment' : 'chat-pdf-attachment'}`;
    link.href = item.attachment_url;
    link.target = '_blank';
    link.rel = 'noopener';
    if (isImage) {
      const img = document.createElement('img');
      img.src = item.attachment_url;
      img.alt = item.attachment_name || 'Imagem do chat';
      link.appendChild(img);
    } else {
      const icon = document.createElement('span');
      icon.className = 'chat-file-icon';
      icon.textContent = 'PDF';
      link.appendChild(icon);
    }
    const label = document.createElement('span');
    label.textContent = `${item.attachment_name || 'Abrir anexo'}${item.attachment_size ? ` • ${formatSize(item.attachment_size)}` : ''}`;
    link.appendChild(label);
    return link;
  }

  function addSystemMessage(item) {
    const article = document.createElement('article');
    article.className = 'chat-message system-activity';
    article.dataset.messageId = item.id;
    article.dataset.messageKind = 'system';
    const pill = document.createElement('div');
    pill.className = 'chat-system-pill';
    const icon = document.createElement('span');
    icon.className = 'chat-system-icon';
    icon.textContent = '↻';
    const copy = document.createElement('span');
    copy.textContent = item.message || 'Cotação atualizada.';
    const small = document.createElement('small');
    const date = new Date(item.created_at);
    small.textContent = Number.isNaN(date.getTime()) ? '' : date.toLocaleString('pt-BR', { day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit' });
    pill.append(icon, copy, small);
    article.appendChild(pill);
    return article;
  }

  function addMessage(item) {
    if (!item?.id || list.querySelector(`[data-message-id="${item.id}"]`)) return;
    const isSystem = Boolean(item.is_system_activity) || String(item.attachment_type || '').startsWith('system/');
    if (isSystem) {
      list.appendChild(addSystemMessage(item));
      list.scrollTop = list.scrollHeight;
      return;
    }

    const mine = Number(item.user_id) === userId;
    const article = document.createElement('article');
    article.className = `chat-message ${mine ? 'mine' : 'theirs'}`;
    article.dataset.messageId = item.id;
    article.dataset.messageKind = 'user';
    article.appendChild(avatarNode(item));

    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble';
    const strong = document.createElement('strong');
    strong.textContent = mine ? 'Você' : (item.user_name || 'Usuário');
    strong.dataset.userNameId = String(item.user_id);
    bubble.appendChild(strong);
    if (item.message) {
      const p = document.createElement('p');
      p.textContent = item.message;
      bubble.appendChild(p);
    }
    const attachment = attachmentNode(item);
    if (attachment) bubble.appendChild(attachment);
    const small = document.createElement('small');
    const date = new Date(item.created_at);
    small.textContent = Number.isNaN(date.getTime()) ? '' : date.toLocaleString('pt-BR', { day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit' });
    bubble.appendChild(small);
    article.appendChild(bubble);
    list.appendChild(article);
    list.scrollTop = list.scrollHeight;
  }

  async function syncMessages() {
    try {
      const response = await fetch('/company/messages', { headers:{Accept:'application/json'}, cache:'no-store' });
      if (!response.ok) return;
      const payload = await response.json();
      (payload.messages || []).forEach(addMessage);
    } catch (_) {}
  }

  async function sendJson(message) {
    const response = await fetch('/company/messages/send', {
      method:'POST',
      headers:{'Content-Type':'application/json',Accept:'application/json','X-CSRF-Token':csrfToken},
      body:JSON.stringify({message,csrf_token:csrfToken})
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || !payload.ok) throw new Error(payload.message || 'Não foi possível enviar.');
    if (payload.message) addMessage(payload.message);
  }

  async function sendAttachment(message, file) {
    const data = new FormData();
    data.append('csrf_token', csrfToken);
    data.append('message', message);
    data.append('attachment', file);
    const response = await fetch('/company/messages/upload', {
      method:'POST',
      headers:{Accept:'application/json','X-CSRF-Token':csrfToken},
      body:data
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || !payload.ok) throw new Error(payload.message || 'Não foi possível enviar o arquivo.');
    if (payload.message) addMessage(payload.message);
  }

  function renderStatus(text='') {
    status.textContent = text || (connected ? 'Conectado em tempo real' : 'Modo de segurança ativo — sincronização automática');
    status.classList.toggle('online', connected);
  }

  function clearFile() {
    pendingFile = null;
    if (attachmentInput) attachmentInput.value = '';
    renderFilePreview();
  }

  function renderFilePreview() {
    const file = currentFile();
    if (!filePreview) return;
    if (!file) {
      filePreview.hidden = true;
      filePreview.replaceChildren();
      return;
    }
    filePreview.hidden = false;
    filePreview.replaceChildren();
    if (String(file.type || '').startsWith('image/')) {
      const img = document.createElement('img');
      img.className = 'chat-paste-preview-image';
      img.alt = file.name || 'Imagem colada';
      const url = URL.createObjectURL(file);
      img.src = url;
      img.addEventListener('load', () => URL.revokeObjectURL(url), { once:true });
      filePreview.appendChild(img);
    }
    const label = document.createElement('span');
    label.textContent = `${file.name} • ${formatSize(file.size)}`;
    filePreview.appendChild(label);
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.textContent = 'Remover';
    remove.addEventListener('click', clearFile);
    filePreview.appendChild(remove);
  }

  function usePastedImage(blob) {
    const subtype = String(blob.type || 'image/png').split('/')[1] || 'png';
    const extension = subtype === 'jpeg' ? 'jpg' : subtype;
    pendingFile = new File([blob], `imagem-colada-${Date.now()}.${extension}`, { type: blob.type || 'image/png' });
    if (attachmentInput && typeof DataTransfer !== 'undefined') {
      try {
        const transfer = new DataTransfer();
        transfer.items.add(pendingFile);
        attachmentInput.files = transfer.files;
      } catch (_) {}
    }
    renderFilePreview();
    renderStatus('Imagem colada. Escreva uma legenda opcional e clique em Enviar.');
  }

  function handlePaste(event) {
    const items = Array.from(event.clipboardData?.items || []);
    const imageItem = items.find(item => String(item.type || '').startsWith('image/'));
    if (!imageItem) return;
    const blob = imageItem.getAsFile();
    if (!blob) return;
    event.preventDefault();
    usePastedImage(blob);
  }

  window.addEventListener('dbmilesx:realtime', event => {
    const payload = event.detail || {};
    if (payload.type === 'chat_message') addMessage(payload);
  });
  window.addEventListener('dbmilesx:realtime-status', event => {
    connected = Boolean(event.detail?.connected);
    renderStatus();
    syncMessages();
  });

  attachmentInput?.addEventListener('change', () => {
    pendingFile = attachmentInput.files?.[0] || null;
    renderFilePreview();
  });
  input.addEventListener('paste', handlePaste);
  shell.addEventListener('paste', event => {
    if (event.target !== input) handlePaste(event);
  });

  form.addEventListener('submit', async event => {
    event.preventDefault();
    const message = input.value.trim();
    const file = currentFile();
    if ((!message && !file) || sending) return;
    if (file && file.size > 12 * 1024 * 1024) {
      renderStatus('O arquivo deve ter no máximo 12 MB.');
      return;
    }
    sending = true;
    const button = form.querySelector('button[type="submit"]');
    if (button) button.disabled = true;
    renderStatus('Enviando...');
    try {
      if (file) await sendAttachment(message, file);
      else {
        const realtimeSent = window.DBMILESXRealtime?.send?.({type:'chat_message',message}, false) === true;
        if (!realtimeSent) await sendJson(message);
      }
      input.value = '';
      clearFile();
      input.focus();
      setTimeout(syncMessages, 200);
      renderStatus();
    } catch (error) {
      renderStatus(error?.message || 'Falha ao enviar.');
    } finally {
      sending = false;
      if (button) button.disabled = false;
    }
  });

  input.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  // O WebSocket entrega mensagens imediatamente no Render. O polling fica
  // apenas como fallback e não consulta o servidor com a aba oculta.
  const fallbackPoll = () => {
    if (document.visibilityState !== 'visible' || connected) return;
    syncMessages();
  };
  setInterval(fallbackPoll, 12000);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') syncMessages();
  });
  renderStatus();
  syncMessages();
})();
