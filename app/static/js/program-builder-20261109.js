/* Tela "Novo cadastro" (programas, companhias, sistemas, consolidadoras). */
(() => {
  const form = document.getElementById('programBuilderForm');
  if (!form) return;
  const $ = (id) => document.getElementById(id);
  const models = JSON.parse($('pbModels').textContent || '{}');
  const fieldsBox = $('pbFields');
  const formulaInput = $('pbFormula');
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const slugKey = (t) => String(t || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').replace(/^([0-9])/, '_$1');
  const brl = new Intl.NumberFormat('pt-BR', {style: 'currency', currency: 'BRL'});
  const kindLabels = {};
  form.querySelectorAll('input[name="catalog_kind"]').forEach((el) => { kindLabels[el.value] = el.closest('label').querySelector('strong').textContent; });
  const presets = {
    fee: {label: 'Taxa adicional (R$)', key: 'taxa_adicional', field_type: 'number', default_value: '0'},
    discount: {label: 'Desconto (%)', key: 'desconto', field_type: 'percent', default_value: '0'},
  };

  let customized = false;
  let testValues = {};
  let lastPreview = {ok: true};

  const kind = () => form.querySelector('input[name="catalog_kind"]:checked')?.value || 'miles';
  const modelFor = (k) => (k === 'miles' ? models.miles : models.tariff);

  function readFields() {
    return [...fieldsBox.querySelectorAll('.pb-field')].map((row) => ({
      label: row.querySelector('[data-f="label"]').value.trim(),
      key: row.querySelector('[data-f="key"]').value.trim(),
      field_type: row.querySelector('[data-f="field_type"]').value,
      default_value: row.querySelector('[data-f="default_value"]').value || '0',
      required: row.dataset.required === '1',
      min_value: row.dataset.min ?? '',
      max_value: row.dataset.max ?? '',
      step: row.dataset.step ?? '',
      help_text: row.dataset.help || '',
      options: null,
    })).filter((f) => f.label && f.key);
  }

  function addFieldRow(data = {}) {
    const row = document.createElement('div');
    row.className = 'pb-field';
    row.dataset.required = data.required ? '1' : '0';
    row.dataset.min = data.min_value ?? '';
    row.dataset.max = data.max_value ?? '';
    row.dataset.step = data.step ?? '';
    row.dataset.help = data.help_text || '';
    const uid = Math.random().toString(36).slice(2, 8);
    row.innerHTML = `
      <label for="l${uid}">Nome<input id="l${uid}" data-f="label" value="${esc(data.label)}" placeholder="Ex.: Milhas"></label>
      <label for="k${uid}">Chave na fórmula<input id="k${uid}" data-f="key" value="${esc(data.key)}" placeholder="milhas" spellcheck="false"></label>
      <label for="t${uid}">Tipo<select id="t${uid}" data-f="field_type"><option value="number">Número</option><option value="integer">Inteiro</option><option value="percent">Percentual</option></select></label>
      <label for="d${uid}">Padrão<input id="d${uid}" data-f="default_value" value="${esc(data.default_value ?? '0')}" inputmode="decimal"></label>
      <button type="button" class="pb-remove" aria-label="Remover campo ${esc(data.label || '')}">×</button>`;
    row.querySelector('[data-f="field_type"]').value = ['number', 'integer', 'percent'].includes(data.field_type) ? data.field_type : 'number';
    const label = row.querySelector('[data-f="label"]');
    const key = row.querySelector('[data-f="key"]');
    let keyTouched = Boolean(data.key);
    key.addEventListener('input', () => { keyTouched = true; });
    label.addEventListener('input', () => { if (!keyTouched) key.value = slugKey(label.value); });
    row.addEventListener('input', () => { customized = true; refresh(); });
    row.addEventListener('change', () => { customized = true; refresh(); });
    row.querySelector('.pb-remove').addEventListener('click', () => { row.remove(); customized = true; refresh(); });
    fieldsBox.append(row);
  }

  function applyModel(k) {
    const model = modelFor(k);
    fieldsBox.innerHTML = '';
    model.fields.forEach(addFieldRow);
    formulaInput.value = model.formula;
    const calcName = $('pbCalcName');
    const desc = $('pbDesc');
    calcName.value = model.calculation_name;
    desc.value = model.description;
    customized = false;
    testValues = {};
  }

  function renderTest(fields) {
    const box = $('pbTest');
    const focused = document.activeElement?.dataset?.testKey;
    box.innerHTML = fields.map((f) => `
      <label>${esc(f.label)}<input type="text" inputmode="decimal" data-test-key="${esc(f.key)}" value="${esc(testValues[f.key] ?? exampleValue(f))}"></label>`).join('');
    box.querySelectorAll('input').forEach((input) => {
      input.addEventListener('input', () => { testValues[input.dataset.testKey] = input.value; schedulePreview(); });
      if (input.dataset.testKey === focused) input.focus();
    });
  }

  function exampleValue(f) {
    const examples = {milhas: '50000', milheiro: '17,50', taxa: '120', tarifa: '1500', desconto_percentual: '10'};
    if (examples[f.key] !== undefined) return examples[f.key];
    return f.default_value || '0';
  }

  function renderFormulaView(fields) {
    const view = $('pbFormulaView');
    let text = formulaInput.value.trim() || modelFor(kind()).formula;
    const byKey = Object.fromEntries(fields.map((f) => [f.key, f.label]));
    const parts = text.split(/([A-Za-z_][A-Za-z0-9_]*)/g).map((part) => (byKey[part] ? `<b title="${esc(part)}">${esc(byKey[part])}</b>` : esc(part)));
    view.innerHTML = `<span style="color:var(--muted)">Cálculo:</span> ${parts.join('')}${$('pbApply').value === 'per_passenger' ? ' <span style="color:var(--muted)">× passageiros</span>' : ''}`;
  }

  let timer = null;
  let seq = 0;
  function schedulePreview() {
    clearTimeout(timer);
    timer = setTimeout(runPreview, 220);
  }

  async function runPreview() {
    const mine = ++seq;
    const fields = readFields();
    const values = {};
    fields.forEach((f) => { values[f.key] = testValues[f.key] ?? exampleValue(f); });
    const box = $('pbResult');
    try {
      const res = await fetch('/airlines/formula-preview', {
        method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
        body: JSON.stringify({formula: formulaInput.value.trim() || modelFor(kind()).formula, fields, values}),
      });
      const data = await res.json();
      if (mine !== seq) return;
      lastPreview = data;
      box.classList.toggle('is-error', !data.ok);
      if (data.ok) {
        const perPax = $('pbApply').value === 'per_passenger';
        $('pbResultValue').textContent = brl.format(data.result) + (perPax ? ' por passageiro' : '');
      } else {
        $('pbResultValue').textContent = data.error || 'Cálculo inválido';
      }
    } catch (_) {
      if (mine === seq) { box.classList.remove('is-error'); $('pbResultValue').textContent = '—'; }
    }
  }

  function refresh() {
    const fields = readFields();
    renderTest(fields);
    renderFormulaView(fields);
    schedulePreview();
  }

  function refreshPreviewCard() {
    const name = $('pbName').value.trim();
    $('pbNamePreview').textContent = name || 'Sem nome';
    $('pbKindPreview').textContent = kindLabels[kind()] || '';
    const logo = $('pbLogoPreview');
    logo.style.setProperty('--pb-color', $('pbColor').value);
    const file = $('pbLogo').files?.[0];
    if (file && file.type.startsWith('image/')) {
      const url = URL.createObjectURL(file);
      logo.innerHTML = `<img src="${url}" alt="">`;
    } else {
      logo.textContent = (name || '?').trim().slice(0, 2).toUpperCase();
    }
  }

  // Inicialização: rascunho (voltou com erro) ou modelo da categoria.
  let draftFields = [];
  try { draftFields = JSON.parse($('pbFieldsJson').value || '[]'); } catch (_) { draftFields = []; }
  if (Array.isArray(draftFields) && draftFields.length) {
    draftFields.forEach(addFieldRow);
    if (!formulaInput.value.trim()) formulaInput.value = modelFor(kind()).formula;
    customized = true;
  } else {
    const keepFormula = formulaInput.value.trim();
    applyModel(kind());
    if (keepFormula) { formulaInput.value = keepFormula; customized = true; }
  }

  form.querySelectorAll('input[name="catalog_kind"]').forEach((el) => el.addEventListener('change', () => {
    const switchToMiles = el.value === 'miles';
    const currentIsMiles = readFields().some((f) => f.key === 'milhas');
    if (!customized || (switchToMiles !== currentIsMiles && confirm('Trocar também o cálculo para o modelo desta categoria? Suas personalizações do cálculo serão substituídas.'))) {
      applyModel(el.value);
    }
    refreshPreviewCard();
    refresh();
  }));
  formulaInput.addEventListener('input', () => { customized = true; refresh(); });
  $('pbApply').addEventListener('change', refresh);
  $('pbName').addEventListener('input', refreshPreviewCard);
  $('pbColor').addEventListener('input', refreshPreviewCard);
  $('pbLogo').addEventListener('change', refreshPreviewCard);
  form.querySelector('[data-pb-add]').addEventListener('click', () => { addFieldRow({field_type: 'number', default_value: '0'}); customized = true; refresh(); fieldsBox.lastElementChild?.querySelector('input')?.focus(); });
  form.querySelectorAll('[data-pb-preset]').forEach((btn) => btn.addEventListener('click', () => {
    const p = presets[btn.dataset.pbPreset];
    const used = new Set(readFields().map((f) => f.key));
    if (used.has(p.key)) return;
    addFieldRow(p);
    customized = true;
    if (p.key === 'taxa_adicional') formulaInput.value = `(${formulaInput.value.trim()}) + taxa_adicional`;
    if (p.key === 'desconto') formulaInput.value = `(${formulaInput.value.trim()}) * (1 - desconto / 100)`;
    refresh();
  }));
  form.querySelector('[data-pb-reset]').addEventListener('click', () => { applyModel(kind()); refresh(); });

  form.addEventListener('submit', (event) => {
    const errorBox = $('pbClientError');
    const name = $('pbName').value.trim();
    let message = '';
    const fields = readFields();
    const keys = fields.map((f) => f.key);
    if (name.length < 2) message = 'Informe o nome do cadastro.';
    else if (!fields.length) message = 'O cálculo precisa de pelo menos um campo.';
    else if (keys.some((k) => !/^[A-Za-z_][A-Za-z0-9_]*$/.test(k))) message = 'Há uma chave de campo inválida. Use letras, números e _ (sem espaços ou acentos).';
    else if (new Set(keys).size !== keys.length) message = 'Há campos com a mesma chave.';
    else if (lastPreview && lastPreview.ok === false) message = `O cálculo tem um problema: ${lastPreview.error}`;
    if (message) {
      event.preventDefault();
      event.stopImmediatePropagation();
      errorBox.textContent = message;
      errorBox.hidden = false;
      if (name.length < 2) $('pbName').focus(); else $('pbAdvanced').open = true;
      return;
    }
    errorBox.hidden = true;
    $('pbFieldsJson').value = JSON.stringify(fields.map((f, i) => ({...f, order_index: i})));
    if (!formulaInput.value.trim()) formulaInput.value = modelFor(kind()).formula;
    window.dbmShowLoader?.('Salvando cadastro…');
  });

  refreshPreviewCard();
  refresh();
})();
