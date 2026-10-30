/* Complemento do calendário de ida/volta: datas individuais com a mesma aparência.
   Não interfere no seletor unificado de ida/volta (#standardDates). */
(() => {
  'use strict';
  const root = document.querySelector('main.main-content') || document.querySelector('.main-content') || document;
  if (!document.querySelector('#quoteBaseForm, #quoteVariantForm, .wizard-grid, #optionMetadataSection, #quoteEditForm, .manual-quote-form')) return;
  const names = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho','Julho','Agosto','Setembro','Outubro','Novembro','Dezembro'];
  const weekdays = ['Seg','Ter','Qua','Qui','Sex','Sáb','Dom'];
  const pad = n => String(n).padStart(2,'0');
  const iso = (y,m,d) => `${y}-${pad(m + 1)}-${pad(d)}`;
  const today = () => {const now=new Date();return iso(now.getFullYear(), now.getMonth(), now.getDate());};
  const br = date => /^\d{4}-\d\d-\d\d$/.test(date || '') ? date.split('-').reverse().join('/') : 'Escolher data';
  let active = null;
  let visibleMonth = new Date();
  visibleMonth = new Date(visibleMonth.getFullYear(), visibleMonth.getMonth(), 1);
  const overlay = document.createElement('div');
  overlay.className = 'quote-date-overlay';
  overlay.hidden = true;
  overlay.innerHTML = `<div class="quote-date-modal" role="dialog" aria-modal="true" aria-label="Escolher data">
      <div class="quote-date-head"><strong>Selecione a data</strong><button type="button" data-close aria-label="Fechar">✕</button></div>
      <div class="quote-date-nav"><button type="button" data-prev aria-label="Mês anterior">‹</button><strong data-month></strong><button type="button" data-next aria-label="Próximo mês">›</button></div>
      <div class="quote-date-days" data-days></div>
      <div class="quote-date-footer"><button type="button" data-clear>Limpar</button><button type="button" data-close>Concluir</button></div>
    </div>`;
  document.body.append(overlay);
  const weekdaysMarkup = weekdays.map(day => `<span class="weekday">${day}</span>`).join('');
  function render() {
    if (!active) return;
    const year = visibleMonth.getFullYear();
    const month = visibleMonth.getMonth();
    overlay.querySelector('[data-month]').textContent = `${names[month]} ${year}`;
    const first = (new Date(year,month,1).getDay()+6)%7;
    const count = new Date(year, month+1,0).getDate();
    let html = weekdaysMarkup + Array(first).fill('<span></span>').join('');
    for (let d=1; d<=count; d++) {
      const date = iso(year, month, d);
      const past = active.min && date < active.min;
      html += `<button type="button" data-day="${date}" class="${date === active.value ? 'selected':''}" aria-pressed="${date===active.value}" ${past?'disabled aria-disabled="true" title="Data anterior a hoje"':''}>${d}</button>`;
    }
    overlay.querySelector('[data-days]').innerHTML = html;
    const minimum = active?.min;
    overlay.querySelector('[data-prev]').disabled = Boolean(minimum && new Date(year, month, 1) <= new Date(Number(minimum.slice(0,4)),Number(minimum.slice(5,7))-1,1));
  }
  function close() { overlay.hidden = true; active?.dataset?.triggerId && document.getElementById(active.dataset.triggerId)?.focus(); active = null; if(overlay.parentNode!==document.body)document.body.appendChild(overlay); }
  function open(input) {
    active = input;
    if (input.value && (!input.min || input.value >= input.min)) {const date = input.value.split('-').map(Number); if (date.length === 3 && date[0]) visibleMonth = new Date(date[0],date[1]-1,1);}
    else {const now=new Date();visibleMonth=new Date(now.getFullYear(), now.getMonth(),1)}
    const parentDialog=input.closest('dialog[open]');
    if(parentDialog) parentDialog.appendChild(overlay); else document.body.appendChild(overlay);
    overlay.hidden=false; render();overlay.querySelector('[data-close]').focus();
  }
  function setDate(value) {
    if (!active) return;
    if(value && active.min && value < active.min)return;
    active.value = value;
    active.dispatchEvent(new Event('input',{bubbles:true}));
    active.dispatchEvent(new Event('change',{bubbles:true}));
    const btn = active.nextElementSibling;
    if (btn?.classList.contains('quote-date-inline-trigger')) btn.textContent = `📅 ${br(value)}`;
    close();
  }
  function enhance(input) {
    if (input.dataset.dbmDateEnhanced || input.closest('#standardDates') || input.disabled) return;
    // Os filtros são históricos: precisam continuar aceitando datas passadas.
    const isFilter = input.closest('form[method="get"], .history-filter, .voos-filter, .date-filter') ||
      /^(from|to|date_from|date_to|filter_from|filter_to)$/.test(input.name||'');
    if(!isFilter) input.min = today();
    if (input.type !== 'date') return;
    input.dataset.dbmDateEnhanced='1';
    const button = document.createElement('button');
    button.type='button';
    button.className='quote-date-inline-trigger';
    button.textContent=`📅 ${br(input.value)}`;
    button.setAttribute('aria-label',`Escolher data: ${input.name || 'trecho'}`);
    const id = `dbmDateTrigger${Math.random().toString(36).slice(2)}`;
    button.id=id;
    input.dataset.triggerId=id;
    // Keep the native control available as a fallback if JavaScript is disabled.
    input.classList.add('quote-date-native-input');
    input.insertAdjacentElement('afterend',button);
    button.addEventListener('click',()=>open(input));
    input.addEventListener('change',()=>{button.textContent=`📅 ${br(input.value)}`;});
  }
  function discover() {
    root.querySelectorAll('input[type="date"]').forEach(enhance);
  }
  discover();
  const obs = new MutationObserver(discover);
  obs.observe(root,{childList:true,subtree:true});
  overlay.querySelector('[data-prev]').addEventListener('click',()=>{
    const target = new Date(visibleMonth.getFullYear(),visibleMonth.getMonth()-1,1);
    const firstAllowed = active?.min?new Date(active.min+'T12:00:00'):null;
    if(firstAllowed && target < new Date(firstAllowed.getFullYear(),firstAllowed.getMonth(),1))return;
    visibleMonth=target;render();
  });
  overlay.querySelector('[data-next]').addEventListener('click',()=>{visibleMonth = new Date(visibleMonth.getFullYear(),visibleMonth.getMonth()+1,1);render();});
  overlay.querySelector('[data-days]').addEventListener('click',e=>{const day=e.target.closest('[data-day]')?.dataset.day;if(day)setDate(day);});
  overlay.querySelector('[data-clear]').addEventListener('click',()=>setDate(''));
  overlay.querySelectorAll('[data-close]').forEach(button=>button.addEventListener('click',close));
  overlay.addEventListener('click',e=>{if(e.target===overlay)close();});
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!overlay.hidden)close();});
})();
