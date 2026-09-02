(() => {
  const initPair = (topBar) => {
    const block = topBar.closest('.history-scope-block');
    if (!block) return;
    const strip = block.querySelector('[data-history-scroll-strip]');
    const inner = topBar.querySelector('.history-scrollbar-top-inner');
    if (!strip || !inner) return;

    let syncing = false;
    const update = () => {
      const fullWidth = Math.max(strip.scrollWidth, strip.clientWidth);
      inner.style.width = `${fullWidth}px`;
      const active = strip.scrollWidth > strip.clientWidth + 2;
      topBar.classList.toggle('is-active', active);
      if (!active) {
        topBar.scrollLeft = 0;
        strip.scrollLeft = 0;
      }
    };

    topBar.addEventListener('scroll', () => {
      if (syncing) return;
      syncing = true;
      strip.scrollLeft = topBar.scrollLeft;
      requestAnimationFrame(() => { syncing = false; });
    }, { passive: true });

    strip.addEventListener('scroll', () => {
      if (syncing) return;
      syncing = true;
      topBar.scrollLeft = strip.scrollLeft;
      requestAnimationFrame(() => { syncing = false; });
    }, { passive: true });

    update();
    if ('ResizeObserver' in window) {
      const observer = new ResizeObserver(update);
      observer.observe(strip);
      Array.from(strip.children).forEach((child) => observer.observe(child));
    } else {
      window.addEventListener('resize', update, { passive: true });
    }
    window.addEventListener('load', update, { once: true });
  };

  const boot = () => document.querySelectorAll('[data-history-scroll-top]').forEach(initPair);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true });
  else boot();
})();
