(() => {
  const root = document.documentElement;
  const mode = root.dataset.themeMode || root.dataset.theme || 'dark';
  const media = window.matchMedia?.('(prefers-color-scheme: light)');
  const applySystemTheme = () => {
    if (mode === 'system') root.dataset.theme = media?.matches ? 'light' : 'dark';
  };
  applySystemTheme();
  media?.addEventListener?.('change', applySystemTheme);

  const sidebar = document.getElementById('sidebar');
  document.getElementById('menuButton')?.addEventListener('click', () => sidebar?.classList.toggle('open'));
  document.addEventListener('click', (event) => {
    if (!sidebar || window.innerWidth > 920) return;
    const target = event.target;
    if (sidebar.classList.contains('open') && !sidebar.contains(target) && !target?.closest?.('#menuButton')) sidebar.classList.remove('open');
  });

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => navigator.serviceWorker.register('/static/sw.js?v=5.10.33').then(reg=>reg.update()).catch(() => {}));
  }

  let deferredPrompt;
  const installButton = document.getElementById('installPwa');
  window.addEventListener('beforeinstallprompt', (event) => {
    event.preventDefault();
    deferredPrompt = event;
    if (installButton) installButton.hidden = false;
  });
  installButton?.addEventListener('click', async () => {
    if (!deferredPrompt) return;
    deferredPrompt.prompt();
    await deferredPrompt.userChoice;
    deferredPrompt = null;
    installButton.hidden = true;
  });

  setTimeout(() => document.querySelectorAll('.flash').forEach((item) => item.remove()), 6500);
})();


(() => {
  const loader = document.getElementById('globalLoader');
  const loaderText = document.getElementById('globalLoaderText');
  if (!loader) return;
  let timer = null;
  const show = (message) => {
    if (loaderText && message) loaderText.textContent = message;
    clearTimeout(timer);
    timer = setTimeout(() => { loader.classList.add('is-visible'); loader.setAttribute('aria-hidden','false'); }, 100);
  };
  const hide = () => { clearTimeout(timer); loader.classList.remove('is-visible'); loader.setAttribute('aria-hidden','true'); };
  window.dbmShowLoader = show; window.dbmHideLoader = hide;
  window.addEventListener('load', hide);
  window.addEventListener('pageshow', hide);
  document.addEventListener('submit', (ev) => {
    const form = ev.target;
    if (!(form instanceof HTMLFormElement) || form.dataset.noLoader === '1') return;
    show(form.dataset.loaderMessage || 'Salvando informações...');
  }, true);
  document.addEventListener('click', (ev) => {
    const a = ev.target.closest?.('a'); if (!a) return;
    const href=(a.getAttribute('href')||'').trim();
    if (!href || href.startsWith('#') || href.startsWith('javascript:') || href.startsWith('mailto:') || href.startsWith('tel:') || a.target==='_blank' || a.hasAttribute('download') || a.dataset.noLoader==='1') return;
    show(a.dataset.loaderMessage || 'Abrindo página...');
  }, true);
})();

/* V5.12.10 - alternância rápida claro/escuro */
(() => {
  const root = document.documentElement;
  const button = document.getElementById('themeQuickToggle');
  if (!button) return;

  const STORAGE_KEY = 'dbmilesx-theme-quick';
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved === 'light' || saved === 'dark') root.dataset.theme = saved;

  const sync = () => {
    const current = root.dataset.theme === 'light' ? 'light' : 'dark';
    button.setAttribute('aria-pressed', current === 'light' ? 'true' : 'false');
    button.title = current === 'light' ? 'Ativar modo escuro' : 'Ativar modo claro';
  };

  button.addEventListener('click', () => {
    const next = root.dataset.theme === 'light' ? 'dark' : 'light';
    root.dataset.theme = next;
    localStorage.setItem(STORAGE_KEY, next);
    sync();
  });
  sync();
})();
