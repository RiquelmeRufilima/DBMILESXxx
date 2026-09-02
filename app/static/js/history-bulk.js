(() => {
  const selectors = [...document.querySelectorAll('[data-history-check]')];
  const selectAll = document.getElementById('selectAllHistory');
  const counter = document.getElementById('historySelectedCount');
  if (!selectors.length) return;

  function refresh() {
    const selected = selectors.filter((item) => item.checked);
    if (counter) counter.textContent = `${selected.length} selecionada${selected.length === 1 ? '' : 's'}`;
    selectors.forEach((selector) => {
      const card = selector.closest('.history-group-card');
      if (card) card.classList.toggle('is-selected', selector.checked);
    });
    if (selectAll) {
      selectAll.checked = selected.length === selectors.length;
      selectAll.indeterminate = selected.length > 0 && selected.length < selectors.length;
    }
  }

  selectors.forEach((selector) => selector.addEventListener('change', refresh));
  selectAll?.addEventListener('change', () => {
    selectors.forEach((selector) => { selector.checked = selectAll.checked; });
    refresh();
  });
  refresh();
})();
