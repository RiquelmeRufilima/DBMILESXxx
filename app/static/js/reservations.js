/* Página Reservas: "Adicionar reserva" pelo localizador + ações da lista. */
(() => {
  'use strict';
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
  let catalog = [];
  try { catalog = JSON.parse(document.getElementById('rsvCatalog')?.textContent || '[]'); } catch (_) {}
  const bySlug = Object.fromEntries(catalog.map((a) => [a.slug, a]));
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'}[c]));
  const showError = (node, msg) => { if (node) { node.textContent = msg || ''; node.hidden = !msg; } };

  async function post(url, body) {
    const res = await fetch(url, {
      method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
      body: JSON.stringify({...body, csrf_token: csrf}),
    });
    let data = {};
    try { data = await res.json(); } catch (_) {}
    if (!res.ok || !data.ok) throw new Error(data.message || 'Não foi possível concluir. Tente novamente.');
    return data;
  }

  // ---------------- Adicionar reserva ----------------
  const dialog = document.getElementById('rsvDialog');
  const step1 = dialog?.querySelector('[data-rsv-step="1"]');
  const form = document.getElementById('rsvForm');
  const fieldsBox = document.getElementById('rsvFields');
  const submit = document.getElementById('rsvSubmit');
  const errorBox = document.getElementById('rsvError');
  const search = document.getElementById('rsvAirlineSearch');
  let selected = null;

  function goStep(n) {
    if (step1) step1.hidden = n !== 1;
    if (form) form.hidden = n !== 2;
  }

  function validate() {
    if (!selected || !fieldsBox) { submit.disabled = true; return; }
    submit.disabled = [...fieldsBox.querySelectorAll('input[required]')].some((i) => !i.value.trim());
  }

  function pick(slug) {
    selected = bySlug[slug];
    if (!selected) return;
    const logo = document.getElementById('rsvSelectedLogo');
    if (logo) logo.innerHTML = selected.logo_url ? `<img src="${esc(selected.logo_url)}" alt="">` : `<i>${esc(selected.name.slice(0, 2).toUpperCase())}</i>`;
    document.getElementById('rsvSelectedName').textContent = selected.name;
    fieldsBox.innerHTML = selected.fields.map((f) => `
      <label class="rsv-field"><span>${esc(f.label)}</span>
        <span class="rsv-input-wrap"><input name="${esc(f.key)}" placeholder="${esc(f.placeholder)}" required autocomplete="off" spellcheck="false" ${f.key === 'origin' ? 'maxlength="3"' : ''}>
        ${f.key === 'locator' || f.key === 'purchase_number' ? '<button type="button" class="rsv-paste" data-rsv-paste data-confirm-ignore="1">Colar</button>' : ''}</span>
      </label>`).join('');
    showError(errorBox, '');
    goStep(2);
    validate();
    setTimeout(() => fieldsBox.querySelector('input')?.focus(), 50);
  }

  document.getElementById('rsvAddButton')?.addEventListener('click', () => {
    selected = null;
    form?.reset();
    if (search) search.value = '';
    dialog.querySelectorAll('.rsv-airline').forEach((b) => { b.hidden = false; });
    goStep(1);
    dialog.showModal();
  });
  dialog?.querySelectorAll('.rsv-airline').forEach((b) => b.addEventListener('click', () => pick(b.dataset.slug)));
  dialog?.querySelectorAll('[data-rsv-back]').forEach((b) => b.addEventListener('click', () => { selected = null; goStep(1); }));
  dialog?.querySelectorAll('[data-rsv-close]').forEach((b) => b.addEventListener('click', () => dialog.close()));
  search?.addEventListener('input', () => {
    const term = search.value.trim().toLowerCase();
    dialog.querySelectorAll('.rsv-airline').forEach((b) => { b.hidden = !!term && !b.dataset.name.includes(term); });
  });
  fieldsBox?.addEventListener('input', validate);
  fieldsBox?.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-rsv-paste]');
    if (!btn) return;
    try {
      const text = (await navigator.clipboard.readText()).trim();
      const input = btn.parentElement.querySelector('input');
      input.value = text.replace(/\s+/g, '').toUpperCase();
      validate();
    } catch (_) { /* navegador bloqueou a área de transferência */ }
  });

  form?.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!selected) return;
    const data = Object.fromEntries(new FormData(form).entries());
    data.airline = selected.slug;
    data.notify = form.querySelector('[name=notify]')?.checked ? '1' : '0';
    submit.disabled = true;
    const label = submit.textContent;
    submit.textContent = 'Adicionando...';
    showError(errorBox, '');
    try {
      await post('/reservas', data);
      location.reload();
    } catch (error) {
      showError(errorBox, error.message);
      submit.disabled = false;
    } finally {
      submit.textContent = label;
    }
  });

  // ---------------- Ações da lista ----------------
  const pageError = document.getElementById('rsvPageError');
  document.addEventListener('click', async (e) => {
    const row = e.target.closest('[data-rsv-id]');
    const copy = e.target.closest('[data-rsv-copy]');
    if (copy) {
      try { await navigator.clipboard.writeText(copy.dataset.rsvCopy); copy.classList.add('is-done'); setTimeout(() => copy.classList.remove('is-done'), 1200); } catch (_) {}
      return;
    }
    if (!row) return;
    const id = Number(row.dataset.rsvId);
    if (e.target.closest('[data-rsv-sync]')) {
      const btn = e.target.closest('[data-rsv-sync]');
      btn.classList.add('is-spinning');
      try { const d = await post(`/reservas/${id}/sincronizar`, {}); if (d.status === 'sincronizada') location.reload(); else showError(pageError, d.message || ''); }
      catch (error) { showError(pageError, error.message); }
      finally { btn.classList.remove('is-spinning'); }
      return;
    }
    if (e.target.closest('[data-rsv-delete]')) {
      const code = row.querySelector('.rsv-code strong')?.textContent?.trim() || 'esta reserva';
      if (!window.confirm(`Excluir ${code}?`)) return;
      try { await post(`/reservas/${id}/excluir`, {}); row.remove(); } catch (error) { showError(pageError, error.message); }
    }
  });
  document.querySelectorAll('[data-rsv-desc]').forEach((input) => {
    input.addEventListener('change', async () => {
      const row = input.closest('[data-rsv-id]');
      try { await post(`/reservas/${Number(row.dataset.rsvId)}/atualizar`, {description: input.value}); input.classList.add('is-saved'); setTimeout(() => input.classList.remove('is-saved'), 1000); }
      catch (error) { showError(pageError, error.message); }
    });
  });
})();
