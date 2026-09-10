(() => {
  const AIRPORTS = [{"code":"AAX","name":"Araxá"},{"code":"ADD","name":"Adis Abeba"},{"code":"AEP","name":"Buenos Aires/Aeroparque"},{"code":"AFL","name":"Alta Floresta"},{"code":"AJU","name":"Aracaju"},{"code":"AKL","name":"Auckland"},{"code":"AMS","name":"Amsterdã/Schiphol"},{"code":"AQA","name":"Araraquara"},{"code":"ARN","name":"Estocolmo/Arlanda"},{"code":"ARU","name":"Araçatuba"},{"code":"ASU","name":"Assunção"},{"code":"ATH","name":"Atenas"},{"code":"ATL","name":"Atlanta/Hartsfield-Jackson"},{"code":"ATM","name":"Altamira"},{"code":"AUA","name":"Aruba"},{"code":"AUH","name":"Abu Dhabi"},{"code":"BCN","name":"Barcelona/El Prat"},{"code":"BEL","name":"Belém"},{"code":"BGC","name":"Bragança"},{"code":"BGZ","name":"Braga"},{"code":"BKK","name":"Bangkok/Suvarnabhumi"},{"code":"BOG","name":"Bogotá/El Dorado"},{"code":"BOM","name":"Mumbai"},{"code":"BOS","name":"Boston/Logan"},{"code":"BPG","name":"Barra do Garças"},{"code":"BPS","name":"Porto Seguro"},{"code":"BRA","name":"Barreiras"},{"code":"BRU","name":"Bruxelas"},{"code":"BSB","name":"Brasília"},{"code":"BUD","name":"Budapeste"},{"code":"BUE","name":"Buenos Aires (todos)"},{"code":"BVB","name":"Boa Vista"},{"code":"BVH","name":"Vilhena"},{"code":"BYJ","name":"Beja/Alentejo"},{"code":"BYO","name":"Bonito"},{"code":"CAC","name":"Cascavel"},{"code":"CAI","name":"Cairo"},{"code":"CAN","name":"Guangzhou"},{"code":"CAT","name":"Cascais/Tires"},{"code":"CAU","name":"Caruaru"},{"code":"CBP","name":"Coimbra/Bissaya Barreto"},{"code":"CDG","name":"Paris/Charles de Gaulle"},{"code":"CGB","name":"Cuiabá"},{"code":"CGH","name":"São Paulo/Congonhas"},{"code":"CGR","name":"Campo Grande"},{"code":"CHV","name":"Chaves"},{"code":"CKS","name":"Carajás/Parauapebas"},{"code":"CLT","name":"Charlotte"},{"code":"CLV","name":"Caldas Novas"},{"code":"CMG","name":"Corumbá"},{"code":"CMN","name":"Casablanca"},{"code":"CNF","name":"Belo Horizonte/Confins"},{"code":"COR","name":"Córdoba"},{"code":"COV","name":"Covilhã"},{"code":"CPH","name":"Copenhague"},{"code":"CPT","name":"Cidade do Cabo"},{"code":"CPV","name":"Campina Grande"},{"code":"CTG","name":"Cartagena"},{"code":"CUN","name":"Cancún"},{"code":"CUR","name":"Curaçao"},{"code":"CVU","name":"Corvo"},{"code":"CWB","name":"Curitiba"},{"code":"CXJ","name":"Caxias do Sul"},{"code":"CZS","name":"Cruzeiro do Sul"},{"code":"DCA","name":"Washington/Reagan"},{"code":"DEL","name":"Nova Délhi"},{"code":"DFW","name":"Dallas/Fort Worth"},{"code":"DIQ","name":"Divinópolis"},{"code":"DOH","name":"Doha/Hamad"},{"code":"DOU","name":"Dourados"},{"code":"DUB","name":"Dublin"},{"code":"DXB","name":"Dubai"},{"code":"EDI","name":"Edimburgo"},{"code":"EWR","name":"Nova York/Newark"},{"code":"EZE","name":"Buenos Aires/Ezeiza"},{"code":"FAO","name":"Faro/Algarve"},{"code":"FCO","name":"Roma/Fiumicino"},{"code":"FEN","name":"Fernando de Noronha"},{"code":"FLN","name":"Florianópolis"},{"code":"FLR","name":"Florença"},{"code":"FLW","name":"Flores"},{"code":"FNC","name":"Madeira/Cristiano Ronaldo"},{"code":"FOR","name":"Fortaleza"},{"code":"FRA","name":"Frankfurt"},{"code":"GEL","name":"Santo Ângelo"},{"code":"GIG","name":"Rio de Janeiro/Galeão"},{"code":"GNM","name":"Guanambi"},{"code":"GRU","name":"São Paulo/Guarulhos"},{"code":"GRW","name":"Graciosa"},{"code":"GVA","name":"Genebra"},{"code":"GVR","name":"Governador Valadares"},{"code":"GYE","name":"Guayaquil"},{"code":"GYN","name":"Goiânia"},{"code":"HAV","name":"Havana"},{"code":"HEL","name":"Helsinque"},{"code":"HKG","name":"Hong Kong"},{"code":"HND","name":"Tóquio/Haneda"},{"code":"HOR","name":"Horta"},{"code":"IAD","name":"Washington/Dulles"},{"code":"IAH","name":"Houston/George Bush"},{"code":"ICN","name":"Seul/Incheon"},{"code":"IGU","name":"Foz do Iguaçu"},{"code":"IMP","name":"Imperatriz"},{"code":"IOS","name":"Ilhéus"},{"code":"IPN","name":"Ipatinga"},{"code":"IST","name":"Istambul"},{"code":"ITB","name":"Itaituba"},{"code":"IZA","name":"Juiz de Fora/Zona da Mata"},{"code":"JDO","name":"Juazeiro do Norte"},{"code":"JFK","name":"Nova York/JFK"},{"code":"JJD","name":"Cruz/Jericoacoara"},{"code":"JJG","name":"Jaguaruna"},{"code":"JNB","name":"Joanesburgo"},{"code":"JOI","name":"Joinville"},{"code":"JPA","name":"João Pessoa"},{"code":"JPR","name":"Ji-Paraná"},{"code":"JTC","name":"Bauru/Arealva"},{"code":"KEF","name":"Reiquiavique/Keflavík"},{"code":"KUL","name":"Kuala Lumpur"},{"code":"LAS","name":"Las Vegas"},{"code":"LAX","name":"Los Angeles"},{"code":"LBR","name":"Lábrea"},{"code":"LDB","name":"Londrina"},{"code":"LEC","name":"Lençóis"},{"code":"LGA","name":"Nova York/LaGuardia"},{"code":"LGW","name":"Londres/Gatwick"},{"code":"LHR","name":"Londres/Heathrow"},{"code":"LIM","name":"Lima/Jorge Chávez"},{"code":"LIS","name":"Lisboa/Humberto Delgado"},{"code":"MAB","name":"Marabá"},{"code":"MAD","name":"Madri/Barajas"},{"code":"MAN","name":"Manchester"},{"code":"MAO","name":"Manaus"},{"code":"MBZ","name":"Maués"},{"code":"MCO","name":"Orlando"},{"code":"MCP","name":"Macapá"},{"code":"MCZ","name":"Maceió"},{"code":"MDE","name":"Medellín"},{"code":"MDZ","name":"Mendoza"},{"code":"MEL","name":"Melbourne"},{"code":"MEU","name":"Monte Dourado"},{"code":"MEX","name":"Cidade do México"},{"code":"MGF","name":"Maringá"},{"code":"MIA","name":"Miami"},{"code":"MII","name":"Marília"},{"code":"MNL","name":"Manila"},{"code":"MNX","name":"Manicoré"},{"code":"MOC","name":"Montes Claros"},{"code":"MUC","name":"Munique"},{"code":"MVD","name":"Montevidéu"},{"code":"MXP","name":"Milão/Malpensa"},{"code":"MXQ","name":"Morro de São Paulo"},{"code":"NAP","name":"Nápoles"},{"code":"NAS","name":"Nassau"},{"code":"NAT","name":"Natal"},{"code":"NBO","name":"Nairóbi"},{"code":"NRT","name":"Tóquio/Narita"},{"code":"NVT","name":"Navegantes"},{"code":"OAL","name":"Cacoal"},{"code":"OPO","name":"Porto/Francisco Sá Carneiro"},{"code":"OPS","name":"Sinop"},{"code":"ORY","name":"Paris/Orly"},{"code":"OSL","name":"Oslo"},{"code":"PDL","name":"Ponta Delgada/João Paulo II"},{"code":"PEK","name":"Pequim/Capital"},{"code":"PER","name":"Perth"},{"code":"PET","name":"Pelotas"},{"code":"PFB","name":"Passo Fundo"},{"code":"PHB","name":"Parnaíba"},{"code":"PIN","name":"Parintins"},{"code":"PIX","name":"Pico"},{"code":"PMG","name":"Ponta Porã"},{"code":"PMW","name":"Palmas"},{"code":"PNZ","name":"Petrolina"},{"code":"POA","name":"Porto Alegre"},{"code":"POJ","name":"Patos de Minas"},{"code":"PPB","name":"Presidente Prudente"},{"code":"PRG","name":"Praga"},{"code":"PRM","name":"Portimão"},{"code":"PTO","name":"Pato Branco"},{"code":"PTY","name":"Cidade do Panamá/Tocumen"},{"code":"PUJ","name":"Punta Cana"},{"code":"PVG","name":"Xangai/Pudong"},{"code":"PVH","name":"Porto Velho"},{"code":"PXO","name":"Porto Santo"},{"code":"QLR","name":"Leiria/Gândara"},{"code":"QPS","name":"Ponte de Sor"},{"code":"RAK","name":"Marrakech"},{"code":"RAO","name":"Ribeirão Preto"},{"code":"RBB","name":"Borba"},{"code":"RBR","name":"Rio Branco"},{"code":"REC","name":"Recife"},{"code":"RIA","name":"Santa Maria"},{"code":"ROO","name":"Rondonópolis"},{"code":"RRJ","name":"Rio de Janeiro/Jacarepaguá"},{"code":"SAW","name":"Istambul/Sabiha Gökçen"},{"code":"SCL","name":"Santiago do Chile"},{"code":"SDQ","name":"Santo Domingo"},{"code":"SDU","name":"Rio de Janeiro/Santos Dumont"},{"code":"SET","name":"Serra Talhada"},{"code":"SFO","name":"São Francisco"},{"code":"SIE","name":"Sines"},{"code":"SIN","name":"Singapura/Changi"},{"code":"SJK","name":"São José dos Campos"},{"code":"SJL","name":"São Gabriel da Cachoeira"},{"code":"SJP","name":"São José do Rio Preto"},{"code":"SJZ","name":"São Jorge"},{"code":"SLZ","name":"São Luís"},{"code":"SMA","name":"Santa Maria"},{"code":"SMT","name":"Sorriso"},{"code":"SSA","name":"Salvador"},{"code":"STM","name":"Santarém"},{"code":"SVO","name":"Moscou/Sheremetyevo"},{"code":"SYD","name":"Sydney"},{"code":"TBT","name":"Tabatinga"},{"code":"TER","name":"Terceira/Lajes"},{"code":"TFF","name":"Tefé"},{"code":"THE","name":"Teresina"},{"code":"TLV","name":"Tel Aviv/Ben Gurion"},{"code":"UBA","name":"Uberaba"},{"code":"UDI","name":"Uberlândia"},{"code":"UIO","name":"Quito"},{"code":"UMU","name":"Umuarama"},{"code":"UNA","name":"Una/Comandatuba"},{"code":"URG","name":"Uruguaiana"},{"code":"VAG","name":"Varginha"},{"code":"VCE","name":"Veneza"},{"code":"VCP","name":"Campinas/Viracopos"},{"code":"VDC","name":"Vitória da Conquista"},{"code":"VIE","name":"Viena"},{"code":"VIX","name":"Vitória"},{"code":"VRL","name":"Vila Real"},{"code":"VSE","name":"Viseu/Gonçalves Lobato"},{"code":"WAW","name":"Varsóvia"},{"code":"XAP","name":"Chapecó"},{"code":"YUL","name":"Montreal/Trudeau"},{"code":"YVR","name":"Vancouver"},{"code":"YYZ","name":"Toronto/Pearson"},{"code":"ZRH","name":"Zurique"}];
  const BY_CODE = new Map(AIRPORTS.map(item => [item.code, item]));
  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
  const fold = value => String(value || '').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toUpperCase().trim();
  const normalizeCode = value => String(value || '').toUpperCase().replace(/[^A-Z]/g,'').slice(0,3);
  const tokenParts = value => String(value || '').split(/[,;\/|]+/).map(v=>v.trim()).filter(Boolean);
  const lookupToken = token => {
    const raw=String(token||'').trim();
    const code=normalizeCode(raw);
    if(code.length===3 && BY_CODE.has(code)) return BY_CODE.get(code);
    const exact=AIRPORTS.find(a=>fold(a.name)===fold(raw));
    return exact || null;
  };
  const searchAirports = query => {
    const q=fold(query);
    if (!q) return AIRPORTS.slice(0,30);
    return AIRPORTS.filter(item => item.code.startsWith(q) || fold(item.name).includes(q)).slice(0,30);
  };
  function ensureContainer(input, multi=false) {
    let wrapper=input.closest('.iata-search-wrapper');
    if(!wrapper){wrapper=document.createElement('span');wrapper.className='iata-search-wrapper';input.parentNode.insertBefore(wrapper,input);wrapper.appendChild(input);}
    if(multi) wrapper.classList.add('multi-iata-shell');
    let box=wrapper.querySelector('.airport-search-results');
    if(!box){box=document.createElement('div');box.className='airport-search-results';box.hidden=true;wrapper.appendChild(box);}
    let chips=wrapper.querySelector('.multi-iata-chips');
    if(multi&&!chips){chips=document.createElement('div');chips.className='multi-iata-chips';wrapper.appendChild(chips);}
    return {wrapper,box,chips};
  }
  function hint(input){return input.dataset.airportHint?document.getElementById(input.dataset.airportHint):(input.closest('label')||input.parentElement)?.querySelector('.iata-selected-hint,.field-hint-city');}
  function selectAirport(a,input,box){
    input.value=a.code;
    input.dataset.selectedAirportCode=a.code;
    input.dataset.selectedAirportName=a.name||'';
    input.dataset.manualIata=a.manual?'1':'0';
    const h=hint(input); if(h) h.textContent=a.manual?`${a.code} - IATA informado manualmente`:`${a.code} - ${a.name||''}`;
    input.setCustomValidity(''); box.hidden=true;
    input.dispatchEvent(new CustomEvent('airport-selected',{bubbles:true,detail:{airport:a}}));
  }
  function renderSingle(items,input,box,query){
    const q=normalizeCode(query); const allowManual=q.length===3&&!BY_CODE.has(q);
    let html=items.map(a=>`<button type="button" class="airport-search-item" data-code="${escapeHtml(a.code)}" data-name="${escapeHtml(a.name)}"><strong>${escapeHtml(a.code)}</strong><span>${escapeHtml(a.name)}</span></button>`).join('');
    if(allowManual) html += `<button type="button" class="airport-search-item airport-search-manual" data-code="${escapeHtml(q)}" data-name="" data-manual="1"><strong>${escapeHtml(q)}</strong><span>Usar como código IATA manual</span></button>`;
    if(!html) html='<div class="airport-search-empty">Nenhum aeroporto cadastrado. Complete 3 letras para usar um IATA manual.</div>';
    box.innerHTML=html; box.querySelectorAll('button').forEach(b=>b.addEventListener('mousedown',e=>{e.preventDefault();selectAirport({code:b.dataset.code,name:b.dataset.name,manual:b.dataset.manual==='1'},input,box);})); box.hidden=false;
  }
  function validateSingle(input,show=false){
    const v=normalizeCode(input.value); input.value=v;
    if(!v){input.setCustomValidity('');return true;}
    if(v.length!==3){input.setCustomValidity('Digite exatamente as 3 letras do código IATA.');if(show)input.reportValidity();return false;}
    const airport=BY_CODE.get(v); input.dataset.selectedAirportCode=v; input.dataset.selectedAirportName=airport?.name||''; input.dataset.manualIata=airport?'0':'1';
    const h=hint(input); if(h) h.textContent=airport?`${v} - ${airport.name||''}`:`${v} - IATA informado manualmente`;
    input.setCustomValidity(''); return true;
  }
  function initSingle(input){
    if(!input||input.dataset.airportSearchReady==='1')return; input.dataset.airportSearchReady='1'; input.autocomplete='off'; input.maxLength=3;
    const {wrapper,box}=ensureContainer(input,false); let timer=0;
    const run=()=>{const q=input.value;renderSingle(searchAirports(q),input,box,q);if(normalizeCode(q).length===3)validateSingle(input,false);};
    input.addEventListener('focus',run); input.addEventListener('input',()=>{input.value=normalizeCode(input.value);input.setCustomValidity('');clearTimeout(timer);timer=setTimeout(run,25);});
    input.addEventListener('keydown',e=>{if(e.key==='Enter'&&!box.hidden){const first=box.querySelector('.airport-search-item');if(first){e.preventDefault();selectAirport({code:first.dataset.code,name:first.dataset.name,manual:first.dataset.manual==='1'},input,box);}}});
    input.addEventListener('blur',()=>setTimeout(()=>{box.hidden=true;validateSingle(input,false);},180)); document.addEventListener('click',e=>{if(!wrapper.contains(e.target))box.hidden=true;}); if(input.value)validateSingle(input,false);
  }
  function currentMultiQuery(input){const value=String(input.value||'');const part=value.split(/[,;\/|]/).pop()||'';return part.trim();}
  function committedMultiTokens(input){const value=String(input.value||'');const pieces=value.split(/[,;\/|]/);pieces.pop();return pieces.map(v=>v.trim()).filter(Boolean);}
  function canonicalToken(raw){
    const airport=lookupToken(raw); if(airport)return {code:airport.code,name:airport.name,manual:false};
    const code=normalizeCode(raw); if(code.length===3)return {code,name:'',manual:!BY_CODE.has(code)};
    return null;
  }
  function multiTokens(input, includeCurrent=true){
    const raw=tokenParts(input.value); if(!includeCurrent && raw.length) raw.pop();
    return raw.map(canonicalToken).filter(Boolean);
  }
  function renderMultiChips(input,chips){
    if(!chips)return; const raw=tokenParts(input.value); chips.innerHTML='';
    raw.forEach((token,index)=>{const info=canonicalToken(token);const chip=document.createElement('span');chip.className='iata-chip '+(info?(info.manual?'manual':'known'):'pending');
      chip.innerHTML=info?`<b>${escapeHtml(info.code)}</b><span>${escapeHtml(info.name || 'IATA manual')}</span><button type="button" aria-label="Remover">×</button>`:`<b>${escapeHtml(token)}</b><span>continue digitando</span>`;
      chip.querySelector('button')?.addEventListener('click',()=>{const values=tokenParts(input.value);values.splice(index,1);input.value=values.join(', ');renderMultiChips(input,chips);input.dispatchEvent(new Event('input',{bubbles:true}));});chips.appendChild(chip);});
  }
  function setMultiAirport(input,box,chips,airport){
    const committed=committedMultiTokens(input).map(canonicalToken).filter(Boolean).map(i=>i.code);
    if(!committed.includes(airport.code))committed.push(airport.code); input.value=committed.join(', ') + ', '; input.setCustomValidity(''); renderMultiChips(input,chips); box.hidden=true; input.focus();
    input.dispatchEvent(new CustomEvent('airport-selected',{bubbles:true,detail:{airport,multiple:true}})); input.dispatchEvent(new Event('input',{bubbles:true}));
  }
  function renderMulti(items,input,box,chips,query){
    const code=normalizeCode(query);const allowManual=code.length===3&&!BY_CODE.has(code);
    let html=items.map(a=>`<button type="button" class="airport-search-item" data-code="${escapeHtml(a.code)}" data-name="${escapeHtml(a.name)}"><strong>${escapeHtml(a.code)}</strong><span>${escapeHtml(a.name)}</span></button>`).join('');
    if(allowManual)html+=`<button type="button" class="airport-search-item airport-search-manual" data-code="${escapeHtml(code)}" data-name="" data-manual="1"><strong>${escapeHtml(code)}</strong><span>Adicionar IATA manual</span></button>`;
    if(!html)html='<div class="airport-search-empty">Digite uma cidade/nome de aeroporto ou complete 3 letras para adicionar manualmente.</div>';
    box.innerHTML=html;box.querySelectorAll('button').forEach(b=>b.addEventListener('mousedown',e=>{e.preventDefault();setMultiAirport(input,box,chips,{code:b.dataset.code,name:b.dataset.name,manual:b.dataset.manual==='1'});}));box.hidden=false;
  }
  function normalizeMulti(input,show=false){
    const raw=tokenParts(input.value); const out=[]; let bad='';
    raw.forEach(token=>{const info=canonicalToken(token);if(info){if(!out.includes(info.code))out.push(info.code);}else if(token.trim()){bad=token;}});
    if(bad){input.setCustomValidity(`“${bad}” não foi reconhecido. Se for um IATA manual, informe exatamente 3 letras.`);if(show)input.reportValidity();return false;}
    input.value=out.join(', ');input.setCustomValidity('');const chips=input.closest('.iata-search-wrapper')?.querySelector('.multi-iata-chips');renderMultiChips(input,chips);return true;
  }
  function initMulti(input){
    if(!input||input.dataset.multiAirportSearchReady==='1')return; input.dataset.multiAirportSearchReady='1';input.autocomplete='off';
    const {wrapper,box,chips}=ensureContainer(input,true);let timer=0;
    const run=()=>{const q=currentMultiQuery(input);renderMulti(searchAirports(q),input,box,chips,q);};
    input.addEventListener('focus',run); input.addEventListener('input',()=>{input.setCustomValidity('');renderMultiChips(input,chips);clearTimeout(timer);timer=setTimeout(run,45);});
    input.addEventListener('keydown',e=>{if((e.key==='Enter'||e.key==='Tab')&&!box.hidden){const first=box.querySelector('.airport-search-item');if(first){e.preventDefault();setMultiAirport(input,box,chips,{code:first.dataset.code,name:first.dataset.name,manual:first.dataset.manual==='1'});}}});
    input.addEventListener('blur',()=>setTimeout(()=>{box.hidden=true;normalizeMulti(input,false);},180));document.addEventListener('click',e=>{if(!wrapper.contains(e.target))box.hidden=true;});renderMultiChips(input,chips);
  }
  function validateForm(form){
    const singleBad=Array.from(form.querySelectorAll('.iata-search:not(.multi-iata-input)')).find(f=>!validateSingle(f)); if(singleBad){singleBad.reportValidity();singleBad.focus();return false;}
    const multiBad=Array.from(form.querySelectorAll('.multi-iata-input:not(:disabled)')).find(f=>!normalizeMulti(f)); if(multiBad){multiBad.reportValidity();multiBad.focus();return false;} return true;
  }
  function bindForm(form){if(!form||form.dataset.iataValidationReady==='1')return;form.dataset.iataValidationReady='1';form.addEventListener('submit',e=>{if(!validateForm(form))e.preventDefault();});}
  const scan=(r=document)=>{r.querySelectorAll?.('.iata-search').forEach(initSingle);r.querySelectorAll?.('.multi-iata-input').forEach(initMulti);r.querySelectorAll?.('form').forEach(bindForm);};
  window.initAirportSearch=initSingle;window.initMultiAirportSearch=initMulti;window.validateAirportInput=validateSingle;window.validateMultiAirportInput=normalizeMulti;window.DBMILESX_AIRPORTS=AIRPORTS;
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>scan());else scan();
  new MutationObserver(ms=>ms.forEach(m=>m.addedNodes.forEach(n=>{if(n instanceof Element){if(n.matches?.('.iata-search'))initSingle(n);if(n.matches?.('.multi-iata-input'))initMulti(n);scan(n);}}))).observe(document.documentElement,{childList:true,subtree:true});
})();
