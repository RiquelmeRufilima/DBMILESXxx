(() => {
  'use strict';

  const shell = document.querySelector('.chat-shell');
  const list = document.getElementById('chatMessages');
  const form = document.getElementById('chatForm');
  const input = document.getElementById('chatInput');
  const status = document.getElementById('chatStatus');
  if (!shell || !list || !form || !input) return;

  // O chat nunca deve disparar o loader global.
  form.dataset.noLoader = '1';
  window.dbmHideLoader?.();

  const userId = Number(shell.dataset.userId || document.body?.dataset.currentUserId || 0);
  const POLL_MS = 900;
  const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
  let socket = null;
  let reconnectTimer = null;
  let pollBusy = false;
  let lastIncomingId = 0;

  list.scrollTop = list.scrollHeight;

  // ---------- SOM ----------
  let audioContext = null;
  function soundsEnabled() {
    const value = localStorage.getItem('dbmilesx:sounds-enabled');
    return value !== '0' && value !== 'false' && value !== 'off';
  }
  function unlockAudio() {
    if (!soundsEnabled()) return;
    try {
      audioContext ||= new (window.AudioContext || window.webkitAudioContext)();
      if (audioContext.state === 'suspended') audioContext.resume().catch(() => {});
    } catch (_) {}
  }
  document.addEventListener('pointerdown', unlockAudio, { once: true, passive: true });
  document.addEventListener('keydown', unlockAudio, { once: true });

  function playIncomingSound() {
    if (!soundsEnabled()) return;
    try {
      unlockAudio();
      if (!audioContext) return;
      const now = audioContext.currentTime;
      const gain = audioContext.createGain();
      gain.gain.setValueAtTime(0.0001, now);
      gain.gain.exponentialRampToValueAtTime(0.12, now + 0.015);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.34);
      gain.connect(audioContext.destination);

      [740, 980].forEach((freq, index) => {
        const osc = audioContext.createOscillator();
        osc.type = 'sine';
        osc.frequency.setValueAtTime(freq, now + index * 0.08);
        osc.connect(gain);
        osc.start(now + index * 0.08);
        osc.stop(now + 0.30 + index * 0.08);
      });
    } catch (_) {}
  }

  // ---------- MENSAGENS ----------
  function formatDate(value) {
    const date = value ? new Date(value) : new Date();
    return date.toLocaleString('pt-BR', {
      day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'
    });
  }

  function findOptimistic(message) {
    const nodes = [...list.querySelectorAll('[data-temp-message="1"]')].reverse();
    return nodes.find(node => node.querySelector('.chat-bubble p')?.textContent === message) || null;
  }

  function renderMessage(item, { optimistic = false, silent = false } = {}) {
    const id = String(item.id ?? '');
    if (id && list.querySelector(`[data-message-id="${CSS.escape(id)}"]`)) return false;

    const mine = Number(item.user_id) === userId || optimistic;

    // Se esta é a confirmação do servidor para uma mensagem otimista, apenas reconcilia.
    if (!optimistic && mine) {
      const temp = findOptimistic(String(item.message || ''));
      if (temp) {
        temp.dataset.messageId = id;
        delete temp.dataset.tempMessage;
        temp.classList.remove('sending');
        const strong = temp.querySelector('.chat-bubble strong');
        const small = temp.querySelector('.chat-bubble small');
        if (strong) strong.textContent = item.user_name || strong.textContent;
        if (small) small.textContent = formatDate(item.created_at);
        return true;
      }
    }

    const article = document.createElement('article');
    article.className = `chat-message ${mine ? 'mine' : ''}${optimistic ? ' sending' : ''}`;
    article.dataset.messageId = id || `temp-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    if (optimistic) article.dataset.tempMessage = '1';

    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble';
    const strong = document.createElement('strong');
    strong.textContent = item.user_name || (mine ? 'Você' : 'Equipe');
    const p = document.createElement('p');
    p.textContent = item.message || '';
    const small = document.createElement('small');
    small.textContent = optimistic ? 'Enviando…' : formatDate(item.created_at);
    bubble.append(strong, p, small);
    article.appendChild(bubble);
    list.appendChild(article);
    list.scrollTop = list.scrollHeight;

    if (!optimistic && !mine && !silent) {
      const numericId = Number(item.id || 0);
      if (!numericId || numericId > lastIncomingId) {
        playIncomingSound();
        if (numericId) lastIncomingId = numericId;
      }
    }
    return true;
  }

  // Marca o maior ID já exibido ao abrir para não tocar som para mensagens antigas.
  list.querySelectorAll('[data-message-id]').forEach(node => {
    const id = Number(node.dataset.messageId || 0);
    if (Number.isFinite(id)) lastIncomingId = Math.max(lastIncomingId, id);
  });

  // ---------- WEBSOCKET ----------
  function setStatus(text) {
    if (status) status.textContent = text;
  }

  function connect() {
    clearTimeout(reconnectTimer);
    try {
      socket = new WebSocket(`${protocol}://${location.host}/company/ws/chat`);
    } catch (_) {
      socket = null;
      reconnectTimer = setTimeout(connect, 1800);
      return;
    }

    socket.addEventListener('open', () => setStatus('Conectado em tempo real'));
    socket.addEventListener('message', event => {
      try {
        const item = JSON.parse(event.data);
        renderMessage(item);
      } catch (_) {}
    });
    socket.addEventListener('close', () => {
      setStatus('Sincronizando…');
      reconnectTimer = setTimeout(connect, 1800);
    });
    socket.addEventListener('error', () => {
      try { socket.close(); } catch (_) {}
    });
  }
  connect();

  // ---------- FALLBACK ENTRE INSTÂNCIAS/COMPUTADORES ----------
  async function pollMessages() {
    if (pollBusy || document.visibilityState === 'hidden') return;
    pollBusy = true;
    try {
      const response = await fetch(`/company/messages?_=${Date.now()}`, {
        credentials: 'same-origin',
        cache: 'no-store',
        headers: { 'Accept': 'application/json', 'Cache-Control': 'no-cache' }
      });
      if (!response.ok) return;
      const data = await response.json();
      const messages = Array.isArray(data.messages) ? data.messages : [];
      for (const item of messages) renderMessage(item);
    } catch (_) {
      // WebSocket continua sendo tentado; polling tenta novamente no próximo ciclo.
    } finally {
      pollBusy = false;
    }
  }
  const pollTimer = setInterval(pollMessages, POLL_MS);
  window.addEventListener('focus', pollMessages);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') pollMessages();
  });

  // ---------- ENVIO INSTANTÂNEO ----------
  form.addEventListener('submit', event => {
    event.preventDefault();
    event.stopPropagation();
    window.dbmHideLoader?.();

    const message = input.value.trim();
    if (!message) return;

    if (!socket || socket.readyState !== WebSocket.OPEN) {
      setStatus('Reconectando… aguarde um instante');
      return;
    }

    // Aparece na própria tela imediatamente, antes da resposta do servidor.
    renderMessage({
      id: '', user_id: userId, user_name: 'Você', message, created_at: new Date().toISOString()
    }, { optimistic: true, silent: true });

    socket.send(JSON.stringify({ message }));
    input.value = '';
    input.focus();

    // Puxa confirmação rapidamente e reconcilia o item otimista.
    setTimeout(pollMessages, 180);
  });

  window.addEventListener('beforeunload', () => {
    clearInterval(pollTimer);
    clearTimeout(reconnectTimer);
    try { socket?.close(); } catch (_) {}
  });
})();
