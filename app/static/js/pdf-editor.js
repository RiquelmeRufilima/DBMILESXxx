(() => {
  const preview = document.getElementById('pdfLivePreview');
  if (!preview) return;

  function applyVisibility(name, visible) {
    preview.querySelectorAll(`[data-pdf-visibility="${name}"]`).forEach((element) => {
      element.classList.toggle('pdf-preview-hidden', !visible);
    });
  }

  document.querySelectorAll('[data-preview-toggle]').forEach((toggle) => {
    const name = toggle.dataset.previewToggle;
    applyVisibility(name, toggle.checked);
    toggle.addEventListener('change', () => applyVisibility(name, toggle.checked));
  });
})();
