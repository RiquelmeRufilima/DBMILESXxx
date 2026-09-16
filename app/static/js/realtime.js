(() => {
  "use strict";

  const body = document.body;
  const companyId = Number(body?.dataset.companyId || 0);
  const currentUserId = Number(body?.dataset.currentUserId || 0);
  if (!body || !companyId || !currentUserId) return;

  const CHAT_SOUND_URL = "/static/sounds/chat-notification.mp3";
  const CHAT_POLL_MS = 850;
  const chatPage = location.pathname === "/company/chat";
  const lastMessageKey = `dbmilesx:last-chat-message:${companyId}:${currentUserId}`;

  const chatAudio = new Audio(CHAT_SOUND_URL);
  chatAudio.preload = "auto";
  chatAudio.volume = 1.0;

  let audioUnlocked = false;
  let lastSoundAt = 0;
  let chatPolling = false;
  let chatInitialized = false;

  function soundsEnabled() {
    const disabled = new Set(["false", "0", "off", "disabled"]);
    const keys = [
      "dbmilesx_sounds_enabled",
      "dbmilesxSoundsEnabled",
      "systemSoundsEnabled",
      "soundsEnabled"
    ];

    for (const key of keys) {
      const value = localStorage.getItem(key);
      if (value !== null && disabled.has(String(value).toLowerCase())) return false;
    }
    return true;
  }

  async function unlockAudio() {
    if (audioUnlocked) return;
    try {
      chatAudio.muted = true;
      await chatAudio.play();
      chatAudio.pause();
      chatAudio.currentTime = 0;
      chatAudio.muted = false;
      audioUnlocked = true;
    } catch (_) {
      // Navegadores móveis podem exigir outra interação do usuário.
    }
  }

  ["pointerdown", "touchstart", "keydown"].forEach((name) => {
    window.addEventListener(name, unlockAudio, { once: true, passive: true });
  });

  async function playChatSound() {
    if (!soundsEnabled()) return;

    const now = Date.now();
    if (now - lastSoundAt < 600) return;
    lastSoundAt = now;

    try {
      chatAudio.pause();
      chatAudio.currentTime = 0;
      chatAudio.muted = false;
      chatAudio.volume = 1.0;
      await chatAudio.play();
    } catch (error) {
      console.debug("DBMILESX: som de chat aguardando interação do usuário.", error);
    }
  }

  function getStoredLastId() {
    const value = Number(localStorage.getItem(lastMessageKey) || 0);
    return Number.isFinite(value) ? value : 0;
  }

  function setStoredLastId(value) {
    const id = Number(value || 0);
    if (!id) return;
    const current = getStoredLastId();
    if (id > current) localStorage.setItem(lastMessageKey, String(id));
  }

  async function pollChatMessages() {
    if (chatPolling) return;
    chatPolling = true;

    try {
      const response = await fetch(`/company/messages?_global_sound=${Date.now()}`, {
        credentials: "same-origin",
        cache: "no-store",
        headers: {
          "Accept": "application/json",
          "X-Requested-With": "XMLHttpRequest"
        }
      });

      if (!response.ok) return;

      const payload = await response.json();
      const messages = Array.isArray(payload) ? payload : (payload.messages || []);
      if (!messages.length) {
        chatInitialized = true;
        return;
      }

      const latestId = messages.reduce((max, item) => {
        const id = Number(item?.id || 0);
        return id > max ? id : max;
      }, 0);

      const storedLastId = getStoredLastId();

      // Primeira leitura: cria uma referência sem tocar som para mensagens antigas.
      if (!chatInitialized && !storedLastId) {
        setStoredLastId(latestId);
        chatInitialized = true;
        return;
      }

      const baseline = storedLastId || latestId;

      const newMessagesFromOthers = messages.filter((item) => {
        const id = Number(item?.id || 0);
        const senderId = Number(item?.user_id || 0);
        return id > baseline && senderId && senderId !== currentUserId;
      });

      setStoredLastId(latestId);
      chatInitialized = true;

      // Dentro do chat, o chat.js já cuida do som.
      // Aqui apenas atualizamos a referência para não tocar de novo ao sair da tela.
      if (chatPage) return;

      if (newMessagesFromOthers.length > 0) {
        await playChatSound();

        window.dispatchEvent(new CustomEvent("dbmilesx:chat-notification", {
          detail: {
            count: newMessagesFromOthers.length,
            latest: newMessagesFromOthers[newMessagesFromOthers.length - 1]
          }
        }));
      }
    } catch (error) {
      console.debug("DBMILESX: falha na verificação global do chat.", error);
    } finally {
      chatPolling = false;
    }
  }

  /*
   * Mantemos o realtime existente para perfil/tarefas quando WebSocket estiver
   * disponível. Na Vercel ele pode falhar; o som do chat NÃO depende dele.
   */
  let socket = null;
  let retryTimer = null;
  let heartbeat = null;
  let retryDelay = 1200;
  const queue = [];

  function emit(name, detail) {
    window.dispatchEvent(new CustomEvent(name, { detail }));
  }

  function buildAvatarNode(current, avatarUrl, userName, userId) {
    const commonClass = current.className || "avatar";
    let node;

    if (avatarUrl) {
      node = document.createElement("img");
      node.className = commonClass.includes("avatar-image")
        ? commonClass
        : `${commonClass} avatar-image`;
      node.src = avatarUrl;
      node.alt = userName || "Usuário";
    } else {
      node = document.createElement("span");
      node.className = commonClass
        .replace(/\bavatar-image\b/g, "")
        .replace(/\s+/g, " ")
        .trim();
      node.textContent = (userName || "?").trim().charAt(0).toUpperCase() || "?";
    }

    node.dataset.userAvatarId = String(userId);
    node.dataset.userName = userName || "";
    return node;
  }

  function updateProfile(payload) {
    const userId = Number(payload?.user_id || 0);
    if (!userId) return;

    const userName = payload.user_name || "Usuário";

    document.querySelectorAll(`[data-user-avatar-id="${userId}"]`).forEach((element) => {
      const replacement = buildAvatarNode(
        element,
        payload.avatar_url || null,
        userName,
        userId
      );
      element.replaceWith(replacement);
    });

    document.querySelectorAll(`[data-user-name-id="${userId}"]`).forEach((element) => {
      element.textContent = userName;
    });
  }

  function receive(payload) {
    if (payload?.type === "profile_updated") updateProfile(payload);

    // Chat não toca som aqui; o polling global é a fonte única do som fora da tela.
    emit("dbmilesx:realtime", payload || {});
  }

  function setStatus(connected) {
    emit("dbmilesx:realtime-status", { connected });
  }

  function flushQueue() {
    while (queue.length && socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(queue.shift()));
    }
  }

  function connect() {
    clearTimeout(retryTimer);

    try {
      const protocol = location.protocol === "https:" ? "wss" : "ws";
      socket = new WebSocket(`${protocol}://${location.host}/company/ws/realtime`);
    } catch (_) {
      return;
    }

    socket.addEventListener("open", () => {
      retryDelay = 1200;
      setStatus(true);
      flushQueue();

      clearInterval(heartbeat);
      heartbeat = setInterval(() => {
        if (socket?.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: "ping" }));
        }
      }, 25000);
    });

    socket.addEventListener("message", (event) => {
      try {
        receive(JSON.parse(event.data));
      } catch (_) {}
    });

    socket.addEventListener("close", () => {
      clearInterval(heartbeat);
      setStatus(false);

      retryTimer = setTimeout(connect, retryDelay);
      retryDelay = Math.min(Math.round(retryDelay * 1.7), 15000);
    });

    socket.addEventListener("error", () => {
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

    testChatSound() {
      unlockAudio().finally(playChatSound);
    }
  };

  // O som global funciona mesmo se /company/ws/realtime falhar.
  pollChatMessages();
  setInterval(pollChatMessages, CHAT_POLL_MS);

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) pollChatMessages();
  });

  window.addEventListener("focus", pollChatMessages);

  connect();
})();
