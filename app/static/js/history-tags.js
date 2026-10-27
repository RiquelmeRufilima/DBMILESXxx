(() => {
  'use strict';
  const dataNode = document.getElementById('historyTagsData');
  if (!dataNode) return;

  let state = {tags: [], csrf: ''};
  try { state = JSON.parse(dataNode.textContent || '{}'); } catch (_) {}
  let allTags = Array.isArray(state.tags) ? state.tags : [];
  const csrf = state.csrf || '';

  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'}[c]));
  const safeColor = (v) => (/^#[0-9a-fA-F]{6}$/.test(String(v || '')) ? v : '#26c5e6');

  async function post(url, body) {
    const res = await fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
      body: JSON.stringify({...body, csrf_token: csrf}),
    });
    let data = {};
    try { data = await res.json(); } catch (_) {}
    if (!res.ok || !data.ok) throw new Error(data.message || 'Não foi possível salvar. Tente novamente.');
    return data;
  }

  function showError(node, message) {
    if (!node) return;
    node.textContent = message || '';
    node.hidden = !message;
  }

  // ---------------------------------------------------------------
  // Filtro: clicar numa etiqueta aplica o filtro na hora
  // ---------------------------------------------------------------
  document.querySelectorAll('[data-tag-filter-input]').forEach((input) => {
    input.addEventListener('change', () => {
      input.closest('.dbm-tag-chip')?.classList.toggle('is-on', input.checked);
      const form = input.form;
      if (!form) return;
      const page = form.querySelector('input[name="page"]');
      if (page) page.value = '1';
      form.requestSubmit ? form.requestSubmit() : form.submit();
    });
  });

  // ---------------------------------------------------------------
  // Etiquetar uma cotação
  // ---------------------------------------------------------------
  const editDialog = document.getElementById('tagEditDialog');
  const editOptions = document.getElementById('tagEditOptions');
  const editSearch = document.getElementById('tagEditSearch');
  const editSave = document.getElementById('tagEditSave');
  const editError = document.getElementById('tagEditError');
  const createButton = document.getElementById('tagCreateButton');
  const newColor = document.getElementById('tagNewColor');
  let currentRow = null;
  let selected = new Set();

  function renderOptions() {
    if (!editOptions) return;
    const term = (editSearch?.value || '').trim().toLowerCase();
    const visible = allTags.filter((t) => !term || t.name.toLowerCase().includes(term));
    editOptions.innerHTML = visible.length
      ? visible.map((t) => `<label class="dbm-tag-chip ${selected.has(t.id) ? 'is-on' : ''}" style="--tag:${safeColor(t.color)}"><input type="checkbox" value="${Number(t.id)}" ${selected.has(t.id) ? 'checked' : ''}><span>${esc(t.name)}</span></label>`).join('')
      : `<small class="history-tag-empty">${allTags.length ? 'Nenhuma etiqueta com esse nome.' : 'Nenhuma etiqueta ainda. Digite acima para criar.'}</small>`;
    editOptions.querySelectorAll('input[type=checkbox]').forEach((box) => {
      box.addEventListener('change', () => {
        const id = Number(box.value);
        if (box.checked) selected.add(id); else selected.delete(id);
        box.closest('.dbm-tag-chip')?.classList.toggle('is-on', box.checked);
      });
    });
    const exact = allTags.some((t) => t.name.toLowerCase() === term);
    if (createButton) {
      createButton.hidden = !term || exact;
      createButton.textContent = `＋ Criar “${(editSearch?.value || '').trim().slice(0, 40)}”`;
    }
  }

  function renderRow(row, tags) {
    row.dataset.tags = JSON.stringify(tags);
    row.querySelectorAll('.dbm-tag-chip').forEach((chip) => chip.remove());
    const button = row.querySelector('[data-tag-edit]');
    tags.forEach((t) => {
      const chip = document.createElement('a');
      chip.className = 'dbm-tag-chip';
      chip.style.setProperty('--tag', safeColor(t.color));
      chip.href = `/calculations/history?tag=${Number(t.id)}`;
      chip.textContent = t.name;
      row.insertBefore(chip, button);
    });
  }

  function openEditor(row) {
    if (!editDialog) return;
    currentRow = row;
    let tags = [];
    try { tags = JSON.parse(row.dataset.tags || '[]'); } catch (_) {}
    selected = new Set(tags.map((t) => Number(t.id)));
    if (editSearch) editSearch.value = '';
    showError(editError, '');
    renderOptions();
    editDialog.showModal();
    setTimeout(() => editSearch?.focus(), 60);
  }

  async function saveTags(newTagName) {
    if (!currentRow) return;
    editSave.disabled = true;
    if (createButton) createButton.disabled = true;
    showError(editError, '');
    try {
      const data = await post('/tags/assign', {
        kind: currentRow.dataset.kind,
        id: Number(currentRow.dataset.id),
        tag_ids: [...selected],
        new_tag: newTagName || '',
        new_color: newColor?.value || '',
      });
      allTags = Array.isArray(data.all_tags) ? data.all_tags : allTags;
      renderRow(currentRow, data.tags || []);
      if (newTagName && data.created) {
        // Criou uma nova: continua com o editor aberto para marcar outras.
        selected = new Set((data.tags || []).map((t) => Number(t.id)));
        if (editSearch) editSearch.value = '';
        renderOptions();
        return;
      }
      editDialog.close();
    } catch (error) {
      showError(editError, error.message);
    } finally {
      editSave.disabled = false;
      if (createButton) createButton.disabled = false;
    }
  }

  document.addEventListener('click', (event) => {
    const editButton = event.target.closest('[data-tag-edit]');
    if (editButton) {
      event.preventDefault();
      event.stopPropagation();
      const row = editButton.closest('[data-tag-target]');
      if (row) openEditor(row);
      return;
    }
    // Clicar numa etiqueta do card não deve abrir/fechar o card.
    if (event.target.closest('.history-tag-row .dbm-tag-chip')) event.stopPropagation();
  }, true);

  editSearch?.addEventListener('input', renderOptions);
  editSearch?.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter') return;
    event.preventDefault();
    const term = editSearch.value.trim();
    if (!term) return;
    const match = allTags.find((t) => t.name.toLowerCase() === term.toLowerCase());
    if (match) { selected.add(Number(match.id)); editSearch.value = ''; renderOptions(); }
    else saveTags(term);
  });
  createButton?.addEventListener('click', () => {
    const term = (editSearch?.value || '').trim();
    if (term) saveTags(term);
  });
  editSave?.addEventListener('click', () => saveTags(''));

  // ---------------------------------------------------------------
  // Gerenciar etiquetas (renomear, cor, apagar)
  // ---------------------------------------------------------------
  const manageDialog = document.getElementById('tagManageDialog');
  const manageList = document.getElementById('tagManageList');
  const manageError = document.getElementById('tagManageError');
  let changedInManager = false;

  function renderManager() {
    if (!manageList) return;
    if (!allTags.length) {
      manageList.innerHTML = '<small class="history-tag-empty">Nenhuma etiqueta criada ainda.</small>';
      return;
    }
    manageList.innerHTML = allTags.map((t) => `
      <div class="dbm-tag-manage-row" data-tag-id="${Number(t.id)}">
        <input type="color" value="${safeColor(t.color)}" aria-label="Cor">
        <input type="text" value="${esc(t.name)}" maxlength="40" aria-label="Nome">
        <small>${Number(t.usage || 0)} uso(s)</small>
        <button type="button" class="ghost-button small-button danger" data-tag-delete data-confirm-ignore="1">Apagar</button>
      </div>`).join('');
  }

  async function updateTag(row) {
    const id = Number(row.dataset.tagId);
    const name = row.querySelector('input[type=text]').value.trim();
    const color = row.querySelector('input[type=color]').value;
    showError(manageError, '');
    try {
      const data = await post(`/tags/${id}/update`, {name, color});
      allTags = allTags.map((t) => (t.id === id ? {...t, ...data.tag} : t));
      changedInManager = true;
    } catch (error) {
      showError(manageError, error.message);
    }
  }

  manageList?.addEventListener('change', (event) => {
    const row = event.target.closest('.dbm-tag-manage-row');
    if (row) updateTag(row);
  });
  manageList?.addEventListener('click', async (event) => {
    const button = event.target.closest('[data-tag-delete]');
    if (!button) return;
    const row = button.closest('.dbm-tag-manage-row');
    const id = Number(row.dataset.tagId);
    const tag = allTags.find((t) => t.id === id);
    if (!window.confirm(`Apagar a etiqueta "${tag ? tag.name : ''}"? Ela será removida de todas as cotações.`)) return;
    try {
      await post(`/tags/${id}/delete`, {});
      allTags = allTags.filter((t) => t.id !== id);
      changedInManager = true;
      renderManager();
    } catch (error) {
      showError(manageError, error.message);
    }
  });

  document.getElementById('manageTagsButton')?.addEventListener('click', async () => {
    try {
      const res = await fetch('/tags', {credentials: 'same-origin', cache: 'no-store'});
      const data = await res.json();
      if (data.ok) allTags = data.tags || allTags;
    } catch (_) {}
    changedInManager = false;
    showError(manageError, '');
    renderManager();
    manageDialog?.showModal();
  });

  document.querySelectorAll('[data-tag-close]').forEach((button) => {
    button.addEventListener('click', () => {
      const dialog = button.closest('dialog');
      dialog?.close();
      if (button.hasAttribute('data-tag-reload') && changedInManager) window.location.reload();
    });
  });
  manageDialog?.addEventListener('close', () => { if (changedInManager) window.location.reload(); });
})();
