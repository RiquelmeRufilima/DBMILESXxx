(() => {
  const body = document.body;
  const companyId = Number(body?.dataset.companyId || 0);
  const currentUserId = Number(body?.dataset.currentUserId || 0);
  if (!body || !companyId) return;

  // Sons são exclusivos para:
  // 1) mensagens reais do chat;
  // 2) eventos de tarefas.
  // Atualizações automáticas/sistêmicas do chat NÃO fazem som.
  let audioContext = null;
  let audioUnlocked = false;
  let lastSoundAt = 0;

  function unlockAudio() {
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (!AudioCtx) return;
      audioContext ||= new AudioCtx();
      if (audioContext.state === 'suspended') audioContext.resume().catch(() => {});
      audioUnlocked = true;
    } catch (_) {}
  }

  ['pointerdown', 'keydown', 'touchstart'].forEach((name) => {
    window.addEventListener(name, unlockAudio, { once: true, passive: true });
  });

  function playNotificationSound(kind) {
    const now = Date.now();
    if (now - lastSoundAt < 450) return;
    lastSoundAt = now;
    if (!audioUnlocked) unlockAudio();
    if (!audioContext || audioContext.state !== 'running') return;

    const sequences = {
      chat: [
        [0.00, 740, 0.13, 0.045],
        [0.11, 990, 0.17, 0.05],
      ],
      task: [
        [0.00, 520, 0.11, 0.04],
        [0.10, 660, 0.11, 0.045],
        [0.20, 820, 0.16, 0.05],
      ],
    };
    const sequence = sequences[kind];
    if (!sequence) return;

    const start = audioContext.currentTime + 0.01;
    sequence.forEach(([offset, frequency, duration, volume]) => {
      const osc = audioContext.createOscillator();
      const gain = audioContext.createGain();
      osc.type = 'sine';
      osc.frequency.setValueAtTime(frequency, start + offset);
      gain.gain.setValueAtTime(0.0001, start + offset);
      gain.gain.exponentialRampToValueAtTime(volume, start + offset + 0.018);
      gain.gain.exponentialRampToValueAtTime(0.0001, start + offset + duration);
      osc.connect(gain);
      gain.connect(audioContext.destination);
      osc.start(start + offset);
      osc.stop(start + offset + duration + 0.02);
    });
  }

  function isSystemChat(payload) {
    return Boolean(payload?.is_system_activity)
      || String(payload?.attachment_type || '').startsWith('system/')
      || String(payload?.activity_event || '').trim() !== '';
  }

  function maybePlayEventSound(payload) {
    const type = String(payload?.type || '');
    if (type === 'chat_message') {
      const senderId = Number(payload?.user_id || 0);
      if (!isSystemChat(payload) && senderId && senderId !== currentUserId) {
        playNotificationSound('chat');
      }
      return;
    }
    if (type === 'task_event') {
      const actorId = Number(payload?.actor_user_id || 0);
      if (!actorId || actorId !== currentUserId) playNotificationSound('task');
    }
  }

  let socket = null;
  let retryTimer = null;
  let heartbeat = null;
  let retryDelay = 900;
  const queue = [];

  function emit(name, detail) {
    window.dispatchEvent(new CustomEvent(name, { detail }));
  }

  function buildAvatarNode(current, avatarUrl, userName, userId) {
    const commonClass = current.className || 'avatar';
    let node;
    if (avatarUrl) {
      node = document.createElement('img');
      node.className = commonClass.includes('avatar-image') ? commonClass : `${commonClass} avatar-image`;
      node.src = avatarUrl;
      node.alt = userName || 'Usuário';
    } else {
      node = document.createElement('span');
      node.className = commonClass.replace(/\bavatar-image\b/g, '').replace(/\s+/g, ' ').trim();
      node.textContent = (userName || '?').trim().charAt(0).toUpperCase() || '?';
    }
    node.dataset.userAvatarId = String(userId);
    node.dataset.userName = userName || '';
    return node;
  }

  function updateProfile(payload) {
    const userId = Number(payload.user_id || 0);
    if (!userId) return;
    const userName = payload.user_name || 'Usuário';
    document.querySelectorAll(`[data-user-avatar-id="${userId}"]`).forEach((element) => {
      const replacement = buildAvatarNode(element, payload.avatar_url || null, userName, userId);
      element.replaceWith(replacement);
    });
    document.querySelectorAll(`[data-user-name-id="${userId}"]`).forEach((element) => {
      element.textContent = userName;
    });
  }

  function receive(payload) {
    if (payload?.type === 'profile_updated') updateProfile(payload);
    maybePlayEventSound(payload || {});
    emit('dbmilesx:realtime', payload || {});
  }

  function setStatus(connected) {
    emit('dbmilesx:realtime-status', { connected });
  }

  function flushQueue() {
    while (queue.length && socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(queue.shift()));
    }
  }

  function connect() {
    clearTimeout(retryTimer);
    const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
    socket = new WebSocket(`${protocol}://${location.host}/company/ws/realtime`);

    socket.addEventListener('open', () => {
      retryDelay = 900;
      setStatus(true);
      flushQueue();
      clearInterval(heartbeat);
      heartbeat = setInterval(() => {
        if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'ping' }));
      }, 25000);
    });

    socket.addEventListener('message', (event) => {
      try { receive(JSON.parse(event.data)); } catch (_) {}
    });

    socket.addEventListener('close', () => {
      clearInterval(heartbeat);
      setStatus(false);
      retryTimer = setTimeout(connect, retryDelay);
      retryDelay = Math.min(Math.round(retryDelay * 1.7), 12000);
    });

    socket.addEventListener('error', () => {
      try { socket.close(); } catch (_) {}
    });
  }

  window.DBMILESXRealtime = {
    send(payload, queueWhenOffline = true) {
      if (socket?.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify(payload));
        return true;
      }
      if (queueWhenOffline) queue.push(payload);
      return false;
    },
    isConnected() {
      return socket?.readyState === WebSocket.OPEN;
    },
  };

  connect();
})();
