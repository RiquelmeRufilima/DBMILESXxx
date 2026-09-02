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
