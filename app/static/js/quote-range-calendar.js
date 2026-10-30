(() => {
  const form = document.querySelector('#quoteBaseForm, #quoteVariantForm');
  if (!form) return;
  const dates = form.querySelector('#standardDates');
  const departure = dates?.querySelector('input[name="departure_date"]');
  const returning = dates?.querySelector('input[name="return_date"]');
  if (!departure || !returning) return;
  const selectedTrip = () => form.querySelector('input[name="travel_type"]:checked')?.value || 'round_trip';
  const names = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho','Julho','Agosto','Setembro','Outubro','Novembro','Dezembro'];
  const weekdays = ['Seg','Ter','Qua','Qui','Sex','Sáb','Dom'];
  const today = () => {const d=new Date(); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;};
  departure.min=today();returning.min=today();
  const trigger = document.createElement('button');
  trigger.type = 'button'; trigger.className = 'secondary-button range-trigger';
  trigger.setAttribute('aria-haspopup','dialog');
  const display = () => {trigger.textContent = departure.value ? ('📅 Ida: '+departure.value.split('-').reverse().join('/') + (selectedTrip()==='round_trip' && returning.value ? '  •  Volta: '+returning.value.split('-').reverse().join('/') : '')) : '📅 Selecionar datas da viagem';};
  dates.parentElement.insertBefore(trigger,dates);
  dates.classList.add("range-original-hidden"); // evita calendário nativo duplicado
  display();
  const overlay=document.createElement('div'); overlay.className='range-overlay';overlay.hidden=true;
  overlay.innerHTML=`<section class="range-dialog" role="dialog" aria-modal="true" aria-label="Datas da viagem"><header><strong>Selecione as datas</strong><button type="button" class="range-close" aria-label="Fechar">×</button></header><div class="range-nav"><button type="button" class="range-prev">‹ Anterior</button><strong class="range-heading"></strong><button type="button" class="range-next">Próximo ›</button></div><div class="range-months"></div><footer><div class="range-summary"></div><button type="button" class="range-done">Continuar</button></footer></section>`;
  document.body.append(overlay);
  const months = overlay.querySelector('.range-months');
  let monthView = new Date(); monthView = new Date(Date.UTC(monthView.getUTCFullYear(), monthView.getUTCMonth(),1));
  let phase = 'departure';
  function iso(d){return d.toISOString().slice(0,10);}
  function monthHtml(date){
    const y=date.getUTCFullYear(), m=date.getUTCMonth();const count=new Date(Date.UTC(y,m+1,0)).getUTCDate();
    const offset=(new Date(Date.UTC(y,m,1)).getUTCDay()+6)%7;
    let markup=`<div class="range-month"><h3>${names[m]} ${y}</h3><div class="range-days">`;
    weekdays.forEach(x=>{markup+=`<span class="range-weekday">${x}</span>`});
    for(let n=0;n<offset;n++)markup+='<span></span>';
    for(let n=1;n<=count;n++){
      const value=iso(new Date(Date.UTC(y,m,n)));
      const first=departure.value, last=returning.value;
      const inRange=selectedTrip()==='round_trip' && first && last && value>=first && value<=last;
      const disabled=value<today();
      markup+=`<button type="button" data-day="${value}" class="${value===first||value===last?'range-selected':''} ${inRange?'range-between':''}" aria-label="${n} de ${names[m]}" ${disabled?'disabled aria-disabled="true"':''}>${n}</button>`;
    }
    return markup+'</div></div>';
  }
  function render(){
    overlay.querySelector('.range-heading').textContent=selectedTrip()==='round_trip'?'Ida e volta':'Data de ida';
    const second=new Date(Date.UTC(monthView.getUTCFullYear(),monthView.getUTCMonth()+1,1));
    months.innerHTML=monthHtml(monthView)+monthHtml(second);
    const now=new Date();const firstMonth=new Date(Date.UTC(now.getFullYear(),now.getMonth(),1));
    overlay.querySelector('.range-prev').disabled = monthView <= firstMonth;
    overlay.querySelector('.range-summary').textContent=`Ida: ${departure.value||'Selecione'}${selectedTrip()==='round_trip'?' • Volta: '+(returning.value||'Selecione'):''}`;
    display();
  }
  const open=()=>{
    if (departure.value && departure.value>=today()){let date=new Date(departure.value+'T00:00:00Z');if(!isNaN(date)) monthView=new Date(Date.UTC(date.getUTCFullYear(),date.getUTCMonth(),1));}
    else {const d=new Date();monthView=new Date(Date.UTC(d.getFullYear(),d.getMonth(),1));}
    phase='departure';overlay.hidden=false;render();overlay.querySelector('.range-close').focus();
  };
  const close=()=>{overlay.hidden=true;display();trigger.focus();};
  trigger.addEventListener('click',open);
  overlay.querySelector('.range-close').addEventListener('click',close);
  overlay.querySelector('.range-done').addEventListener('click',()=>{
    if (!departure.value || departure.value<today() || (selectedTrip()==='round_trip' && (!returning.value || returning.value<today()))){
      alert('Escolha a data de ida'+(selectedTrip()==='round_trip'?' e a de volta':'')+'.');return;
    }
    if(selectedTrip()==='round_trip' && returning.value < departure.value){alert('A volta não pode ser antes da ida.');return;}
    close();
  });
  overlay.querySelector('.range-prev').addEventListener('click',()=>{
    const prev=new Date(Date.UTC(monthView.getUTCFullYear(),monthView.getUTCMonth()-1,1));
    const now=new Date();const currentMonth=new Date(Date.UTC(now.getFullYear(),now.getMonth(),1));
    if(prev<currentMonth)return;
    monthView=prev;render();
  });
  overlay.querySelector('.range-next').addEventListener('click',()=>{monthView=new Date(Date.UTC(monthView.getUTCFullYear(),monthView.getUTCMonth()+1,1));render();});
  months.addEventListener('click',e=>{
    const value=e.target.closest('[data-day]')?.dataset.day;if(!value || value<today())return;
    if(selectedTrip()!=='round_trip') {departure.value=value;returning.value='';phase='departure';}
    else if(phase==='departure' || !departure.value || value < departure.value){departure.value=value; returning.value='';phase='return';}
    else {returning.value=value;phase='departure';}
    departure.dispatchEvent(new Event('change',{bubbles:true}));returning.dispatchEvent(new Event('change',{bubbles:true}));render();
  });
  overlay.addEventListener('click',e=>{if(e.target===overlay)close();});
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!overlay.hidden)close();});
  [departure, returning].forEach(input=>input.addEventListener('change',display));
  form.querySelectorAll('input[name="travel_type"]').forEach(input=>input.addEventListener('change',display));
  // Não interfere com multitrecho: cada segmento mantém sua própria data.
})();
