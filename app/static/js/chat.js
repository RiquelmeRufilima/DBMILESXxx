(() => {
  const shell = document.querySelector('.chat-shell');
  const list = document.getElementById('chatMessages');
  const form = document.getElementById('chatForm');
  const input = document.getElementById('chatInput');
  const status = document.getElementById('chatStatus');
  if (!shell || !list || !form || !input) return;

  const userId = Number(shell.dataset.userId || 0);
  let socket = null;
  let reconnectTimer = null;
  let pollTimer = null;
  let lastKnownId = 0;
  let sending = false;

  // O chat nunca deve ativar o loader global.
  form.dataset.noLoader = '1';

  function playChatSound() {
    try { window.DBMILESXSound?.play?.('chat'); } catch (_) {}
  }

  function formatDate(value) {
    const date = new Date(value || Date.now());
    return date.toLocaleString('pt-BR', {
      day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'
    });
  }

  function makeClientId() {
    if (window.crypto?.randomUUID) return window.crypto.randomUUID();
    return `chat-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  }

  function createMessageNode(item, { pending = false } = {}) {
    const article = document.createElement('article');
    article.className = `chat-message ${Number(item.user_id) === userId ? 'mine' : ''}`;
    if (item.id) article.dataset.messageId = String(item.id);
    if (item.client_id) article.dataset.clientId = String(item.client_id);
    if (pending) article.dataset.pending = '1';

    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble';
    const strong = document.createElement('strong');
    strong.textContent = item.user_name || 'Você';
    const p = document.createElement('p');
    p.textContent = item.message || '';
    const small = document.createElement('small');
    small.textContent = pending ? 'Enviando…' : formatDate(item.created_at);

    bubble.append(strong, p, small);
    article.appendChild(bubble);
    return article;
  }

  function reconcilePending(item) {
    if (!item?.client_id) return false;
    const pending = list.querySelector(`[data-client-id="${CSS.escape(String(item.client_id))}"]`);
    if (!pending) return false;
    pending.dataset.messageId = String(item.id || '');
    delete pending.dataset.pending;
    const small = pending.querySelector('small');
    if (small) small.textContent = formatDate(item.created_at);
    return true;
  }

  function addMessage(item, { playSound = true } = {}) {
    if (!item) return;
    const id = Number(item.id || 0);
    if (id && list.querySelector(`[data-message-id="${id}"]`)) {
      lastKnownId = Math.max(lastKnownId, id);
      return;
    }
    if (reconcilePending(item)) {
      if (id) lastKnownId = Math.max(lastKnownId, id);
      return;
    }

    const article = createMessageNode(item);
    list.appendChild(article);
    if (id) lastKnownId = Math.max(lastKnownId, id);
    list.scrollTop = list.scrollHeight;

    if (playSound && Number(item.user_id || 0) !== userId) playChatSound();
  }

  // Descobre o último ID renderizado pelo servidor.
  list.querySelectorAll('[data-message-id]').forEach((el) => {
    lastKnownId = Math.max(lastKnownId, Number(el.dataset.messageId || 0));
  });
  list.scrollTop = list.scrollHeight;

  async function pollMessages() {
    try {
      const response = await fetch('/company/messages', {
        cache: 'no-store',
        headers: { 'Accept': 'application/json' },
      });
      if (!response.ok) return;
      const data = await response.json();
      const messages = Array.isArray(data?.messages) ? data.messages : [];
      messages.forEach((item) => {
        const id = Number(item.id || 0);
        if (id > lastKnownId) addMessage(item, { playSound: true });
      });
    } catch (_) {}
  }

  function startPolling() {
    clearInterval(pollTimer);
    // Fallback entre instâncias/servidores: mantém outro computador sincronizado.
    pollTimer = setInterval(pollMessages, 900);
  }

  const protocol = location.protocol === 'https:' ? 'wss' : 'ws';

  function connect() {
    clearTimeout(reconnectTimer);
    try {
      socket = new WebSocket(`${protocol}://${location.host}/company/ws/chat`);
    } catch (_) {
      if (status) status.textContent = 'Sincronizando…';
      reconnectTimer = setTimeout(connect, 1500);
      return;
    }

    socket.addEventListener('open', () => {
      if (status) status.textContent = 'Conectado em tempo real';
      pollMessages();
    });

    socket.addEventListener('message', (event) => {
      try {
        const item = JSON.parse(event.data);
        addMessage(item, { playSound: true });
      } catch (_) {}
    });

    socket.addEventListener('close', () => {
      if (status) status.textContent = 'Sincronizando…';
      reconnectTimer = setTimeout(connect, 1200);
    });

    socket.addEventListener('error', () => {
      try { socket?.close(); } catch (_) {}
    });
  }

  function optimisticMessage(message, clientId) {
    const item = {
      id: 0,
      client_id: clientId,
      user_id: userId,
      user_name: shell.dataset.userName || 'Você',
      message,
      created_at: new Date().toISOString(),
    };
    const node = createMessageNode(item, { pending: true });
    list.appendChild(node);
    list.scrollTop = list.scrollHeight;
  }

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    event.stopPropagation();
    window.dbmHideLoader?.();

    const message = input.value.trim();
    if (!message || sending) return;

    if (!socket || socket.readyState !== WebSocket.OPEN) {
      if (status) status.textContent = 'Reconectando… tente novamente em um instante';
      connect();
      return;
    }

    sending = true;
    const clientId = makeClientId();
    optimisticMessage(message, clientId);
    input.value = '';
    input.focus();

    try {
      socket.send(JSON.stringify({ message, client_id: clientId }));
    } catch (_) {
      const pending = list.querySelector(`[data-client-id="${CSS.escape(clientId)}"]`);
      pending?.remove();
      input.value = message;
      if (status) status.textContent = 'Falha ao enviar. Tente novamente.';
    } finally {
      sending = false;
    }
  }, true);

  connect();
  startPolling();
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) pollMessages();
  });
})();
