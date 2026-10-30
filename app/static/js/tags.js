/* Etiquetas reutilizáveis (histórico, voos, pessoas). */
(() => {
  'use strict';
  const dataNode = document.getElementById('dbmTagsData');
  if (!dataNode) return;

  let state = {tags: [], csrf: ''};
  try { state = JSON.parse(dataNode.textContent || '{}'); } catch (_) {}
  let allTags = Array.isArray(state.tags) ? state.tags : [];
  const csrf = state.csrf || document.querySelector('meta[name="csrf-token"]')?.content || '';
  const TARGET_TAG_KIND = {group: 'cotacao', quote: 'cotacao', flight: 'voo', person: 'pessoa', service: 'acompanhamento'};
  const TITLES = {cotacao: 'Etiquetar cotação', voo: 'Etiquetar voo', pessoa: 'Etiquetar pessoa', acompanhamento: 'Etiquetar acompanhamento'};

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
  const showError = (node, message) => { if (node) { node.textContent = message || ''; node.hidden = !message; } };

  // Filtro: clicar numa etiqueta aplica na hora
  document.querySelectorAll('[data-tag-filter-input]').forEach((input) => {
    input.addEventListener('change', () => {
      input.closest('.dbm-tag-chip')?.classList.toggle('is-on', input.checked);
      const form = input.form;
      if (form) (form.requestSubmit ? form.requestSubmit() : form.submit());
    });
  });

  const dialog = document.getElementById('tagEditDialog');
  const options = document.getElementById('tagEditOptions');
  const search = document.getElementById('tagEditSearch');
  const saveButton = document.getElementById('tagEditSave');
  const errorBox = document.getElementById('tagEditError');
  const createButton = document.getElementById('tagCreateButton');
  const newColor = document.getElementById('tagNewColor');
  const title = document.getElementById('tagEditTitle');
  let currentRow = null;
  let currentKind = 'cotacao';
  let selected = new Set();

  const tagsOfKind = () => allTags.filter((t) => (t.kind || 'cotacao') === currentKind && (t.active !== false || selected.has(Number(t.id))));

  function renderOptions() {
    if (!options) return;
    const term = (search?.value || '').trim().toLowerCase();
    const list = tagsOfKind();
    const visible = list.filter((t) => !term || t.name.toLowerCase().includes(term));
    options.innerHTML = visible.length
      ? visible.map((t) => `<label class="dbm-tag-chip ${selected.has(Number(t.id)) ? 'is-on' : ''}" style="--tag:${safeColor(t.color)}"><input type="checkbox" value="${Number(t.id)}" ${selected.has(Number(t.id)) ? 'checked' : ''}><span>${esc(t.name)}</span></label>`).join('')
      : `<small class="history-tag-empty">${list.length ? 'Nenhuma etiqueta com esse nome.' : 'Nenhuma etiqueta deste tipo ainda. Digite acima para criar.'}</small>`;
    options.querySelectorAll('input[type=checkbox]').forEach((box) => {
      box.addEventListener('change', () => {
        const id = Number(box.value);
        if (box.checked) selected.add(id); else selected.delete(id);
        box.closest('.dbm-tag-chip')?.classList.toggle('is-on', box.checked);
      });
    });
    const exact = list.some((t) => t.name.toLowerCase() === term);
    if (createButton) {
      createButton.hidden = false;
      createButton.disabled = exact;
      createButton.textContent = term ? `＋ Criar “${(search?.value || '').trim().slice(0, 40)}”` : '＋ Nova etiqueta';
    }
  }

  function renderRow(row, tags) {
    row.dataset.tags = JSON.stringify(tags);
    row.querySelectorAll('.dbm-tag-chip').forEach((chip) => chip.remove());
    const button = row.querySelector('[data-tag-edit]');
    const base = row.dataset.filterUrl || location.pathname;
    tags.forEach((t) => {
      const chip = document.createElement('a');
      chip.className = 'dbm-tag-chip';
      chip.style.setProperty('--tag', safeColor(t.color));
      chip.href = `${base}?tag=${Number(t.id)}`;
      chip.textContent = t.name;
      row.insertBefore(chip, button);
    });
  }

  function openEditor(row) {
    if (!dialog) return;
    currentRow = row;
    currentKind = TARGET_TAG_KIND[row.dataset.kind] || 'cotacao';
    let tags = [];
    try { tags = JSON.parse(row.dataset.tags || '[]'); } catch (_) {}
    selected = new Set(tags.map((t) => Number(t.id)));
    if (title) title.textContent = TITLES[currentKind] || 'Etiquetar';
    if (search) search.value = '';
    showError(errorBox, '');
    renderOptions();
    dialog.showModal();
    setTimeout(() => search?.focus(), 60);
  }

  async function save(newTagName) {
    if (!currentRow) return;
    saveButton.disabled = true;
    if (createButton) createButton.disabled = true;
    showError(errorBox, '');
    try {
      const data = await post('/tags/assign', {
        kind: currentRow.dataset.kind,
        id: Number(currentRow.dataset.id),
        tag_ids: [...selected],
        new_tag: newTagName || '',
        new_color: newColor?.value || '',
      });
      const others = allTags.filter((t) => (t.kind || 'cotacao') !== currentKind);
      allTags = others.concat(Array.isArray(data.all_tags) ? data.all_tags : []);
      renderRow(currentRow, data.tags || []);
      if (newTagName && data.created) {
        selected = new Set((data.tags || []).map((t) => Number(t.id)));
        if (search) search.value = '';
        renderOptions();
        return;
      }
      dialog.close();
    } catch (error) {
      showError(errorBox, error.message);
    } finally {
      saveButton.disabled = false;
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
    if (event.target.closest('.history-tag-row .dbm-tag-chip')) event.stopPropagation();
  }, true);

  search?.addEventListener('input', renderOptions);
  search?.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter') return;
    event.preventDefault();
    const term = search.value.trim();
    if (!term) return;
    const match = tagsOfKind().find((t) => t.name.toLowerCase() === term.toLowerCase());
    if (match) { selected.add(Number(match.id)); search.value = ''; renderOptions(); } else save(term);
  });
  createButton?.addEventListener('click', () => { const term = (search?.value || '').trim(); if (term) save(term); else {search?.focus(); search?.setAttribute('placeholder','Digite o nome da nova etiqueta e toque em Nova etiqueta');} });
  saveButton?.addEventListener('click', () => save(''));
  document.querySelectorAll('[data-tag-close]').forEach((button) => button.addEventListener('click', () => button.closest('dialog')?.close()));
})();
