/* Página Etiquetas: criar, editar, ativar/desativar e apagar. */
(() => {
  'use strict';
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
  const dialog = document.getElementById('tagFormDialog');
  const form = document.getElementById('tagForm');
  const nameInput = document.getElementById('tagFormName');
  const kindInput = document.getElementById('tagFormKind');
  const colorInput = document.getElementById('tagFormColor');
  const preview = document.getElementById('tagFormPreview');
  const title = document.getElementById('tagFormTitle');
  const formError = document.getElementById('tagFormError');
  const pageError = document.getElementById('tagsPageError');
  const kindWarning = document.getElementById('tagKindWarning');
  let editing = null;

  const showError = (node, message) => { if (node) { node.textContent = message || ''; node.hidden = !message; } };
  async function post(url, body) {
    const res = await fetch(url, {
      method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
      body: JSON.stringify({...body, csrf_token: csrf}),
    });
    let data = {};
    try { data = await res.json(); } catch (_) {}
    if (!res.ok || !data.ok) throw new Error(data.message || 'Não foi possível salvar.');
    return data;
  }
  const rowData = (row) => { try { return JSON.parse(row.dataset.tagRow || '{}'); } catch (_) { return {}; } };

  function syncPreview() {
    preview.textContent = nameInput.value.trim() || 'Etiqueta';
    preview.style.setProperty('--tag', colorInput.value);
    if (kindWarning) kindWarning.hidden = !(editing && editing.kind !== kindInput.value && Number(editing.usage || 0) > 0);
  }

  function open(tag) {
    editing = tag || null;
    title.textContent = tag ? 'Editar etiqueta' : 'Nova etiqueta';
    nameInput.value = tag ? tag.name : '';
    if (tag) kindInput.value = tag.kind || 'cotacao';
    colorInput.value = tag ? tag.color : '#26c5e6';
    showError(formError, '');
    syncPreview();
    dialog.showModal();
    setTimeout(() => nameInput.focus(), 60);
  }

  document.getElementById('tagNewButton')?.addEventListener('click', () => open(null));
  [nameInput, colorInput, kindInput].forEach((el) => el?.addEventListener('input', syncPreview));
  kindInput?.addEventListener('change', syncPreview);
  document.getElementById('tagColorPresets')?.addEventListener('click', (event) => {
    const button = event.target.closest('[data-color]');
    if (!button) return;
    colorInput.value = button.dataset.color;
    syncPreview();
  });
  document.querySelectorAll('[data-tag-form-close]').forEach((b) => b.addEventListener('click', () => dialog.close()));

  form?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const body = {name: nameInput.value.trim(), kind: kindInput.value, color: colorInput.value};
    if (!body.name) { showError(formError, 'Digite o nome da etiqueta.'); return; }
    try {
      if (editing) await post(`/tags/${Number(editing.id)}/update`, body);
      else await post('/tags', body);
      location.reload();
    } catch (error) {
      showError(formError, error.message);
    }
  });

  document.addEventListener('click', async (event) => {
    const row = event.target.closest('[data-tag-row]');
    if (!row) return;
    const tag = rowData(row);
    if (event.target.closest('[data-tag-open-edit]')) { open(tag); return; }
    if (event.target.closest('[data-tag-delete]')) {
      const uses = Number(tag.usage || 0);
      const msg = uses ? `Apagar "${tag.name}"? Ela será removida de ${uses} item(ns).` : `Apagar "${tag.name}"?`;
      if (!window.confirm(msg)) return;
      try { await post(`/tags/${Number(tag.id)}/delete`, {}); row.remove(); } catch (error) { showError(pageError, error.message); }
    }
  });

  document.querySelectorAll('[data-tag-active]').forEach((box) => {
    box.addEventListener('change', async () => {
      const row = box.closest('[data-tag-row]');
      const tag = rowData(row);
      try {
        await post(`/tags/${Number(tag.id)}/update`, {active: box.checked ? '1' : '0'});
        row.classList.toggle('is-inactive', !box.checked);
        showError(pageError, '');
      } catch (error) {
        box.checked = !box.checked;
        showError(pageError, error.message);
      }
    });
  });
})();
