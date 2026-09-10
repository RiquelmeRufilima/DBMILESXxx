(() => {
  const form = document.getElementById('airlineBuilderForm');
  const container = document.getElementById('fieldBuilder');
  const output = document.getElementById('fieldsJson');
  const formulaInput = document.getElementById('formulaInput');
  if (!form || !container || !output) return;

  const slugKey = (text) => text.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').replace(/^([0-9])/, '_$1');
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));

  const presets = {
    discount: {label:'Desconto (%)', key:'desconto', field_type:'percent', default_value:'0', min_value:0, max_value:100, step:0.01},
    interest: {label:'Juros (%)', key:'juros', field_type:'percent', default_value:'0', min_value:0, max_value:1000, step:0.01},
    fee: {label:'Taxa adicional', key:'taxa_adicional', field_type:'number', default_value:'0', min_value:0, max_value:'', step:0.01},
    tariff: {label:'Tarifa informada', key:'tarifa', field_type:'number', default_value:'0', required:true, min_value:0, max_value:'', step:0.01},
    tariff_discount: {label:'Desconto da tarifa (%)', key:'desconto_percentual', field_type:'percent', default_value:'0', required:false, min_value:0, max_value:100, step:0.01}
  };

  function fieldRow(data = {}) {
    const row = document.createElement('div');
    row.className = 'field-row';
    const optionsText = Array.isArray(data.options) ? data.options.join(', ') : '';
    row.innerHTML = `
      <label>Nome<input data-field="label" value="${esc(data.label || '')}" placeholder="Ex: Tarifa informada" required></label>
      <label>Chave<input data-field="key" value="${esc(data.key || '')}" placeholder="tarifa" required></label>
      <label>Tipo<select data-field="field_type">
        <option value="number">Número</option>
        <option value="integer">Inteiro</option>
        <option value="percent">Percentual</option>
        <option value="text">Texto</option>
        <option value="select">Lista</option>
      </select></label>
      <label>Valor padrão<input data-field="default_value" value="${esc(data.default_value ?? '0')}"></label>
      <label>Mínimo<input data-field="min_value" type="number" step="any" value="${esc(data.min_value ?? '')}"></label>
      <label>Máximo<input data-field="max_value" type="number" step="any" value="${esc(data.max_value ?? '')}"></label>
      <label>Passo<input data-field="step" type="number" step="any" value="${esc(data.step ?? '0.01')}"></label>
      <label>Ajuda<input data-field="help_text" value="${esc(data.help_text || '')}" placeholder="Texto opcional"></label>
      <label class="field-options-label">Opções da lista<input data-field="options" value="${esc(optionsText)}" placeholder="Light, Classic, Flex"></label>
      <label class="field-required-label"><input data-field="required" type="checkbox" ${data.required ? 'checked' : ''}> Obrigatório</label>
      <button type="button" class="field-remove" aria-label="Remover">×</button>`;

    row.querySelector('[data-field="field_type"]').value = data.field_type || 'number';
    const labelInput = row.querySelector('[data-field="label"]');
    const keyInput = row.querySelector('[data-field="key"]');
    const typeSelect = row.querySelector('[data-field="field_type"]');
    const optionsLabel = row.querySelector('.field-options-label');
    let manuallyEdited = Boolean(data.key);

    const updateTypeUi = () => {
      optionsLabel.style.display = typeSelect.value === 'select' ? '' : 'none';
    };

    keyInput.addEventListener('input', () => { manuallyEdited = true; });
    labelInput.addEventListener('input', () => { if (!manuallyEdited) keyInput.value = slugKey(labelInput.value); });
    typeSelect.addEventListener('change', updateTypeUi);
    row.querySelector('.field-remove').addEventListener('click', () => row.remove());
    updateTypeUi();
    container.appendChild(row);
  }

  function serialize() {
    const fields = [...container.querySelectorAll('.field-row')].map((row) => {
      const optionsRaw = row.querySelector('[data-field="options"]').value.trim();
      return {
        label: row.querySelector('[data-field="label"]').value.trim(),
        key: row.querySelector('[data-field="key"]').value.trim(),
        field_type: row.querySelector('[data-field="field_type"]').value,
        default_value: row.querySelector('[data-field="default_value"]').value,
        required: row.querySelector('[data-field="required"]').checked,
        min_value: row.querySelector('[data-field="min_value"]').value,
        max_value: row.querySelector('[data-field="max_value"]').value,
        step: row.querySelector('[data-field="step"]').value,
        help_text: row.querySelector('[data-field="help_text"]').value.trim(),
        options: optionsRaw ? optionsRaw.split(',').map(item => item.trim()).filter(Boolean) : null
      };
    }).filter((item) => item.label && item.key);
    output.value = JSON.stringify(fields);
  }

  function tariffDiscountModel(){
    container.innerHTML = '';
    fieldRow(presets.tariff);
    fieldRow(presets.tariff_discount);
    if(formulaInput) formulaInput.value = 'tarifa - (tarifa * desconto_percentual / 100)';
    const calcName = form.querySelector('[name="calculation_name"]');
    if(calcName && (!calcName.value.trim() || calcName.value === 'Cálculo padrão')) calcName.value = 'Tarifa com desconto';
    const description = form.querySelector('[name="description"]');
    if(description && !description.value.trim()) description.value = 'Retira da tarifa informada o percentual de desconto definido.';
  }

  document.querySelectorAll('[data-add-field]').forEach((button) => button.addEventListener('click', () => fieldRow()));
  document.querySelectorAll('[data-add-preset]').forEach((button) => button.addEventListener('click', () => {
    const preset = presets[button.dataset.addPreset];
    if(preset) fieldRow(preset);
  }));
  document.querySelectorAll('[data-tariff-discount-model]').forEach((button) => button.addEventListener('click', tariffDiscountModel));
  form.addEventListener('submit', serialize);

  let initialFields = null;
  const initialData = document.getElementById('initialFieldsData');
  if(initialData){
    try { initialFields = JSON.parse(initialData.textContent || '[]'); } catch(_error) { initialFields = null; }
  }

  if(Array.isArray(initialFields) && initialFields.length){
    initialFields.forEach(fieldRow);
  }else if(form.dataset.defaultMode === 'tariff-discount'){
    tariffDiscountModel();
  }else{
    fieldRow({label:'Milhas',key:'milhas',field_type:'number',default_value:'0',min_value:0,max_value:'',step:.001});
    fieldRow({label:'Valor do milheiro',key:'milheiro',field_type:'number',default_value:'0',min_value:0,max_value:'',step:.01});
    fieldRow({label:'Taxa',key:'taxa',field_type:'number',default_value:'0',min_value:0,max_value:'',step:.01});
  }
})();