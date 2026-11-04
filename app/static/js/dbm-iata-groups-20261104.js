/* DBMILESX 04/11/2026 — filtro de aeroportos por cidade/região (códigos IATA).
   Campos com [data-iata-group] ganham, logo abaixo:
   - um seletor "Cidade/região" (NYC, RIO, SAO, LON, PAR, Portugal, ROM);
   - a segunda seleção com os aeroportos daquele grupo.
   Digitar um código de cidade (ex.: SAO) já abre os aeroportos (GRU, CGH, VCP).
   Digitar um aeroporto específico (ex.: GRU) dispensa a segunda seleção, mas
   mostra os outros aeroportos da mesma cidade para troca rápida.
   Não grava nada sozinho: só preenche o campo e dispara input/change. */
(function(){
  'use strict';
  let groups=[];
  try{groups=JSON.parse(document.getElementById('iataCityGroups')?.textContent||'[]')||[];}catch(_){groups=[];}
  if(!Array.isArray(groups)||!groups.length)return;
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const code=v=>String(v||'').toUpperCase().replace(/[^A-Z]/g,'').slice(0,3);
  const groupFor=value=>{
    const c=code(value);if(!c)return null;
    return groups.find(g=>g.code===c)||groups.find(g=>(g.airports||[]).some(a=>a.code===c))||null;
  };
  function box(input){
    let el=input.closest('label')?.querySelector(':scope > .dbm-iata-group');
    if(!el){
      el=document.createElement('div');el.className='dbm-iata-group';
      el.innerHTML=`<select class="dbm-iata-group-select" aria-label="Filtrar por cidade ou região"><option value="">Cidade/região…</option>${groups.map(g=>`<option value="${esc(g.key)}">${esc(g.code?g.code+' — '+g.name:g.name)}</option>`).join('')}</select><span class="dbm-iata-group-airports"></span>`;
      (input.closest('label')||input.parentElement).appendChild(el);
      el.querySelector('select').addEventListener('change',e=>{
        e.stopPropagation();
        const g=groups.find(item=>item.key===e.target.value);
        // Escolher a cidade preenche o código da cidade (quando existe) e abre os aeroportos.
        if(g&&g.code&&!(g.airports||[]).some(a=>a.code===code(input.value)))set(input,g.code);
        paint(input,g||null);
      });
      // mousedown + preventDefault: o campo não perde o foco antes da escolha
      // (evita que o editor redesenhe a linha e "engula" o clique).
      const pick=e=>{
        const btn=e.target.closest('[data-iata-pick]');if(!btn)return;
        e.preventDefault();e.stopPropagation();
        const value=btn.dataset.iataPick;paint(input,groupFor(value));set(input,value);
      };
      el.addEventListener('mousedown',pick);
      el.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' ')pick(e);});
    }
    return el;
  }
  function set(input,value){
    input.value=value;
    input.dispatchEvent(new Event('input',{bubbles:true}));
    input.dispatchEvent(new Event('change',{bubbles:true}));
  }
  function paint(input,group){
    const el=box(input);const current=code(input.value);
    el.querySelector('select').value=group?group.key:'';
    const list=el.querySelector('.dbm-iata-group-airports');
    // Aeroporto específico fora dos grupos (ex.: BSB, FOR): sem segunda seleção.
    el.hidden=!group&&current.length===3;
    if(!group){list.innerHTML='';el.classList.remove('is-open');return;}
    el.classList.add('is-open');
    const isCity=group.code&&current===group.code;
    list.innerHTML=(isCity?'<small>Escolha o aeroporto:</small>':'')+(group.airports||[]).map(a=>`<button type="button" class="dbm-iata-chip${a.code===current?' is-active':''}" data-iata-pick="${esc(a.code)}" title="${esc(a.name)}"><b>${esc(a.code)}</b><span>${esc(a.name)}</span></button>`).join('');
  }
  function refresh(root){
    (root||document).querySelectorAll('[data-iata-group]').forEach(input=>{
      paint(input,groupFor(input.value));
      if(input.dataset.iataGroupReady==='1')return;input.dataset.iataGroupReady='1';
      input.addEventListener('input',()=>{
        const c=code(input.value);if(!(c.length===3||!c))return;
        const g=groupFor(c);paint(input,g);
        // Código de cidade digitado: fecha a lista de sugestões para não cobrir os aeroportos.
        if(g&&g.code===c){setTimeout(()=>{const list=input.closest('.iata-search-wrapper')?.querySelector('.airport-search-results');if(list)list.hidden=true;},60);}
      });
      // Escolha feita na lista de sugestões do autocompletar também conta como alteração.
      input.addEventListener('airport-selected',()=>{paint(input,groupFor(input.value));input.dispatchEvent(new Event('change',{bubbles:true}));});
    });
  }
  window.dbmIataGroups={refresh,groupFor};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>refresh());else refresh();
})();
