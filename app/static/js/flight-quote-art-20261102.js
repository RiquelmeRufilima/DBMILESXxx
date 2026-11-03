/* DBMILESX - visualização/exportação de cotação, 100% local no navegador.
   Nenhuma API de imagem, nenhuma coleta de dados ou custo por geração. */
(() => {
  'use strict';
  const source=document.getElementById('dbmFlightArtData');
  const area=document.getElementById('dbmFlightArtArea');
  if(!source||!area)return;
  let data={};try{data=JSON.parse(source.textContent||'{}')}catch{return}
  const canvas=area.querySelector('canvas');
  const ctx=canvas?.getContext('2d');
  if(!ctx)return;
  const money=n=>Number(n||0).toLocaleString('pt-BR',{style:'currency',currency:'BRL'});
  const dateBR=v=>/^\d{4}-\d\d-\d\d/.test(v||'')?(v.slice(0,10).split('-').reverse().join('/')+' '+(v.slice(11,16)||'')):'';
  const checkbox=area.querySelector('#dbmArtShowBagPrices');
  const pay=area.querySelector('#dbmArtShowPayments');
  const itin=data.itinerary && typeof data.itinerary==='object'?data.itinerary:{};
  const saved=Array.isArray(data.flight_options)?data.flight_options:[];
  const preferred=new Map();
  saved.filter(o=>o&&o.preferred).concat(saved).forEach(o=>{
    if(o&&o.segment_key&&!preferred.has(o.segment_key))preferred.set(o.segment_key,o);
  });
  const baseSides=Array.isArray(itin.sides)?itin.sides:[];
  const sides=baseSides.map(base=>{
    const chosen=preferred.get(base.key);
    if(!chosen)return base;
    const stops=Array.isArray(chosen.stops)?chosen.stops:[];
    const codes=[base.origin,...stops,base.destination];
    const legs=codes.slice(0,-1).map((code,i)=>{
      const detail=(Array.isArray(chosen.legs)?chosen.legs[i]:null)||{};
      const previous=(Array.isArray(base.legs)?base.legs[0]:null)||{};
      return {...detail,origin:code,destination:codes[i+1],partner:previous.partner||data.airline};
    });
    if(legs.length===1){
      if(!legs[0].departure&&chosen.departure_date&&chosen.departure_time)legs[0].departure=chosen.departure_date+'T'+chosen.departure_time;
      if(!legs[0].arrival&&chosen.arrival_date&&chosen.arrival_time)legs[0].arrival=chosen.arrival_date+'T'+chosen.arrival_time;
    }
    return {...base,status:stops.length?'stops':'direct',stops,legs,
      duration_minutes:chosen.duration_minutes??null,wait_minutes:chosen.wait_minutes||[]};
  });
  function fill(text,x,y,font,color){ctx.font=font;ctx.fillStyle=color;ctx.fillText(String(text||''),x,y);}
  function line(x1,y1,x2,y2,color='#d9e7f3',w=2){ctx.strokeStyle=color;ctx.lineWidth=w;ctx.beginPath();ctx.moveTo(x1,y1);ctx.lineTo(x2,y2);ctx.stroke();}
  function wrap(text,x,y,maxWidth,font,color,lineHeight=31,maxLines=2){
    ctx.font=font;const words=String(text||'').split(/\s+/).filter(Boolean);let current='',count=0;
    words.forEach(word=>{const next=current?current+' '+word:word;
      if(ctx.measureText(next).width>maxWidth&&current&&count<maxLines-1){fill(current,x,y+count*lineHeight,font,color);count++;current=word;}else current=next;});
    if(current)fill(current,x,y+count*lineHeight,font,color);
    return y+(count+1)*lineHeight;
  }
  const segCount=sides.reduce((n,s)=>n+(Array.isArray(s.legs)?s.legs.length:0),0);
  function render(){
    const height=Math.min(3800,920+Math.min(18,segCount)*170+sides.length*135);
    canvas.width=1080;canvas.height=height;
    const grad=ctx.createLinearGradient(0,0,1080,height);grad.addColorStop(0,'#eff9ff');grad.addColorStop(1,'#ffffff');
    ctx.fillStyle=grad;ctx.fillRect(0,0,1080,height);
    ctx.fillStyle='#0e4872';ctx.fillRect(0,0,1080,210);
    ctx.fillStyle='#1582bf';ctx.fillRect(0,190,1080,20);
    fill('✈  ISI VIAGENS',62,86,'bold 51px Arial','#ffffff');
    fill('COTAÇÃO DE PASSAGENS AÉREAS',64,145,'bold 23px Arial','#bfeafe');
    let y=260;
    fill('PASSAGEIRO / CLIENTE',65,y,'bold 20px Arial','#53738a');y+=55;
    y=wrap(data.name||'Cliente',65,y,940,'bold 42px Arial','#173954',49,2)+33;
    if(!sides.length){
      fill(`${data.origin||'ORIGEM'}  ✈  ${data.destination||'DESTINO'}`,65,y,'bold 34px Arial','#144b75');y+=75;
      fill('Paradas e horários não informados',65,y,'22px Arial','#51718a');y+=105;
    }
    sides.forEach((side,i)=>{
      if(y>height-350)return;
      const label=side.key==='return'?'VOLTA':side.key==='outbound'||side.key==='one_way'?'IDA':`TRECHO ${i+1}`;
      ctx.fillStyle='#e2f1fc';ctx.fillRect(55,y-34,970,57);
      fill(`${label}  •  ${side.origin||''} → ${side.destination||''}`,70,y,'bold 30px Arial','#134d75');y+=53;
      const legs=Array.isArray(side.legs)?side.legs:[];
      const status=side.status==='stops'&&Array.isArray(side.stops)&&side.stops.length
        ?`${side.stops.length} ${side.stops.length===1?'CONEXÃO/PARADA':'CONEXÕES/PARADAS'}`:'VOO DIRETO';
      fill(status,76,y,'bold 22px Arial','#087c63');y+=42;
      legs.forEach((leg,idx)=>{
        if(y>height-250)return;
        fill(`✈ ${leg.origin||'?'}  →  ${leg.destination||'?'}`,77,y,'bold 27px Arial','#163d60');y+=35;
        const brand=leg.partner||data.airline||'';
        const fare=idx===0?[side.cabin||legs[0]?.cabin,side.fare||legs[0]?.fare].filter(Boolean).join(' • '):'';
        const details=[brand,fare].filter(Boolean).join('  |  ');
        if(details){y=wrap(details,108,y,875,'21px Arial','#456f88',27,2)+4;}
        // A bagagem pertence ao sentido do voo, não a cada conexão.
        if(idx===0){
          const bags=side.included_bags??legs[0]?.included_bags;
          const label=bags===''||bags==null?'Bagagem: a confirmar':Number(bags)>0?`${Number(bags)} mala(s) incluída(s)`:'Sem mala despachada incluída';
          y=wrap(label,108,y,885,'19px Arial','#527c91',27,2)+4;
          const extraQty=Math.max(0,Number(data.extra_bags_quantity||0));
          const where=itin.bags_applies_to||'all';
          const showExtra=extraQty>0&&checkbox.checked&&(where==='all'||where===side.key);
          if(showExtra){
            const extraLabel=`+ ${extraQty} bagagem(ns) adicional(is) neste sentido`;
            y=wrap(extraLabel,108,y,885,'19px Arial','#527c91',27,2)+4;
          }
        }
        if(leg.departure&&leg.arrival){
          const times=`${dateBR(leg.departure)} ${leg.origin_tz?'UTC'+leg.origin_tz:''} → ${dateBR(leg.arrival)} ${leg.destination_tz?'UTC'+leg.destination_tz:''}`;
          y=wrap(times,108,y,885,'19px Arial','#527c91',25,2)+4;
        }
        if(idx<legs.length-1){
          line(108,y-5,990,y-5,'#bcd6e9',2);y+=24;
          const wait=Array.isArray(side.wait_minutes)?side.wait_minutes[idx]:null;
          const labelWait=Number.isInteger(wait)&&wait>=0?` • espera ${Math.floor(wait/60)}h${String(wait%60).padStart(2,'0')}`:'';
          fill(`CONEXÃO EM ${side.stops?.[idx]||leg.destination}${labelWait}`,110,y,'bold 20px Arial','#12828a');y+=30;
        }
      });
      if(side.duration_minutes!==null&&Number.isInteger(side.duration_minutes)){
        fill(`Duração total: ${Math.floor(side.duration_minutes/60)}h${String(side.duration_minutes%60).padStart(2,'0')}`,77,y,'bold 20px Arial','#0e765e');y+=40;
      }
      y+=26;
    });
    const footerStart=Math.max(y+5,height-270);
    line(65,footerStart,1015,footerStart,'#afcede',3);
    const sale=Number(data.sale||0);
    const defined=data.sale!==null&&data.sale!==undefined&&Number.isFinite(Number(data.sale));
    if(defined){
      fill('VALOR À VISTA',67,footerStart+51,'bold 21px Arial','#506f82');
      fill(money(sale),68,footerStart+110,'bold 48px Arial','#087753');
    }
    const maxChoice=Number(document.getElementById('dbmMessageMaxInstallments')?.value||document.getElementById('dbmCompactMaxInstallments')?.value||0);
    const maxRate=typeof window.dbmFlightPaymentPreview==='function'&&maxChoice>1
      ?window.dbmFlightPaymentPreview(maxChoice):null;
    const chosenN=maxRate&&Number.isFinite(maxRate)?maxChoice:Number(data.installments||1);
    const chosenValue=maxRate&&Number.isFinite(maxRate)?maxRate:Number(data.installment_value||0);
    if(defined && pay.checked && chosenN>1 && chosenValue>0){
      fill(`OU ATÉ ${chosenN}x DE ${money(chosenValue)}`,68,footerStart+151,'bold 26px Arial','#0d598a');
    }
    fill('Valores sujeitos a alteração até a confirmação da reserva.',66,height-49,'20px Arial','#5a7485');
  }
  checkbox.addEventListener('change',render);pay.addEventListener('change',render);
  area.querySelector('#dbmArtGenerate').addEventListener('click',render);
  area.querySelector('#dbmArtDownload').addEventListener('click',()=>{
    render();const link=document.createElement('a');link.download=`cotacao-ISI-${data.quote_id||'voo'}.png`;
    link.href=canvas.toDataURL('image/png');link.click();
  });
  area.querySelector('#dbmArtShare').addEventListener('click',async()=>{
    render();if(!navigator.share||!window.File){alert('Seu dispositivo não permite compartilhar arquivos por aqui. Use Baixar PNG e envie pelo WhatsApp.');return;}
    canvas.toBlob(async blob=>{
      if(!blob)return;
      const file=new File([blob],`cotacao-ISI-${data.quote_id||'voo'}.png`,{type:'image/png'});
      try{if(navigator.canShare&&!navigator.canShare({files:[file]}))throw new Error('unsupported');await navigator.share({files:[file],title:'Cotação ISI Viagens'});}
      catch(err){if(err.name!=='AbortError')alert('Use Baixar PNG para enviar a arte no WhatsApp.');}
    },'image/png');
  });
  // Parcelamento: usar exatamente a mesma tabela carregada na mensagem do cliente.
  const maxInput=document.getElementById('dbmCompactMaxInstallments');
  const info=document.getElementById('dbmCompactInstallmentsList');
  function installmentRows(){
    if(!maxInput||!info)return;
    const supportedMax=typeof window.dbmFlightMaxInstallments==='function'
      ?Math.max(1,window.dbmFlightMaxInstallments()) : 12;
    if(Number(maxInput.dataset.loadedMax)!==supportedMax){
      const desired=Math.min(supportedMax,Number(maxInput.value)||12);
      maxInput.replaceChildren();
      for(let i=1;i<=supportedMax;i++){
        const opt=document.createElement('option');opt.value=String(i);opt.textContent=`${i}x`;
        maxInput.append(opt);
      }
      maxInput.value=String(desired);
      maxInput.dataset.loadedMax=String(supportedMax);
    }
    const maximum=Math.max(1,Math.min(supportedMax,Number(maxInput.value)||12));
    const get=window.dbmFlightPaymentPreview;
    if(typeof get!=='function'){info.textContent='Valores disponíveis depois que as taxas forem carregadas.';return;}
    const lines=[];
    for(let n=1;n<=maximum;n++){
      const v=get(n);
      if(!Number.isFinite(v)||v<=0)continue;
      lines.push(`${n}x de ${money(v)}${n===1?' à vista':''}`);
    }
    info.replaceChildren();
    lines.forEach(text=>{const div=document.createElement('div');div.textContent=text;div.style.margin='4px 0';info.append(div);});
  }
  maxInput?.addEventListener('change',()=>{
    installmentRows();
    const installmentInput=document.getElementById('dbmPayIntN');
    if(installmentInput){
      installmentInput.value=maxInput.value;
      installmentInput.dispatchEvent(new Event('input',{bubbles:true}));
    }
    render();
  });
  document.addEventListener('dbm:commercial-saved',event=>{
    const record=event.detail||{};
    if(String(record.quote_id||'')!==String(data.quote_id||''))return;
    if(record.removed){data.sale=null;data.installments=1;data.installment_value=0;}
    else{
      if(Number(record.sale_value)>0)data.sale=Number(record.sale_value);
      data.installments=Number(record.card_installments||1);
      data.installment_value=Number(record.card_installment_value||0);
    }
    setTimeout(()=>{installmentRows();render();},0);
  });
  document.addEventListener('dbm:machine-fees-loaded',installmentRows);
  setTimeout(installmentRows,100);
  render();
})();
