(() => {
  'use strict';

  const shell = document.querySelector('.chat-shell');
  const list = document.getElementById('chatMessages');
  const form = document.getElementById('chatForm');
  const input = document.getElementById('chatInput');
  const status = document.getElementById('chatStatus');
  const errorBox = document.getElementById('chatSendError');
  if (!shell || !list || !form || !input) return;

  // Blindagem: o loader global nunca deve aparecer no chat.
  form.dataset.noLoader = '1';
  form.querySelectorAll('button, input[type="submit"]').forEach(el => el.dataset.noLoader = '1');
  window.dbmHideLoader?.();

  const userId = Number(shell.dataset.userId || 0);
  const seen = new Set();
  let newestId = 0;
  let sending = false;
  let pollBusy = false;

  function parseDate(value) {
    const date = value ? new Date(value) : new Date();
    return Number.isNaN(date.getTime()) ? new Date() : date;
  }

  function formatDate(value) {
    return parseDate(value).toLocaleString('pt-BR', {
      day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'
    });
  }

  function playIncomingSound() {
    try {
      if (typeof window.dbmPlaySound === 'function') {
        window.dbmPlaySound('chat');
        return;
      }
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return;
      const ctx = new Ctx();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.frequency.setValueAtTime(740, ctx.currentTime);
      osc.frequency.exponentialRampToValueAtTime(980, ctx.currentTime + 0.12);
      gain.gain.setValueAtTime(0.0001, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.12, ctx.currentTime + 0.015);
      gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.18);
      osc.connect(gain); gain.connect(ctx.destination);
      osc.start(); osc.stop(ctx.currentTime + 0.2);
    } catch (_) {}
  }

  function addMessage(item, {incomingSound = false} = {}) {
    const id = Number(item?.id || 0);
    if (id && seen.has(id)) return false;
    if (id) {
      seen.add(id);
      newestId = Math.max(newestId, id);
    }

    const article = document.createElement('article');
    article.className = `chat-message ${Number(item.user_id) === userId ? 'mine' : ''}`;
    if (id) article.dataset.messageId = String(id);

    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble';
    const strong = document.createElement('strong');
    strong.textContent = item.user_name || 'Usuário';
    const p = document.createElement('p');
    p.textContent = item.message || '';
    const small = document.createElement('small');
    small.textContent = formatDate(item.created_at);
    bubble.append(strong, p, small);
    article.appendChild(bubble);
    list.appendChild(article);
    list.scrollTop = list.scrollHeight;

    if (incomingSound && Number(item.user_id) !== userId) playIncomingSound();
    return true;
  }

  // Normaliza as mensagens renderizadas pelo servidor e registra IDs existentes.
  list.querySelectorAll('[data-message-id]').forEach(node => {
    const id = Number(node.dataset.messageId || 0);
    if (id) { seen.add(id); newestId = Math.max(newestId, id); }
    const time = node.querySelector('small[data-created-at]');
    if (time) time.textContent = formatDate(time.dataset.createdAt);
  });
  list.scrollTop = list.scrollHeight;

  async function syncMessages() {
    if (pollBusy || document.hidden) return;
    pollBusy = true;
    try {
      const response = await fetch('/company/messages', {
        credentials: 'same-origin',
        cache: 'no-store',
        headers: { 'Accept': 'application/json', 'Cache-Control': 'no-cache' }
      });
      if (!response.ok) return;
      const data = await response.json();
      let received = false;
      for (const item of (data.messages || [])) {
        if (Number(item.id || 0) > newestId && Number(item.user_id) !== userId) {
          if (addMessage(item, {incomingSound: true})) received = true;
        } else {
          addMessage(item);
        }
      }
      if (status) status.textContent = received ? 'Nova mensagem recebida' : 'Sincronização ativa';
    } catch (_) {
      if (status) status.textContent = 'Reconectando...';
    } finally {
      pollBusy = false;
    }
  }

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation?.();
    window.dbmHideLoader?.();
    if (sending) return;

    const text = input.value.trim();
    if (!text) return;

    sending = true;
    const original = text;
    input.value = '';
    input.focus();
    if (errorBox) errorBox.hidden = true;

    // Otimista: aparece imediatamente, sem esperar a Vercel.
    const temp = {
      id: 0,
      user_id: userId,
      user_name: 'Você',
      message: original,
      created_at: new Date().toISOString()
    };
    const tempNode = document.createElement('article');
    tempNode.className = 'chat-message mine chat-message-pending';
    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble';
    bubble.innerHTML = '<strong>Você</strong>';
    const p = document.createElement('p'); p.textContent = original;
    const small = document.createElement('small'); small.textContent = 'Enviando...';
    bubble.append(p, small); tempNode.appendChild(bubble); list.appendChild(tempNode);
    list.scrollTop = list.scrollHeight;

    try {
      const fd = new FormData(form);
      fd.set('message', original);
      const response = await fetch('/company/messages/send', {
        method: 'POST', body: fd, credentials: 'same-origin',
        headers: { 'Accept': 'application/json' }
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.ok) throw new Error(data.error || 'Falha ao enviar a mensagem.');
      tempNode.remove();
      addMessage(data.message);
      if (status) status.textContent = 'Enviado';
    } catch (err) {
      tempNode.classList.add('chat-message-error');
      small.textContent = 'Falha no envio';
      input.value = original;
      if (errorBox) {
        errorBox.textContent = err?.message || 'Não foi possível enviar a mensagem.';
        errorBox.hidden = false;
      }
    } finally {
      sending = false;
      window.dbmHideLoader?.();
    }
  }, true);

  // Vercel Serverless: usa HTTP curto em vez de WebSocket persistente.
  syncMessages();
  const timer = setInterval(syncMessages, 700);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) syncMessages();
  });
  window.addEventListener('beforeunload', () => clearInterval(timer));
})();
