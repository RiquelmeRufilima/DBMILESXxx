(() => {
  'use strict';

  const POLL_MS = 2500;
  const SYNC_URL = '/sync/version';
  const IGNORE_PATHS = ['/company/chat'];
  const body = document.body;
  if (!body) return;

  let baseline = null;
  let dirty = false;
  let pendingReload = false;
  let reloading = false;

  const path = window.location.pathname;
  if (IGNORE_PATHS.some(prefix => path.startsWith(prefix))) return;

  function isEditableTarget(target) {
    return target instanceof HTMLInputElement ||
      target instanceof HTMLTextAreaElement ||
      target instanceof HTMLSelectElement ||
      target?.isContentEditable;
  }

  document.addEventListener('input', event => {
    if (isEditableTarget(event.target)) dirty = true;
  }, true);

  document.addEventListener('change', event => {
    if (isEditableTarget(event.target)) dirty = true;
  }, true);

  document.addEventListener('submit', () => {
    // O servidor vai salvar e a próxima página já abrirá com os dados atuais.
    dirty = false;
  }, true);

  function canReloadNow() {
    if (dirty) return false;
    const active = document.activeElement;
    if (active && isEditableTarget(active)) return false;
    return document.visibilityState === 'visible';
  }

  function rememberScroll() {
    try {
      sessionStorage.setItem(`dbmilesx-scroll:${path}`, String(window.scrollY || 0));
    } catch (_) {}
  }

  function restoreScroll() {
    try {
      const key = `dbmilesx-scroll:${path}`;
      const value = sessionStorage.getItem(key);
      if (value !== null) {
        sessionStorage.removeItem(key);
        const y = Number(value);
        if (Number.isFinite(y)) requestAnimationFrame(() => window.scrollTo(0, y));
      }
    } catch (_) {}
  }

  function reloadPage() {
    if (reloading || !canReloadNow()) {
      pendingReload = true;
      return;
    }
    reloading = true;
    rememberScroll();
    window.dispatchEvent(new CustomEvent('dbmilesx:auto-refresh', {
      detail: { reason: 'server-data-changed' }
    }));
    window.location.reload();
  }

  async function checkVersion() {
    try {
      const response = await fetch(SYNC_URL, {
        method: 'GET',
        credentials: 'same-origin',
        cache: 'no-store',
        headers: { 'Cache-Control': 'no-cache' }
      });
      if (!response.ok) return;
      const data = await response.json();
      const version = Number(data.version || 0);
      if (!version) return;

      if (baseline === null) {
        baseline = version;
        return;
      }

      if (version !== baseline) {
        baseline = version;
        pendingReload = true;
        reloadPage();
      }
    } catch (_) {
      // Se a rede oscilar, apenas tenta de novo no próximo ciclo.
    }
  }

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
      if (pendingReload && canReloadNow()) reloadPage();
      else checkVersion();
    }
  });

  window.addEventListener('focus', () => {
    if (pendingReload && canReloadNow()) reloadPage();
    else checkVersion();
  });

  restoreScroll();
  checkVersion();
  setInterval(checkVersion, POLL_MS);
})();
