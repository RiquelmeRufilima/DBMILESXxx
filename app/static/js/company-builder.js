(() => {
  const form = document.getElementById('airlineBuilderForm');
  const container = document.getElementById('fieldBuilder');
  const output = document.getElementById('fieldsJson');
  if (!form || !container || !output) return;

  const slugKey = (text) => text.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').replace(/^([0-9])/, '_$1');

  const presets = {
    discount: {label:'Desconto (%)', key:'desconto', field_type:'percent', default_value:'0', min_value:0, max_value:100, step:1},
    interest: {label:'Juros (%)', key:'juros', field_type:'percent', default_value:'0', min_value:0, max_value:1000, step:1},
    fee: {label:'Taxa adicional', key:'taxa_adicional', field_type:'number', default_value:'0', min_value:0, max_value:'', step:.01}
  };

  function fieldRow(data = {}) {
    const row = document.createElement('div');
    row.className = 'field-row';
    row.innerHTML = `
      <label>Nome<input data-field="label" value="${data.label || ''}" placeholder="Ex: Taxa de embarque" required></label>
      <label>Chave<input data-field="key" value="${data.key || ''}" placeholder="taxa" required></label>
      <label>Tipo<select data-field="field_type"><option value="number">Número</option><option value="integer">Inteiro</option><option value="percent">Percentual</option><option value="text">Texto</option></select></label>
      <label>Valor padrão<input data-field="default_value" value="${data.default_value ?? '0'}"></label>
      <button type="button" class="field-remove" aria-label="Remover">×</button>`;
    row.querySelector('[data-field="field_type"]').value = data.field_type || 'number';
    const labelInput = row.querySelector('[data-field="label"]');
    const keyInput = row.querySelector('[data-field="key"]');
    let manuallyEdited = Boolean(data.key);
    keyInput.addEventListener('input', () => { manuallyEdited = true; });
    labelInput.addEventListener('input', () => { if (!manuallyEdited) keyInput.value = slugKey(labelInput.value); });
    row.querySelector('.field-remove').addEventListener('click', () => row.remove());
    row.dataset.extra = JSON.stringify({min_value:data.min_value ?? 0,max_value:data.max_value ?? '',step:data.step ?? .01});
    container.appendChild(row);
  }

  function serialize() {
    const fields = [...container.querySelectorAll('.field-row')].map((row) => {
      const extra = JSON.parse(row.dataset.extra || '{}');
      return {
        label: row.querySelector('[data-field="label"]').value.trim(),
        key: row.querySelector('[data-field="key"]').value.trim(),
        field_type: row.querySelector('[data-field="field_type"]').value,
        default_value: row.querySelector('[data-field="default_value"]').value,
        required: false,
        min_value: extra.min_value,
        max_value: extra.max_value,
        step: extra.step
      };
    }).filter((item) => item.label && item.key);
    output.value = JSON.stringify(fields);
  }

  document.querySelectorAll('[data-add-field]').forEach((button) => button.addEventListener('click', () => fieldRow()));
  document.querySelectorAll('[data-add-preset]').forEach((button) => button.addEventListener('click', () => fieldRow(presets[button.dataset.addPreset])));
  form.addEventListener('submit', serialize);

  fieldRow({label:'Milhas',key:'milhas',field_type:'number',default_value:'0',min_value:0,max_value:'',step:.001});
  fieldRow({label:'Valor do milheiro',key:'milheiro',field_type:'number',default_value:'0',min_value:0,max_value:'',step:.01});
  fieldRow({label:'Taxa',key:'taxa',field_type:'number',default_value:'0',min_value:0,max_value:'',step:.01});
})();
