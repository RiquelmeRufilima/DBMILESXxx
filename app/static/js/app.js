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
  const menuButton = document.getElementById('menuButton');
  const sidebarBackdrop = document.getElementById('sidebarBackdrop');

  const setSidebarOpen = (open) => {
    if (!sidebar) return;
    sidebar.classList.toggle('open', !!open);
    document.body.classList.toggle('mobile-menu-open', !!open);
    menuButton?.setAttribute('aria-expanded', open ? 'true' : 'false');
  };

  menuButton?.setAttribute('aria-expanded', 'false');
  menuButton?.addEventListener('click', () => setSidebarOpen(!sidebar?.classList.contains('open')));
  sidebarBackdrop?.addEventListener('click', () => setSidebarOpen(false));

  document.addEventListener('click', (event) => {
    if (!sidebar || window.innerWidth > 920) return;
    const target = event.target;
    if (sidebar.classList.contains('open') && !sidebar.contains(target) && !target?.closest?.('#menuButton')) {
      setSidebarOpen(false);
    }
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') setSidebarOpen(false);
  });

  sidebar?.querySelectorAll('a, form button[type="submit"]').forEach((item) => {
    item.addEventListener('click', () => {
      if (window.innerWidth <= 920) setSidebarOpen(false);
    });
  });

  const themeQuickToggle = document.getElementById('themeQuickToggle');
  const themeStorageKey = 'dbmilesx-quick-theme';

  const syncThemeButton = () => {
    if (!themeQuickToggle) return;
    const light = root.dataset.theme === 'light';
    themeQuickToggle.classList.toggle('is-light', light);
    themeQuickToggle.setAttribute('aria-label', light ? 'Ativar tema escuro' : 'Ativar tema claro');
    themeQuickToggle.setAttribute('title', light ? 'Tema escuro' : 'Tema claro');
  };

  const quickTheme = localStorage.getItem(themeStorageKey);
  if (quickTheme === 'light' || quickTheme === 'dark') {
    root.dataset.theme = quickTheme;
  }
  syncThemeButton();

  themeQuickToggle?.addEventListener('click', () => {
    const next = root.dataset.theme === 'light' ? 'dark' : 'light';
    root.dataset.theme = next;
    root.dataset.themeMode = next;
    localStorage.setItem(themeStorageKey, next);
    syncThemeButton();
  });

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => navigator.serviceWorker.register('/static/sw.js').catch(() => {}));
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
