(() => {
  const selectAll = document.getElementById('selectAllHistory');
  const counter = document.getElementById('historySelectedCount');
  const selectors = () => [...document.querySelectorAll('[data-history-check]')];

  function refresh() {
    const all = selectors();
    const selected = all.filter((item) => item.checked);
    if (counter) counter.textContent = `${selected.length} selecionada${selected.length === 1 ? '' : 's'}`;
    all.forEach((selector) => {
      const card = selector.closest('.history-group-card');
      if (card) card.classList.toggle('is-selected', selector.checked);
    });
    if (selectAll) {
      selectAll.checked = !!all.length && selected.length === all.length;
      selectAll.indeterminate = selected.length > 0 && selected.length < all.length;
    }
  }

  document.addEventListener('change', event => { if (event.target.matches('[data-history-check]')) refresh(); });
  selectAll?.addEventListener('change', () => {
    selectors().forEach((selector) => { selector.checked = selectAll.checked; });
    refresh();
  });
  refresh();
})();
