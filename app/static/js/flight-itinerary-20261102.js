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
  const money = value => Number(value || 0).toLocaleString('pt-BR', {style:'currency', currency:'BRL'});
  const normalizeValue = value => String(value || '').trim();
  const model = {sides:{}, charge_extra_bags: Boolean(persisted.charge_extra_bags)};
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
    <div class="dbm-itinerary-heading"><div><strong>✈️ Paradas e condições por trecho</strong><small>Opcional — funciona para voo direto ou com conexões. Não precisa preencher para calcular.</small></div><span>OPCIONAL</span></div>
    <div class="dbm-itinerary-actions">
      <button type="button" class="secondary-button small-button" data-copy="all">Aplicar dados do 1º trecho a todos</button>
      <button type="button" class="secondary-button small-button" data-copy="outbound">Copiar só na ida</button>
      <button type="button" class="secondary-button small-button" data-copy="return">Copiar só na volta</button>
      <label class="dbm-itinerary-copy-paid"><input type="checkbox" id="dbmCopyPaid"> Copiar também bagagem paga</label>
    </div>
    <div class="dbm-itinerary-sides" id="dbmItinerarySides"></div>
    <div class="dbm-itinerary-foot">
      <label><input type="checkbox" id="dbmChargeExtraBags"> Somar o CUSTO das bagagens extras ao cálculo desta opção</label>
      <small>Desmarcado por padrão para evitar cobrar duas vezes bagagens que já estão no cálculo. Valores de venda são somente referência para Editar lucro.</small>
      <div id="dbmItineraryTotals" aria-live="polite"></div>
    </div>`;
  partnerArea.insertAdjacentElement('afterend', panel);
  const sidesBox = panel.querySelector('#dbmItinerarySides');
  const charge = panel.querySelector('#dbmChargeExtraBags');
  charge.checked = model.charge_extra_bags;
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
  const globalBags = Number(form.querySelector('[name="included_bags_per_passenger"]')?.value || 0);
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
      previous.origin = segment.origin;
      previous.destination = segment.destination;
      return previous;
    }
    const side = {key:segment.key, status:'direct', stops:[], legs:[], origin:segment.origin, destination:segment.destination};
    model.sides[segment.key] = side;
    return side;
  }
  function newLeg(origin,destination,previous) {
    return {
      origin, destination, partner:previous?.partner || initialCarrier,
      operator:previous?.operator || '', cabin:previous?.cabin || globalCabin,
      fare:previous?.fare || globalFare, included_bags:previous?.included_bags ?? globalBags,
      extra_bags:previous?.extra_bags || 0, extra_weight:previous?.extra_weight || 23,
      extra_passenger:previous?.extra_passenger || '',
      extra_cost:previous?.extra_cost || 0, extra_sale:previous?.extra_sale || 0,
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
  function legHTML(side, leg, i) {
    const k=esc(side.key);
    return `<article class="dbm-itinerary-leg" data-leg="${i}">
      <div class="dbm-itinerary-leghead"><b>Trecho ${i+1} • ${esc(leg.origin)} → ${esc(leg.destination)}</b><span>Opções independentes</span></div>
      <div class="dbm-itinerary-grid">
      <label>Companhia parceira<input data-field="partner" list="dbmItineraryPartners" value="${esc(leg.partner)}" placeholder="Companhia parceira opcional"></label>
      <label>Operado por<input data-field="operator" list="dbmItineraryPartners" value="${esc(leg.operator)}" placeholder="Outra companhia, se houver"></label>
      <label>Classe<select data-field="cabin">${classOptions(leg.cabin)}</select></label>
      <label>Tarifa<input data-field="fare" value="${esc(leg.fare)}" maxlength="70" placeholder="Light, Flex, etc."></label>
      <label>Malas despachadas incluídas<select data-field="included_bags">${Array.from({length:6},(_,n)=>`<option ${n===Number(leg.included_bags)?'selected':''} value="${n}">${n}</option>`).join('')}</select></label>
      <label>Malas extras pagas<select data-field="extra_bags">${Array.from({length:6},(_,n)=>`<option ${n===Number(leg.extra_bags)?'selected':''} value="${n}">${n}</option>`).join('')}</select></label>
      <label>Passageiro da bagagem extra (opcional)<input data-field="extra_passenger" value="${esc(leg.extra_passenger||'')}" maxlength="100" placeholder="Nome / identificação"></label>
      <label>Peso por mala extra (kg)<input type="number" data-field="extra_weight" min="0" max="50" value="${Number(leg.extra_weight)||23}"></label>
      <label>Custo por mala extra (R$)<input type="number" data-field="extra_cost" min="0" max="1000000" step="0.01" value="${Number(leg.extra_cost)||0}"></label>
      <label>Venda por mala extra (R$)<input type="number" data-field="extra_sale" min="0" max="1000000" step="0.01" value="${Number(leg.extra_sale)||0}"></label>
      </div>
      <details class="dbm-itinerary-timing"><summary>🕒 Horários e fuso desta etapa (opcionais)</summary>
        <div class="dbm-itinerary-grid">
          <label>Saída — ${esc(leg.origin)}<input type="datetime-local" data-field="departure" value="${esc(leg.departure)}"></label>
          <label>Fuso da saída<select data-field="origin_tz">${zoneOptions(leg.origin_tz)}</select></label>
          <label>Chegada — ${esc(leg.destination)}<input type="datetime-local" data-field="arrival" value="${esc(leg.arrival)}"></label>
          <label>Fuso da chegada<select data-field="destination_tz">${zoneOptions(leg.destination_tz)}</select></label>
        </div>
      </details>
    </article>`;
  }
  function sideHTML(segment){
    const side=getSide(segment);
    const label=side.key==='return'?'VOLTA':side.key==='outbound'||side.key==='one_way'?'IDA':side.key.replace('_',' ').toUpperCase();
    const count=side.stops.length;
    return `<section class="dbm-itinerary-side" data-side="${esc(side.key)}">
      <div class="dbm-itinerary-sidehead"><b>🛫 ${label} • ${esc(side.origin)} → ${esc(side.destination)}</b><small>Cada sentido é independente</small></div>
      <div class="dbm-itinerary-grid">
        <label>Status do voo<select data-side-field="status"><option value="direct" ${side.status!=='stops'?'selected':''}>Direto (sem parada)</option><option value="stops" ${side.status==='stops'?'selected':''}>Com parada(s)</option></select></label>
        <label ${side.status==='stops'?'':'hidden'} data-stop-count-wrap>Quantidade de paradas<select data-side-field="stop_count">${Array.from({length:4},(_,i)=>`<option value="${i+1}" ${count===i+1?'selected':''}>${i+1}</option>`).join('')}</select></label>
      </div>
      ${side.status==='stops'?`<div class="dbm-itinerary-stops">${side.stops.map((stop,i)=>`<label>${i+1}ª parada — aeroporto IATA<input data-stop="${i}" value="${esc(stop)}" maxlength="3" placeholder="Ex.: BSB" pattern="[A-Za-z]{3}" required></label>`).join('')}</div>`:''}
      <div class="dbm-itinerary-legs">${side.legs.map((leg,i)=>legHTML(side,leg,i)).join('')}</div>
      <div class="dbm-itinerary-duration" data-duration="${esc(side.key)}"></div>
    </section>`;
  }
  function render(){
    const segments=activeSegments();
    segments.forEach(segment => {
      const side=getSide(segment);
      if(side.status==='stops' && !side.stops.length) side.stops=[''];
      rebuildLegs(side);
    });
    sidesBox.innerHTML = segments.length ? segments.map(sideHTML).join('') : '<p>Esta modalidade não possui uma rota com aeroportos únicos. O cálculo continua normalmente sem este complemento.</p>';
    const oldGrid=partnerArea.querySelector('.partner-segment-grid');
    if(oldGrid) oldGrid.hidden=segments.length>0;
    totals();
    saveHidden();
  }
  function offsetMinutes(tz) {if(!/^[+-]\d\d:\d\d$/.test(tz||''))return null;return (tz[0]==='+'?1:-1)*(Number(tz.slice(1,3))*60+Number(tz.slice(4,6)));}
  function utc(date,tz){if(!date||offsetMinutes(tz)===null)return null;const ms=Date.parse(date+':00Z');return Number.isFinite(ms)?ms-offsetMinutes(tz)*60000:null;}
  const fmtMinutes=min=>`${Math.floor(min/60)}h ${String(min%60).padStart(2,'0')}min`;
  function totals(){
    let cost=0, sale=0;
    activeSegments().forEach(segment=>{
      const side=model.sides[segment.key];if(!side)return;
      const legs=side.legs||[];
      legs.forEach(leg=>{const qty=Math.max(0,Number(leg.extra_bags)||0);cost+=qty*(Number(leg.extra_cost)||0);sale+=qty*(Number(leg.extra_sale)||0);});
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
    panel.querySelector('#dbmItineraryTotals').textContent=`Bagagens adicionais: custo ${money(cost)} • venda de referência ${money(sale)}${charge.checked?' • custo incluído no cálculo':' • não somadas automaticamente'}`;
  }
  function saveHidden(){
    model.charge_extra_bags=charge.checked;
    hidden.value=JSON.stringify({version:1,sides:activeSegments().map(seg=>model.sides[seg.key]).filter(Boolean),charge_extra_bags:model.charge_extra_bags});
  }
  function topologyChanged(target,side,root){
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
      if(validIata(side.stops[idx])){
        rebuildLegs(side);
        const wasFocused=document.activeElement===target;
        // Draw dependent routes only on change/blur; never steal focus on typing.
        if(!wasFocused || target.type==='text') render();
      }else saveHidden();
      return true;
    }
    return false;
  }
  sidesBox.addEventListener('input', e=>{
    const target=e.target;const root=target.closest('[data-side]');if(!root)return;
    const side=model.sides[root.dataset.side];if(!side)return;
    if(target.hasAttribute('data-stop')){side.stops[Number(target.dataset.stop)]=target.value.trim().toUpperCase();saveHidden();return;}
    const legRoot=target.closest('[data-leg]');if(legRoot&&target.dataset.field){const leg=side.legs[Number(legRoot.dataset.leg)];if(leg)leg[target.dataset.field]=target.value;totals();saveHidden();}
  });
  sidesBox.addEventListener('change', e=>{
    const target=e.target, root=target.closest('[data-side]');if(!root)return;
    const side=model.sides[root.dataset.side];if(!side)return;
    if(topologyChanged(target,side,root))return;
    const legRoot=target.closest('[data-leg]');if(legRoot&&target.dataset.field){const leg=side.legs[Number(legRoot.dataset.leg)];if(leg)leg[target.dataset.field]=target.value;totals();saveHidden();}
  });
  charge.addEventListener('change',()=>{totals();saveHidden();});
  panel.querySelectorAll('[data-copy]').forEach(button=>button.addEventListener('click',()=>{
    const target=button.dataset.copy;const sides=activeSegments().map(seg=>model.sides[seg.key]).filter(Boolean);
    const source=(target==='return'?sides.find(side=>side.key==='return'):sides.find(side=>side.key!=='return'))||sides[0];
    if(!source?.legs.length)return;
    const recipients=sides.flatMap(side=>side.legs.map((leg,i)=>({side,leg,i})))
      .filter(item=>target==='all'||(target==='return'?item.side.key==='return':item.side.key!=='return'))
      .filter(item=>!(item.side===source && item.i===0));
    if(!recipients.length)return;
    if(!confirm(`Copiar as configurações do 1º trecho para ${recipients.length} trecho(s)? Os dados existentes de parceria, classe, tarifa e bagagem incluída serão substituídos. Horários e rotas serão mantidos.`))return;
    const first=source.legs[0];const copyPaid=panel.querySelector('#dbmCopyPaid').checked;
    recipients.forEach(({leg})=>{
      ['partner','operator','cabin','fare','included_bags'].forEach(key=>{leg[key]=first[key];});
      if(copyPaid)['extra_bags','extra_weight','extra_cost','extra_sale','extra_passenger'].forEach(key=>{leg[key]=first[key];});
    });
    render();
  }));
  document.addEventListener('calculation-scope-will-change',()=>saveHidden());
  document.addEventListener('calculation-scope-changed',event=>{currentKey=event.detail?.to||selectedScope?.value||currentKey;render();});
  form.addEventListener('submit',e=>{
    for(const side of activeSegments().map(seg=>model.sides[seg.key]).filter(Boolean)){
      if(side.status==='stops' && side.stops.some(stop=>!validIata(stop))){
        e.preventDefault();panel.scrollIntoView({behavior:'smooth',block:'center'});
        alert('Informe os três caracteres IATA de todas as paradas, ou escolha Voo direto.');return;
      }
    }
    saveHidden();
  },true);
  render();
})();
