
document.addEventListener('click', async (event) => {
  const button = event.target.closest('.save-option-meta');
  if (!button) return;
  const wrap = button.closest('[data-option-meta]');
  if (!wrap) return;
  const quoteId = button.dataset.quoteId || wrap.dataset.optionMeta;
  const csrf = document.querySelector('input[name="csrf_token"]')?.value || '';
  const tariff = wrap.querySelector('[name="visual_tariff"]')?.value || '';
  const observation = wrap.querySelector('[name="option_observation"]')?.value || '';
  const body = new URLSearchParams();
  body.set('csrf_token', csrf);
  body.set('visual_tariff', tariff);
  body.set('option_observation', observation);
  button.disabled = true;
  const old = button.textContent;
  button.textContent = 'Salvando...';
  try {
    const res = await fetch(`/calculations/${quoteId}/meta/update`, {
      method: 'POST',
      headers: {'Content-Type': 'application/x-www-form-urlencoded', 'X-Requested-With': 'fetch'},
      body
    });
    if (!res.ok) throw new Error('Falha ao salvar');
    const indicator = wrap.querySelector('.save-indicator');
    if (indicator) {
      indicator.classList.add('show');
      setTimeout(() => indicator.classList.remove('show'), 1800);
    }
    button.textContent = 'Salvo';
    setTimeout(() => { button.textContent = old; }, 1200);
  } catch (err) {
    alert('Não consegui salvar a observação. Recarregue a página e tente novamente.');
    button.textContent = old;
  } finally {
    button.disabled = false;
  }
});
