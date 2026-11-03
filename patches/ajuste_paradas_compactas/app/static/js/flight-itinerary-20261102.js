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
  const panel = document.createElement('section');
  panel.className = 'dbm-itinerary-panel';
  panel.id = 'dbmItineraryPanel';
  panel.innerHTML = `
    <details class="dbm-itinerary-compact" id="dbmItineraryDetails">
      <summary><strong>✈️ Condições, paradas e horários do voo</strong><span>OPCIONAL • abrir / fechar</span></summary>
      <div class="dbm-itinerary-content">
        <p class="dbm-itinerary-intro">Tudo opcional. Os campos já existentes foram reunidos aqui; deixar as paradas em branco não impede o cálculo.</p>
        <div class="dbm-itinerary-shared" id="dbmItineraryShared">
          <strong>Padrão desta opção</strong>
          <div class="dbm-itinerary-essentials" id="dbmItineraryEssentials"></div>
          <div id="dbmItineraryBaggage"></div>
        </div>
        <div class="dbm-itinerary-actions">
          <button type="button" class="secondary-button small-button" data-copy="all">Repetir do 1º trecho em todos</button>
          <button type="button" class="secondary-button small-button" data-copy="outbound">Repetir apenas na ida</button>
          <button type="button" class="secondary-button small-button" data-copy="return">Repetir apenas na volta</button>
        </div>
        <div class="dbm-itinerary-sides" id="dbmItinerarySides"></div>
        <div class="dbm-itinerary-schedules" id="dbmItinerarySchedules"></div>
      </div>
    </details>`;
  const calculationSection = form.querySelector('.calculation-values-section');
  if (!calculationSection) return;
  calculationSection.insertAdjacentElement('beforebegin', panel);
  // Mover os inputs REAIS existentes, sem duplicar nomes ou alterar o cálculo.
  const essentials = panel.querySelector('#dbmItineraryEssentials');
  ['cabin_class','fare_brand','included_bags_per_passenger'].forEach(name => {
    const field = form.querySelector(`[name="${name}"]`);
    if (field?.closest('label')) essentials.append(field.closest('label'));
  });
  const baggageSection = form.querySelector('.baggage-section');
  if (baggageSection) {
    panel.querySelector('#dbmItineraryBaggage').append(baggageSection);
    const bagsInput = baggageSection.querySelector('[name="bags_override"]');
    if (bagsInput) {
      const place = document.createElement('label');
      place.className = 'dbm-baggage-scope';
      place.innerHTML = 'Aplicar bagagem adicional em <select id="dbmBaggageScope" aria-label="Sentido da bagagem adicional"></select><small>Usa a mesma quantidade e o mesmo valor do cálculo original. Não duplica a cobrança.</small>';
      bagsInput.closest('label')?.insertAdjacentElement('afterend',place);
    }
  }
  const flightPanel = document.getElementById('flightDetailsPanel');
  const flightCard = flightPanel?.closest('.optional-bottom-card');
  if (flightCard) {
    panel.querySelector('#dbmItinerarySchedules').append(flightCard);
    flightCard.querySelector('summary strong')?.replaceChildren(document.createTextNode('Horários e alternativas do voo (opcionais)'));
  }
  const partnerGrid = partnerArea.querySelector('.partner-segment-grid');
  const extraPartners = document.createElement('div');
  extraPartners.className = 'dbm-partners-expanded';
  extraPartners.id = 'dbmStopPartnerGrid';
  if (partnerGrid) partnerGrid.insertAdjacentElement('afterend',extraPartners);
  const sidesBox = panel.querySelector('#dbmItinerarySides');

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
  const bagsScopeInput = document.getElementById('dbmBaggageScope');
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
    return [...select.options].map(o=>`<option value="${esc(o.value)}" ${String(o.value)===String(value)?'selected':''}>${esc(o.textContent)}</option>`).join('');
  }
  function sideConditions(side) {
    const cabin=side.cabin ?? (side.legs[0]?.cabin || globalCabin);
    const fare=side.fare ?? (side.legs[0]?.fare || globalFare);
    const bags=side.included_bags ?? (side.legs[0]?.included_bags ?? globalBags);
    return `<details class="dbm-side-conditions"><summary>Classe, tarifa e bagagem deste sentido (personalizar)</summary>
      <div class="dbm-itinerary-grid">
        <label>Classe<select data-side-field="cabin">${optionsLike(cabinSelect,cabin)}</select></label>
        <label>Tarifa<input data-side-field="fare" type="text" maxlength="70" value="${esc(fare)}" placeholder="Ex.: Light, Flex, Full"></label>
        <label>Bagagem incluída<select data-side-field="included_bags">${optionsLike(bagSelect,bags)}</select></label>
      </div>
      <small>Não cria taxas nem altera o custo original. Se quiser repetir, use os botões acima.</small>
      </details>`;
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
      </div>
      ${side.status==='stops'?`<div class="dbm-itinerary-stops">${side.stops.map((stop,i)=>`<label>Parada ${i+1} • aeroporto IATA<input data-stop="${i}" value="${esc(stop)}" maxlength="3" placeholder="Ex.: BSB"></label>`).join('')}</div>`:''}
      ${sideConditions(side)}
      <details class="dbm-side-times"><summary>🕒 Horários ${side.status==='stops'?'das etapas e conexões':'do voo'} (opcionais)</summary>
        <div class="dbm-itinerary-legs">${side.legs.map((leg,i)=>legHTML(side,leg,i)).join('')}</div>
        <div class="dbm-itinerary-duration" data-duration="${esc(side.key)}"></div>
      </details>
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
    sidesBox.innerHTML = segments.length ? segments.map(sideHTML).join('') : '<p>Esta modalidade não possui uma rota com aeroportos únicos. O cálculo continua normalmente sem este complemento.</p>';
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
      const node=panel.querySelector(`[data-duration="${side.key}"]`);if(!node)return;
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
    if(['cabin','fare','included_bags'].includes(target.dataset.sideField)){side[target.dataset.sideField]=target.value;saveHidden();return true;}
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
    if(target.dataset.sideField==='fare'){side.fare=target.value;saveHidden();return;}
    const legRoot=target.closest('[data-leg]');if(legRoot&&target.dataset.field){const leg=side.legs[Number(legRoot.dataset.leg)];if(leg)leg[target.dataset.field]=target.value;totals();saveHidden();}
  });
  sidesBox.addEventListener('change', e=>{
    const target=e.target, root=target.closest('[data-side]');if(!root)return;
    const side=model.sides[root.dataset.side];if(!side)return;
    if(topologyChanged(target,side,root))return;
    const legRoot=target.closest('[data-leg]');if(legRoot&&target.dataset.field){const leg=side.legs[Number(legRoot.dataset.leg)];if(leg)leg[target.dataset.field]=target.value;totals();saveHidden();}
  });
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
