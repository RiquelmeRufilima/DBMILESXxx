(() => {
  const typeInputs = [...document.querySelectorAll('input[name="travel_type"]')];
  const returnLabel = document.getElementById('returnDateLabel');
  const multiBuilder = document.getElementById('multiCityBuilder');
  const segmentRows = document.getElementById('segmentRows');
  const segmentsJson = document.getElementById('segmentsJson');
  const addSegment = document.getElementById('addSegment');
  const standardRouteFields = document.getElementById('standardRouteFields');
  const standardDates = document.getElementById('standardDates');
  const multiRouteInfo = document.getElementById('multiRouteInfo');

  let segments = [];
  try { segments = JSON.parse(segmentsJson?.value || '[]'); } catch { segments = []; }
  if (!Array.isArray(segments)) segments = [];

  const escapeAttr = (value) => String(value || '').replace(/"/g, '&quot;');
  const field = (value, placeholder, type = 'text', className = '') => `<input type="${type}" class="${className}" value="${escapeAttr(value)}" placeholder="${placeholder}" autocomplete="off">`;

  const syncSegments = () => {
    if (!segmentRows || !segmentsJson) return;
    const rows = [...segmentRows.querySelectorAll('.segment-row')];
    segments = rows.map((row) => {
      const inputs = row.querySelectorAll('input');
      return { origin: inputs[0].value.trim(), destination: inputs[1].value.trim(), date: inputs[2].value };
    }).filter((item) => item.origin || item.destination || item.date);
    segmentsJson.value = JSON.stringify(segments);
    rows.forEach((row, index) => row.querySelector('.segment-number').textContent = `Trecho ${index + 1}`);
  };

  const renderSegments = () => {
    if (!segmentRows) return;
    segmentRows.innerHTML = '';
    if (!segments.length) segments = [{origin:'', destination:'', date:''}, {origin:'', destination:'', date:''}];
    segments.forEach((item) => {
      const row = document.createElement('div');
      row.className = 'segment-row';
      row.innerHTML = `<span class="segment-number"></span><label>Origem${field(item.origin,'IATA de 3 letras','text','multi-iata-input')}</label><label>Destino${field(item.destination,'IATA de 3 letras','text','multi-iata-input')}</label><label>Data${field(item.date,'','date')}</label><button type="button" class="field-remove" aria-label="Remover trecho">×</button>`;
      row.querySelectorAll('input').forEach((input) => input.addEventListener('input', syncSegments));
      row.querySelector('.field-remove').addEventListener('click', () => { row.remove(); syncSegments(); });
      segmentRows.appendChild(row);
    });
    syncSegments();
  };

  const updateTravelMode = () => {
    if (!typeInputs.length) return;
    const value = document.querySelector('input[name="travel_type"]:checked')?.value || 'round_trip';
    const isMulti = value === 'multi_city';
    if (returnLabel) returnLabel.style.display = value === 'round_trip' ? '' : 'none';
    if (multiBuilder) multiBuilder.style.display = isMulti ? 'block' : 'none';
    if (standardRouteFields) {
      standardRouteFields.hidden = false;
      standardRouteFields.querySelectorAll('input[name="origin"],input[name="destination"]').forEach(input => {
        input.disabled = isMulti;
        const label = input.closest('label');
        if(label) label.hidden = isMulti;
      });
      const quoteName = standardRouteFields.querySelector('input[name="quote_name"],input[name="variant_name"]');
      if(quoteName) { quoteName.disabled = false; const label=quoteName.closest('label'); if(label) label.hidden = false; }
    }
    if (standardDates) {
      standardDates.hidden = isMulti;
      standardDates.querySelectorAll('input').forEach(input => { input.disabled = isMulti; });
    }
    if (multiRouteInfo) multiRouteInfo.hidden = !isMulti;
    if (isMulti && segmentRows && !segmentRows.children.length) renderSegments();
  };

  typeInputs.forEach((input) => input.addEventListener('change', updateTravelMode));
  addSegment?.addEventListener('click', () => { syncSegments(); segments.push({origin:'', destination:'', date:''}); renderSegments(); });
  document.querySelectorAll('form').forEach((form) => form.addEventListener('submit', syncSegments));
  renderSegments();
  updateTravelMode();
})();
