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
  const POLL_MS = 750;
  const SOUND_URL = "/static/sounds/chat-notification.mp3";

  const notificationSound = new Audio(SOUND_URL);
  notificationSound.preload = "auto";
  notificationSound.volume = 1.0;

  let audioUnlocked = false;
  let initialized = false;
  let polling = false;
  let lastActivityAt = Date.now();

  const knownIds = new Set(
    Array.from(list.querySelectorAll("[data-message-id]"))
      .map((el) => String(el.dataset.messageId || ""))
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
      if (value !== null && disabledValues.includes(String(value).toLowerCase())) {
        return false;
      }
    }
    return true;
  }

  async function unlockAudio() {
    if (audioUnlocked) return;
    try {
      const previousVolume = notificationSound.volume;
      notificationSound.volume = 0;
      await notificationSound.play();
      notificationSound.pause();
      notificationSound.currentTime = 0;
      notificationSound.volume = previousVolume;
      audioUnlocked = true;
    } catch (_) {
      // O navegador permitirá depois de outra interação do usuário.
    }
  }

  ["pointerdown", "touchstart", "keydown"].forEach((eventName) => {
    document.addEventListener(eventName, unlockAudio, { once: true, passive: true });
  });

  async function playNotification() {
    if (!soundsEnabled()) return;
    try {
      notificationSound.pause();
      notificationSound.currentTime = 0;
      notificationSound.volume = 1.0;
      await notificationSound.play();
    } catch (error) {
      console.debug("DBMILESX: áudio aguardando interação do usuário.", error);
    }
  }

  function setStatus(text, ok = true) {
    if (!status) return;
    status.textContent = text;
    status.classList.toggle("sync-ok", ok);
    status.classList.toggle("online", ok);
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

  function scrollToBottom(behavior = "auto") {
    list.scrollTo({ top: list.scrollHeight, behavior });
  }

  function makeMessageElement(item, options = {}) {
    const article = document.createElement("article");
    const mine = Number(item.user_id) === userId;

    article.className = `chat-message ${mine ? "mine" : ""}`;
    article.dataset.messageId = String(item.id);
    if (options.optimistic) article.dataset.optimistic = "1";

    const bubble = document.createElement("div");
    bubble.className = "chat-bubble";

    const strong = document.createElement("strong");
    strong.textContent = item.user_name || (mine ? "Você" : "Usuário");

    const p = document.createElement("p");
    p.textContent = item.message || "";

    const small = document.createElement("small");
    small.textContent = formatDate(item.created_at);

    bubble.append(strong, p, small);
    article.appendChild(bubble);
    return article;
  }

  function findOptimisticMatch(item) {
    if (Number(item.user_id) !== userId) return null;
    const candidates = list.querySelectorAll(
      '.chat-message.mine[data-optimistic="1"]'
    );
    for (const candidate of candidates) {
      const text = candidate.querySelector(".chat-bubble p")?.textContent || "";
      if (text === String(item.message || "")) return candidate;
    }
    return null;
  }

  function addMessage(item, options = {}) {
    if (!item || item.id === undefined || item.id === null) return false;

    const id = String(item.id);
    if (knownIds.has(id) || list.querySelector(`[data-message-id="${CSS.escape(id)}"]`)) {
      return false;
    }

    const optimisticMatch = findOptimisticMatch(item);
    if (optimisticMatch) {
      optimisticMatch.dataset.messageId = id;
      delete optimisticMatch.dataset.optimistic;
      knownIds.add(id);
      return true;
    }

    const article = makeMessageElement(item, options);
    list.appendChild(article);
    knownIds.add(id);
    scrollToBottom(options.optimistic ? "smooth" : "auto");
    return true;
  }

  function addOptimisticMessage(message) {
    const tempId = `local-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const item = {
      id: tempId,
      user_id: userId,
      user_name: shell.dataset.userName || "Você",
      message,
      created_at: new Date().toISOString()
    };
    const article = makeMessageElement(item, { optimistic: true });
    list.appendChild(article);
    knownIds.add(tempId);
    scrollToBottom("smooth");
    return article;
  }

  function removeOptimisticFromKnown(article) {
    if (!article) return;
    const id = article.dataset.messageId;
    if (id) knownIds.delete(String(id));
  }

  async function parseResponse(response) {
    const type = response.headers.get("content-type") || "";
    if (!type.includes("application/json")) return null;
    try {
      return await response.json();
    } catch (_) {
      return null;
    }
  }

  async function sendUsingJson(message) {
    const response = await fetch("/company/messages/send", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Requested-With": "XMLHttpRequest"
      },
      body: JSON.stringify({ message })
    });
    return response;
  }

  async function sendUsingForm(message) {
    const data = new FormData();
    data.append("message", message);

    const csrfInput = form.querySelector('input[name="csrf_token"]');
    if (csrfInput?.value) data.append("csrf_token", csrfInput.value);

    return fetch("/company/messages/send", {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-Requested-With": "XMLHttpRequest" },
      body: data
    });
  }

  async function sendMessage(message) {
    let response = await sendUsingJson(message);

    // Compatibilidade caso o backend esteja esperando FormData.
    if ([400, 415, 422].includes(response.status)) {
      response = await sendUsingForm(message);
    }

    if (!response.ok) {
      throw new Error(`Falha ao enviar mensagem (${response.status})`);
    }

    return parseResponse(response);
  }

  async function pollMessages() {
    if (polling || document.hidden) return;
    polling = true;

    try {
      const response = await fetch(`/company/messages?_=${Date.now()}`, {
        method: "GET",
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

      let receivedFromAnotherUser = false;
      let anyAdded = false;

      for (const item of messages) {
        const id = String(item.id);
        const alreadyKnown = knownIds.has(id);
        const added = addMessage(item);

        if (added) anyAdded = true;
        if (
          initialized &&
          !alreadyKnown &&
          Number(item.user_id) !== userId
        ) {
          receivedFromAnotherUser = true;
        }
      }

      if (receivedFromAnotherUser) {
        await playNotification();

        if (document.hidden && "Notification" in window && Notification.permission === "granted") {
          const latest = [...messages].reverse().find((m) => Number(m.user_id) !== userId);
          if (latest) {
            new Notification(latest.user_name || "Nova mensagem", {
              body: String(latest.message || "").slice(0, 160)
            });
          }
        }
      }

      initialized = true;
      setStatus("Sincronização ativa", true);

      if (anyAdded) scrollToBottom("smooth");
    } catch (error) {
      setStatus("Reconectando...", false);
      console.debug("DBMILESX chat sync:", error);
    } finally {
      polling = false;
    }
  }

  // Impede qualquer handler global de submit de mostrar loader antes do chat.
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    event.stopPropagation();
    if (typeof event.stopImmediatePropagation === "function") {
      event.stopImmediatePropagation();
    }

    const message = input.value.trim();
    if (!message) return;

    await unlockAudio();

    input.value = "";
    input.focus();
    input.dispatchEvent(new Event("input", { bubbles: true }));

    const optimistic = addOptimisticMessage(message);

    if (submitButton) submitButton.disabled = true;

    try {
      const payload = await sendMessage(message);
      const serverItem =
        payload?.message && typeof payload.message === "object"
          ? payload.message
          : payload?.id
            ? payload
            : null;

      if (serverItem?.id) {
        removeOptimisticFromKnown(optimistic);
        optimistic.remove();
        addMessage(serverItem);
      }

      lastActivityAt = Date.now();
      setStatus("Sincronização ativa", true);

      // Busca confirmação imediatamente, sem esperar o próximo ciclo.
      setTimeout(pollMessages, 40);
    } catch (error) {
      optimistic.classList.add("chat-message-error");
      const small = optimistic.querySelector("small");
      if (small) small.textContent = "Não enviada — toque e tente novamente";
      input.value = message;
      setStatus("Falha ao enviar", false);
      console.error("DBMILESX chat send:", error);
    } finally {
      if (submitButton) submitButton.disabled = false;
    }
  }, true);

  // Enter envia; Shift+Enter quebra linha.
  input.addEventListener("keydown", (event) => {
    if (
      event.key === "Enter" &&
      !event.shiftKey &&
      !event.isComposing
    ) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  // Auto ajuste simples do textarea.
  input.addEventListener("input", () => {
    input.style.height = "48px";
    input.style.height = `${Math.min(input.scrollHeight, 120)}px`;
  });

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      unlockAudio();
      pollMessages();
    }
  });

  window.addEventListener("focus", pollMessages);

  scrollToBottom();
  pollMessages();
  setInterval(pollMessages, POLL_MS);

  // Libera notificações do navegador apenas se o usuário já tiver concedido.
  // Não solicita permissão automaticamente.
})();
