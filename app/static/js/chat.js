(() => {
  "use strict";

  const shell = document.querySelector(".chat-shell");
  const list = document.getElementById("chatMessages");
  const form = document.getElementById("chatForm");
  const input = document.getElementById("chatInput");
  const status = document.getElementById("chatStatus");
  const submitButton = form?.querySelector('button[type="submit"]');

  if (!shell || !list || !form || !input) return;

  const userId = Number(shell.dataset.userId || 0);
  const userName = shell.dataset.userName || "Você";
  const POLL_MS = 750;
  const SOUND_URL = "/static/sounds/chat-notification.mp3";

  const notificationSound = new Audio(SOUND_URL);
  notificationSound.preload = "auto";
  notificationSound.volume = 1.0;

  let initialized = false;
  let polling = false;
  let sending = false;

  const knownIds = new Set(
    Array.from(list.querySelectorAll("[data-message-id]"))
      .map(el => String(el.dataset.messageId || ""))
      .filter(Boolean)
  );

  function soundsEnabled() {
    const disabledValues = ["false", "0", "off", "disabled"];
    const keys = [
      "dbmilesx_sounds_enabled",
      "dbmilesxSoundsEnabled",
      "systemSoundsEnabled",
      "soundsEnabled"
    ];
    for (const key of keys) {
      const value = localStorage.getItem(key);
      if (value !== null && disabledValues.includes(String(value).toLowerCase())) return false;
    }
    return true;
  }

  async function unlockAudio() {
    try {
      notificationSound.muted = true;
      await notificationSound.play();
      notificationSound.pause();
      notificationSound.currentTime = 0;
      notificationSound.muted = false;
    } catch (_) {}
  }

  ["pointerdown", "touchstart", "keydown"].forEach(name => {
    document.addEventListener(name, unlockAudio, { once: true, passive: true });
  });

  async function playNotification() {
    if (!soundsEnabled()) return;
    try {
      notificationSound.pause();
      notificationSound.currentTime = 0;
      notificationSound.muted = false;
      notificationSound.volume = 1.0;
      await notificationSound.play();
    } catch (error) {
      console.debug("DBMILESX: som bloqueado até interação do usuário.", error);
    }
  }

  function setStatus(text, ok = true) {
    if (!status) return;
    status.textContent = text;
    status.classList.toggle("online", ok);
    status.classList.toggle("sync-ok", ok);
  }

  function formatDate(value) {
    const date = value ? new Date(value) : new Date();
    if (Number.isNaN(date.getTime())) return "";
    return date.toLocaleString("pt-BR", {
      day: "2-digit",
      month: "2-digit",
      hour: "2-digit",
      minute: "2-digit"
    });
  }

  function scrollBottom(behavior = "auto") {
    list.scrollTo({ top: list.scrollHeight, behavior });
  }

  function buildMessage(item, optimistic = false) {
    const article = document.createElement("article");
    const mine = Number(item.user_id) === userId;

    article.className = `chat-message ${mine ? "mine" : ""}`;
    article.dataset.messageId = String(item.id);
    if (optimistic) article.dataset.optimistic = "1";

    const bubble = document.createElement("div");
    bubble.className = "chat-bubble";

    const strong = document.createElement("strong");
    strong.textContent = item.user_name || (mine ? "Você" : "Usuário");

    const p = document.createElement("p");
    p.textContent = item.message || "";

    const small = document.createElement("small");
    small.textContent = optimistic ? "Enviando..." : formatDate(item.created_at);

    bubble.append(strong, p, small);
    article.appendChild(bubble);
    return article;
  }

  function addServerMessage(item) {
    if (!item || item.id === undefined || item.id === null) return false;
    const id = String(item.id);
    if (knownIds.has(id) || list.querySelector(`[data-message-id="${CSS.escape(id)}"]`)) return false;

    // Confirma uma bolha otimista do próprio usuário com mesmo texto.
    if (Number(item.user_id) === userId) {
      const optimistic = [...list.querySelectorAll('.chat-message.mine[data-optimistic="1"]')]
        .find(el => (el.querySelector(".chat-bubble p")?.textContent || "") === String(item.message || ""));
      if (optimistic) {
        knownIds.delete(String(optimistic.dataset.messageId || ""));
        optimistic.dataset.messageId = id;
        delete optimistic.dataset.optimistic;
        const small = optimistic.querySelector("small");
        if (small) small.textContent = formatDate(item.created_at);
        knownIds.add(id);
        return true;
      }
    }

    const article = buildMessage(item, false);
    list.appendChild(article);
    knownIds.add(id);
    return true;
  }

  function addOptimistic(message) {
    const tempId = `local-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    const item = {
      id: tempId,
      user_id: userId,
      user_name: userName,
      message,
      created_at: new Date().toISOString()
    };
    const article = buildMessage(item, true);
    list.appendChild(article);
    knownIds.add(tempId);
    scrollBottom("smooth");
    return article;
  }

  function markFailed(article, message) {
    article.classList.add("chat-message-error");
    article.dataset.failed = "1";
    const small = article.querySelector("small");
    if (small) small.textContent = "Não enviada — toque para tentar novamente";
    article.addEventListener("click", () => {
      if (sending) return;
      article.remove();
      knownIds.delete(String(article.dataset.messageId || ""));
      input.value = message;
      input.focus();
    }, { once: true });
  }

  async function sendToServer(message) {
    const response = await fetch("/company/messages/send", {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Requested-With": "XMLHttpRequest"
      },
      body: JSON.stringify({ message })
    });

    let payload = null;
    try { payload = await response.json(); } catch (_) {}

    if (!response.ok) {
      throw new Error(payload?.error || `Falha no envio (${response.status})`);
    }
    return payload;
  }

  async function pollMessages() {
    if (polling || document.hidden) return;
    polling = true;

    try {
      const response = await fetch(`/company/messages?_=${Date.now()}`, {
        credentials: "same-origin",
        cache: "no-store",
        headers: {
          "Accept": "application/json",
          "X-Requested-With": "XMLHttpRequest"
        }
      });

      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      const payload = await response.json();
      const messages = Array.isArray(payload) ? payload : (payload.messages || []);

      let receivedOther = false;
      let addedAny = false;

      for (const item of messages) {
        const id = String(item.id);
        const wasKnown = knownIds.has(id);
        const added = addServerMessage(item);
        if (added) addedAny = true;
        if (initialized && !wasKnown && Number(item.user_id) !== userId) {
          receivedOther = true;
        }
      }

      initialized = true;
      setStatus("Sincronização ativa", true);

      if (receivedOther) await playNotification();
      if (addedAny) scrollBottom("smooth");
    } catch (error) {
      setStatus("Reconectando...", false);
      console.debug("DBMILESX chat poll:", error);
    } finally {
      polling = false;
    }
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    event.stopPropagation();
    if (event.stopImmediatePropagation) event.stopImmediatePropagation();

    if (sending) return;

    const message = input.value.trim();
    if (!message) return;

    sending = true;
    if (submitButton) submitButton.disabled = true;

    await unlockAudio();

    input.value = "";
    input.style.height = "48px";
    input.focus();

    const optimistic = addOptimistic(message);

    try {
      const payload = await sendToServer(message);
      const serverMessage = payload?.message;

      if (serverMessage?.id) {
        // Confirma a bolha existente, sem duplicar.
        addServerMessage(serverMessage);
      }

      setStatus("Sincronização ativa", true);
      setTimeout(pollMessages, 60);
    } catch (error) {
      console.error("DBMILESX chat send:", error);
      markFailed(optimistic, message);
      setStatus("Falha ao enviar", false);
    } finally {
      sending = false;
      if (submitButton) submitButton.disabled = false;
    }
  }, true);

  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  input.addEventListener("input", () => {
    input.style.height = "48px";
    input.style.height = `${Math.min(input.scrollHeight, 120)}px`;
  });

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) pollMessages();
  });
  window.addEventListener("focus", pollMessages);

  scrollBottom();
  pollMessages();
  setInterval(pollMessages, POLL_MS);
})();
