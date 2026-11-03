/* DBMILESX - itinerário facultativo por sentido e conexão.
   Não modifica as fórmulas existentes nem faz requests extras. */
(() => {
  'use strict';
  const form = document.getElementById('quoteForm');
  const partnerArea = document.getElementById('partnerAirlineField');
  const hidden = document.getElementById('dbmItineraryJson');
  if (!form || !partnerArea || !hidden) return;
  const readJSON = (id, fallback) => {
    try { return JSON.parse(document.getElementById(id)?.textContent || ''); }
    catch { return fallback; }
  };
  const scopeData = readJSON('routeScopesData', []);
  const persisted = readJSON('dbmItineraryInitial', {});
  const partnerOptions = readJSON('partnerAirlineOptionsJson', []);
  const selectedScope = document.getElementById('scopeKeyInput');
  let currentKey = selectedScope?.value || scopeData[0]?.key || 'one_way';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const validIata = value => /^[A-Z]{3}$/.test(String(value || '').trim().toUpperCase());
  const firstCode = value => (String(value || '').toUpperCase().match(/\b[A-Z]{3}\b/) || [])[0] || '';
  const model = {sides:{}, bags_applies_to: String(persisted.bags_applies_to || 'all')};
  (Array.isArray(persisted.sides) ? persisted.sides : []).forEach(side => {
    if (side && side.key) {
      model.sides[side.key] = {
        ...side, stops: Array.isArray(side.stops) ? side.stops : [],
        legs: Array.isArray(side.legs) ? side.legs : []
      };
    }
  });
  // Layout solicitado: não cria um segundo painel, reutiliza os campos originais.
  const metadataSection = form.querySelector('.option-metadata-section');
  const metadataFields = metadataSection?.querySelector('.form-grid');
  const baggageSection = form.querySelector('.baggage-section');
  const optionalStack = form.querySelector('.optional-bottom-stack');
  const datesCard = optionalStack?.querySelector('.optional-bottom-card');
  const flightPanel = document.getElementById('flightDetailsPanel');
  const flightCard = flightPanel?.closest('.optional-bottom-card');
  if (!metadataSection || !metadataFields || !baggageSection || !optionalStack || !datesCard || !flightCard) return;

  // Os selects já usados pelo backend continuam no formulário, mas sem
  // duplicar visualmente os campos por sentido. O primeiro sentido é o padrão.
  const originalInputs = document.createElement('div');
  originalInputs.className = 'dbm-itinerary-legacy-inputs';
  originalInputs.hidden = true;
  ['cabin_class','fare_brand','included_bags_per_passenger'].forEach(name => {
    const field = metadataFields.querySelector(`[name="${name}"]`);
    if (field?.closest('label')) originalInputs.append(field.closest('label'));
  });
  metadataSection.append(originalInputs);

  // Observação abaixo das datas, como na referência, preservando o mesmo name.
  const note = metadataFields.querySelector('[name="option_description"]')?.closest('label');
  if (note) {
    const observations = document.createElement('div');
    observations.className = 'dbm-itinerary-observation';
    observations.append(note);
    datesCard.insertAdjacentElement('afterend', observations);
  }

  // Custos/taxas adicionais que já existem permanecem, mas recolhidos para
  // não competir com os blocos simples de ida/volta.
  const feeCard = document.createElement('details');
  feeCard.className = 'dbm-itinerary-fees';
  feeCard.innerHTML = '<summary>Taxas e identificação adicionais (opcionais)</summary>';
  feeCard.append(metadataFields);
  metadataSection.append(feeCard);
  const feeHasContent = [...metadataFields.querySelectorAll('input')]
    .some(input => input.name === 'extra_name' ? !!input.value.trim() :
      input.name === 'extra_value' && Number(input.value) > 0);
  feeCard.open = feeHasContent;

  const panel = document.createElement('div');
  panel.className = 'dbm-itinerary-panel dbm-layout-reference';
  panel.id = 'dbmItineraryPanel';
  panel.innerHTML = `
    <div class="dbm-itinerary-sides" id="dbmItinerarySides"></div>
    <details class="dbm-itinerary-copy-tools">
      <summary>↪ Repetir configurações entre trechos (opcional)</summary>
      <div class="dbm-itinerary-actions">
        <button type="button" class="secondary-button small-button" data-copy="all">Repetir do 1º trecho em todos</button>
        <button type="button" class="secondary-button small-button" data-copy="outbound">Repetir apenas na ida</button>
        <button type="button" class="secondary-button small-button" data-copy="return">Repetir apenas na volta</button>
      </div>
    </details>`;
  feeCard.insertAdjacentElement('beforebegin', panel);
  const sidesBox = panel.querySelector('#dbmItinerarySides');

  // A bagagem adicional continua no bloco 3, sem criar bagagem por conexão.
  const bagsInput = baggageSection.querySelector('[name="bags_override"]');
  if (bagsInput && !document.getElementById('dbmBaggageScope')) {
    const place = document.createElement('label');
    place.className = 'dbm-baggage-scope';
    place.innerHTML = 'Aplicar bagagem adicional em <select id="dbmBaggageScope" aria-label="Sentido da bagagem adicional"></select><small>Mesma quantidade e mesmo valor do cálculo original. Sem cobrança duplicada.</small>';
    bagsInput.closest('label')?.insertAdjacentElement('afterend',place);
  }
  const bagsScopeInput = document.getElementById('dbmBaggageScope');

  // Horários sob as datas, numa área independente, facultativa.
  // O controle de alternativas já existente é preservado e pode ser aberto
  // dentro da mesma seção; seus listeners e input names não mudam.
  datesCard.open = true;
  const schedule = document.createElement('details');
  schedule.className = 'dbm-itinerary-schedules dbm-reference-schedules';
  schedule.open = true;
  schedule.innerHTML = '<summary>◢ &nbsp; Horários do voo (opcionais)</summary><div class="dbm-reference-timing" id="dbmItinerarySchedules"></div>';
  if (note) note.closest('.dbm-itinerary-observation').insertAdjacentElement('afterend', schedule);
  else datesCard.insertAdjacentElement('afterend', schedule);
  const alternatives = document.createElement('div');
  alternatives.className = 'dbm-reference-alternatives';
  schedule.append(alternatives);
  alternatives.append(flightCard);
  const schedulesBox = schedule.querySelector('#dbmItinerarySchedules');

  const partnerGrid = partnerArea.querySelector('.partner-segment-grid');
  const extraPartners = document.createElement('div');
  extraPartners.className = 'dbm-partners-expanded';
  extraPartners.id = 'dbmStopPartnerGrid';
  if (partnerGrid) partnerGrid.insertAdjacentElement('afterend',extraPartners);
  const list = document.createElement('datalist');
  list.id = 'dbmItineraryPartners';
  (Array.isArray(partnerOptions) ? partnerOptions : []).forEach(item => {
    if (typeof item?.name !== 'string' || !item.name.trim()) return;
    const opt = document.createElement('option');
    opt.value = item.name.trim();
    list.append(opt);
  });
  panel.append(list);
  const initialCarrier = document.getElementById('partnerAirlineInput')?.value || '';
  const globalCabin = form.querySelector('[name="cabin_class"]')?.value || '';
  const globalFare = form.querySelector('[name="fare_brand"]')?.value || '';
  const globalBags = form.querySelector('[name="included_bags_per_passenger"]')?.value || '';
  function activeSegments() {
    const scope = scopeData.find(row => row.key === currentKey) || scopeData[0] || {};
    return (Array.isArray(scope.segments) ? scope.segments : []).map((segment, i) => ({
      key:String(segment.key || `segment_${i+1}`),
      origin:firstCode(segment.origin), destination:firstCode(segment.destination)
    })).filter(seg => seg.origin && seg.destination);
  }
  function getSide(segment) {
    const previous = model.sides[segment.key];
    if (previous) {
      if(previous.cabin===undefined)previous.cabin=previous.legs?.[0]?.cabin || globalCabin;
      if(previous.fare===undefined)previous.fare=previous.legs?.[0]?.fare || globalFare;
      if(previous.included_bags===undefined)previous.included_bags=String(previous.legs?.[0]?.included_bags ?? globalBags);
      previous.origin = segment.origin;
      previous.destination = segment.destination;
      return previous;
    }
    const segmentIndex=activeSegments().findIndex(s=>s.key===segment.key);
    const priorPartner=partnerGrid?.querySelector(`[data-segment="${segmentIndex+1}"]`)?.value || initialCarrier;
    const side = {key:segment.key, status:'direct', stops:[], legs:[{partner:priorPartner}], origin:segment.origin, destination:segment.destination, cabin:globalCabin, fare:globalFare, included_bags:globalBags};
    model.sides[segment.key] = side;
    return side;
  }
  function newLeg(origin,destination,previous) {
    return {
      origin, destination, partner:previous?.partner ?? initialCarrier,
      departure:previous?.departure || '', arrival:previous?.arrival || '',
      origin_tz:previous?.origin_tz || '', destination_tz:previous?.destination_tz || ''
    };
  }
  function rebuildLegs(side){
    const codes = [side.origin, ...(side.status==='stops'?side.stops:[]), side.destination];
    const existing = Array.isArray(side.legs) ? side.legs : [];
    side.legs = codes.slice(0,-1).map((origin,i) => newLeg(origin,codes[i+1],existing[i]));
  }
  function zoneOptions(value){
    const offsets=['','-05:00','-04:00','-03:00','-02:00','-01:00','+00:00','+01:00','+02:00','+03:00','+04:00','+05:00','+05:30','+06:00','+07:00','+08:00','+09:00','+10:00','+11:00','+12:00','+13:00','+14:00'];
    if (value && !offsets.includes(value)) offsets.push(value);
    return offsets.map(off => `<option value="${esc(off)}" ${off===value?'selected':''}>${off?'UTC'+off:'Fuso horário…'}</option>`).join('');
  }
  function classOptions(value){
    return ['','Econômica','Premium','Executiva','Primeira'].map(cls => `<option value="${esc(cls)}" ${cls===value?'selected':''}>${esc(cls || 'Não informado')}</option>`).join('');
  }
  const fareSelect = form.querySelector('[name="fare_brand"]');
  const cabinSelect = form.querySelector('[name="cabin_class"]');
  const bagSelect = form.querySelector('[name="included_bags_per_passenger"]');
  function optionsLike(select,value) {
    if(!select) return '';
    const items=[...select.options];
    // Não perde uma tarifa salva anteriormente, mesmo que tenha sido
    // personalizada e já não conste da lista atual.
    const custom=value && !items.some(o=>String(o.value)===String(value))
      ? `<option value="${esc(value)}" selected>${esc(value)} (salva)</option>` : '';
    return custom+items.map(o=>`<option value="${esc(o.value)}" ${String(o.value)===String(value)?'selected':''}>${esc(o.textContent)}</option>`).join('');
  }
  function sideConditions(side) {
    const cabin=side.cabin ?? (side.legs[0]?.cabin || globalCabin);
    const fare=side.fare ?? (side.legs[0]?.fare || globalFare);
    const bags=side.included_bags ?? (side.legs[0]?.included_bags ?? globalBags);
    return `<div class="dbm-side-conditions">
      <div class="dbm-itinerary-grid dbm-condition-grid">
        <label>Classe<select data-side-field="cabin">${optionsLike(cabinSelect,cabin)}</select></label>
        <label>Tarifa<select data-side-field="fare">${optionsLike(fareSelect,fare)}</select></label>
        <label>Bagagem incluída<select data-side-field="included_bags">${optionsLike(bagSelect,bags)}</select></label>
      </div></div>`;
  }
  function legHTML(side,leg,i){
    return `<article class="dbm-itinerary-leg" data-leg="${i}">
      <div class="dbm-itinerary-leghead"><b>${esc(leg.origin)} → ${esc(leg.destination)}</b><small>Horários opcionais</small></div>
      <div class="dbm-itinerary-grid dbm-timing-grid">
        <label>Saída ${esc(leg.origin)}<input type="datetime-local" data-field="departure" value="${esc(leg.departure)}"></label>
        <label>Fuso saída<select data-field="origin_tz">${zoneOptions(leg.origin_tz)}</select></label>
        <label>Chegada ${esc(leg.destination)}<input type="datetime-local" data-field="arrival" value="${esc(leg.arrival)}"></label>
        <label>Fuso chegada<select data-field="destination_tz">${zoneOptions(leg.destination_tz)}</select></label>
      </div></article>`;
  }
  function partnerCards(segments){
    const sides=segments.map(s=>model.sides[s.key]).filter(Boolean);
    const expanded=sides.some(s=>s.status==='stops' && s.stops.some(Boolean));
    // O HTML original pode conter a quantidade MÁXIMA de trechos entre
    // modalidades. Mostra só os da modalidade ativa (só ida = 1 cartão).
    const cards = [...(partnerGrid?.querySelectorAll('.partner-segment-card') || [])];
    cards.forEach((card,index)=>{
      const active=segments[index];
      card.hidden=!active;
      const input=card.querySelector('.partner-segment-input');
      if(input) input.disabled=!active;
      if(active){
        const route=card.querySelector('.partner-segment-route small');
        if(route) route.textContent=`${active.origin} → ${active.destination}`;
      }
    });
    if(partnerGrid)partnerGrid.hidden=expanded;
    if(!expanded){extraPartners.innerHTML='';return;}
    extraPartners.innerHTML=sides.map((side)=>side.legs.map((leg,i)=>
      `<label class="dbm-partner-route" data-partner-side="${esc(side.key)}" data-partner-leg="${i}">
      <span>${side.key==='return'?'Volta':side.key==='outbound'||side.key==='one_way'?'Ida':'Trecho'} • ${esc(leg.origin)} → ${esc(leg.destination)}</span>
      <input list="dbmItineraryPartners" placeholder="Parceria opcional" value="${esc(leg.partner)}" data-partner-edit></label>`
    ).join('')).join('');
  }
  function sideHTML(segment){
    const side=getSide(segment);
    const label=side.key==='return'?'VOLTA':side.key==='outbound'||side.key==='one_way'?'IDA':side.key.replace('_',' ').toUpperCase();
    const count=side.stops.length;
    return `<section class="dbm-itinerary-side" data-side="${esc(side.key)}">
      <div class="dbm-itinerary-sidehead"><b>✈️ ${label} • ${esc(side.origin)} → ${esc(side.destination)}</b><small>Todos os campos opcionais</small></div>
      <div class="dbm-itinerary-grid dbm-status-grid">
        <label>Status do voo<select data-side-field="status"><option value="direct" ${side.status!=='stops'?'selected':''}>Direto / sem conexão informada</option><option value="stops" ${side.status==='stops'?'selected':''}>Com parada(s)</option></select></label>
        ${side.status==='stops'?`<label>Quantidade de paradas<select data-side-field="stop_count">${Array.from({length:4},(_,i)=>`<option value="${i+1}" ${count===i+1?'selected':''}>${i+1}</option>`).join('')}</select></label>`:''}
        ${side.status==='stops'?side.stops.map((stop,i)=>`<label>Parada ${i+1} • aeroporto IATA<input data-stop="${i}" value="${esc(stop)}" maxlength="3" placeholder="Ex.: BSB"></label>`).join(''):''}
      </div>
      ${sideConditions(side)}
    </section>`;
  }
  function timingHTML(segment){
    const side=getSide(segment);
    const label=side.key==='return'?'VOLTA':side.key==='outbound'||side.key==='one_way'?'IDA':side.key.replace('_',' ').toUpperCase();
    const first=side.legs[0]||{};
    const last=side.legs.at(-1)||{};
    // A linha principal e a primeira/última etapa usam os mesmos valores;
    // não são horários independentes que podem divergir no salvamento.
    return `<section class="dbm-reference-time-side" data-side="${esc(side.key)}">
      <div class="dbm-reference-time-head"><strong>${esc(label)} • ${esc(side.origin)} → ${esc(side.destination)}</strong><small>Horários opcionais</small></div>
      <div class="dbm-itinerary-grid dbm-timing-grid dbm-main-timing">
        <label>Saída ${esc(side.origin)}<input type="datetime-local" data-main-field="departure" value="${esc(first.departure)}"></label>
        <label>Fuso saída<select data-main-field="origin_tz">${zoneOptions(first.origin_tz)}</select></label>
        <label>Chegada ${esc(side.destination)}<input type="datetime-local" data-main-field="arrival" value="${esc(last.arrival)}"></label>
        <label>Fuso chegada<select data-main-field="destination_tz">${zoneOptions(last.destination_tz)}</select></label>
      </div>
      ${side.status==='stops'?`<details class="dbm-reference-stop-times" open><summary>◢ &nbsp; Horários das etapas e conexões (opcionais)</summary>
        <div class="dbm-itinerary-legs">${side.legs.map((leg,i)=>legHTML(side,leg,i)).join('')}</div>
      </details>`:''}
      <div class="dbm-itinerary-duration" data-duration="${esc(side.key)}"></div>
    </section>`;
  }
  function updateBaggageScope(segments){
    if(!bagsScopeInput)return;
    const previous=model.bags_applies_to;
    const options=[{key:'all',label:'Percurso completo (como já era)'}];
    if(segments.length>1)segments.forEach((s,i)=>options.push({key:s.key,label:s.key==='return'?'Somente volta':s.key==='outbound'?'Somente ida':`Somente trecho ${i+1}`}));
    bagsScopeInput.innerHTML=options.map(o=>`<option value="${esc(o.key)}">${esc(o.label)}</option>`).join('');
    model.bags_applies_to=options.some(o=>o.key===previous)?previous:'all';
    bagsScopeInput.value=model.bags_applies_to;
    bagsScopeInput.closest('label').hidden=segments.length<2;
  }
  if(bagsScopeInput)bagsScopeInput.addEventListener('change',()=>{model.bags_applies_to=bagsScopeInput.value;saveHidden()});
  partnerGrid?.addEventListener('input',event=>{
    const input=event.target.closest('.partner-segment-input');
    if(!input)return;
    const seg=activeSegments()[Number(input.dataset.segment)-1];
    if(!seg)return;
    const side=model.sides[seg.key];
    if(side?.legs?.length){side.legs[0].partner=input.value;saveHidden()}
  });
  extraPartners.addEventListener('input',e=>{
    if(!e.target.matches('[data-partner-edit]'))return;
    const row=e.target.closest('[data-partner-side]');
    const side=model.sides[row?.dataset.partnerSide];
    const leg=side?.legs[Number(row?.dataset.partnerLeg)];
    if(leg){leg.partner=e.target.value;saveHidden()}
  });
  function render(){
    const segments=activeSegments();
    segments.forEach(segment => {
      const side=getSide(segment);
      if(side.status==='stops' && !side.stops.length) side.stops=[''];
      rebuildLegs(side);
    });
    sidesBox.innerHTML = segments.length ? segments.map(sideHTML).join('') : '<p>Sem rota configurada. O cálculo continua normalmente.</p>';
    schedulesBox.innerHTML = segments.length ? segments.map(timingHTML).join('') : '';
    partnerCards(segments);
    updateBaggageScope(segments);
    totals();
    saveHidden();
  }
  function offsetMinutes(tz) {if(!/^[+-]\d\d:\d\d$/.test(tz||''))return null;return (tz[0]==='+'?1:-1)*(Number(tz.slice(1,3))*60+Number(tz.slice(4,6)));}
  function utc(date,tz){if(!date||offsetMinutes(tz)===null)return null;const ms=Date.parse(date+':00Z');return Number.isFinite(ms)?ms-offsetMinutes(tz)*60000:null;}
  const fmtMinutes=min=>`${Math.floor(min/60)}h ${String(min%60).padStart(2,'0')}min`;
  function totals(){
    activeSegments().forEach(segment=>{
      const side=model.sides[segment.key];if(!side)return;
      const legs=side.legs||[];
      const node=schedulesBox.querySelector(`[data-duration="${side.key}"]`);if(!node)return;
      if(!legs.length){node.textContent='';return;}
      const first=utc(legs[0].departure,legs[0].origin_tz);
      const last=utc(legs.at(-1).arrival,legs.at(-1).destination_tz);
      let complete=first!==null&&last!==null&&last>=first;
      const waits=[];
      legs.forEach((leg,i)=>{
        const dep=utc(leg.departure,leg.origin_tz),arr=utc(leg.arrival,leg.destination_tz);
        if(dep===null||arr===null||arr<dep)complete=false;
        if(i<legs.length-1){const next=legs[i+1];const nextDep=utc(next.departure,next.origin_tz);const wait=arr!==null&&nextDep!==null?Math.round((nextDep-arr)/60000):null;waits.push(wait);if(wait===null||wait<0)complete=false;}
      });
      node.textContent=complete?`Duração total: ${fmtMinutes(Math.round((last-first)/60000))}${waits.length?' • Esperas: '+waits.map((w,i)=>`${side.stops[i]} ${fmtMinutes(w)}`).join(' • '):''}`:'Duração total: opcional. Informe datas, horas e fusos de todas as etapas para calcular corretamente.';
    });

  }
  function saveHidden(){
    activeSegments().forEach((seg,i)=>{const input=partnerGrid?.querySelector(`[data-segment="${i+1}"]`);const s=model.sides[seg.key];if(input&&s?.legs?.[0]?.partner!==undefined&&input.value!==s.legs[0].partner)input.value=s.legs[0].partner;});
    hidden.value=JSON.stringify({version:2,sides:activeSegments().map(seg=>model.sides[seg.key]).filter(Boolean),bags_applies_to:model.bags_applies_to,charge_extra_bags:false});
  }
  function topologyChanged(target,side,root){
    if(['cabin','fare','included_bags'].includes(target.dataset.sideField)){
      side[target.dataset.sideField]=target.value;
      // Mantém os inputs originais compatíveis com os cálculos antigos.
      const first=activeSegments()[0];
      if(first?.key===side.key){
        const master=target.dataset.sideField==='cabin'?cabinSelect:target.dataset.sideField==='fare'?fareSelect:bagSelect;
        if(master && [...master.options].some(o=>o.value===target.value)) master.value=target.value;
      }
      saveHidden();return true;}
    if(target.dataset.sideField==='status'){
      side.status=target.value==='stops'?'stops':'direct';
      if(side.status==='stops'&&!side.stops.length)side.stops=[''];
      render();return true;
    }
    if(target.dataset.sideField==='stop_count'){
      const count=Math.min(4,Math.max(1,Number(target.value)||1));
      side.stops=Array.from({length:count},(_,i)=>side.stops[i]||'');
      render();return true;
    }
    if(target.hasAttribute('data-stop')){
      const idx=Number(target.dataset.stop);
      side.stops[idx]=target.value.trim().toUpperCase();
      if(validIata(side.stops[idx])){rebuildLegs(side);render();}
      else saveHidden();
      return true;
    }
    return false;
  }
  sidesBox.addEventListener('input', e=>{
    const target=e.target;const root=target.closest('[data-side]');if(!root)return;
    const side=model.sides[root.dataset.side];if(!side)return;
    if(target.hasAttribute('data-stop')){side.stops[Number(target.dataset.stop)]=target.value.trim().toUpperCase();saveHidden();return;}
    if(target.dataset.sideField==='fare'){
      side.fare=target.value;
      const first=activeSegments()[0];
      if(first?.key===side.key && fareSelect && [...fareSelect.options].some(o=>o.value===target.value)) fareSelect.value=target.value;
      saveHidden();return;}
    const legRoot=target.closest('[data-leg]');if(legRoot&&target.dataset.field){const leg=side.legs[Number(legRoot.dataset.leg)];if(leg)leg[target.dataset.field]=target.value;totals();saveHidden();}
  });
  sidesBox.addEventListener('change', e=>{
    const target=e.target, root=target.closest('[data-side]');if(!root)return;
    const side=model.sides[root.dataset.side];if(!side)return;
    if(topologyChanged(target,side,root))return;
    const legRoot=target.closest('[data-leg]');if(legRoot&&target.dataset.field){const leg=side.legs[Number(legRoot.dataset.leg)];if(leg)leg[target.dataset.field]=target.value;totals();saveHidden();}
  });
  function updateTimeInput(target){
    const root=target.closest('[data-side]');
    const side=model.sides[root?.dataset.side];
    if(!side?.legs?.length)return;
    if(target.hasAttribute('data-main-field')){
      const key=target.dataset.mainField;
      const leg=['departure','origin_tz'].includes(key)?side.legs[0]:side.legs.at(-1);
      leg[key]=target.value;
      const corresponding=root.querySelector(`[data-leg="${leg===side.legs[0]?0:side.legs.length-1}"] [data-field="${key}"]`);
      if(corresponding) corresponding.value=target.value;
    } else if(target.hasAttribute('data-field')) {
      const legRoot=target.closest('[data-leg]');
      const idx=Number(legRoot?.dataset.leg);
      const leg=side.legs[idx];
      if(!leg)return;
      leg[target.dataset.field]=target.value;
      const mainKey=target.dataset.field;
      if((idx===0&&['departure','origin_tz'].includes(mainKey))||
          (idx===side.legs.length-1&&['arrival','destination_tz'].includes(mainKey))){
        const corresponding=root.querySelector(`[data-main-field="${mainKey}"]`);
        if(corresponding) corresponding.value=target.value;
      }
    } else return;
    totals();saveHidden();
  }
  schedulesBox.addEventListener('input', e=>updateTimeInput(e.target));
  schedulesBox.addEventListener('change', e=>updateTimeInput(e.target));
  panel.querySelectorAll('[data-copy]').forEach(button=>button.addEventListener('click',()=>{
    const target=button.dataset.copy;
    const sides=activeSegments().map(seg=>model.sides[seg.key]).filter(Boolean);
    const source=(target==='return'?sides.find(s=>s.key==='return'):sides.find(s=>s.key!=='return'))||sides[0];
    if(!source?.legs.length)return;
    const recipients=sides.filter(s=>target==='all'||(target==='return'?s.key==='return':s.key!=='return'));
    if(!recipients.length)return;
    if(!confirm('Repetir parceria, classe, tarifa e bagagem incluída do primeiro trecho? Não serão alterados horários, rotas nem bagagem paga.'))return;
    const first=source.legs[0];
    recipients.forEach(side=>{
      ['cabin','fare','included_bags'].forEach(key=>{side[key]=source[key]??''});
      side.legs.forEach((leg,i)=>{if(side!==source||i!==0)leg.partner=first.partner});
    });
    render();
  }));
  document.addEventListener('calculation-scope-will-change',()=>saveHidden());
  document.addEventListener('calculation-scope-changed',event=>{currentKey=event.detail?.to||selectedScope?.value||currentKey;render();});
  form.addEventListener('submit',()=>saveHidden(),true);
  render();
})();
