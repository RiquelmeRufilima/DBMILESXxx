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
  // ===== Arte no estilo "ficha de viagem", mas como COTAÇÃO (não é reserva) =====
  let brand={};try{brand=JSON.parse(document.getElementById('dbmFlightArtBrand')?.textContent||'{}')||{}}catch{brand={}}
  const names=brand.airport_names||{};
  const rows=Array.isArray(brand.segments)?brand.segments:[];
  const images={};
  function loadImage(key,src){
    if(!src)return Promise.resolve();
    return new Promise(res=>{const img=new Image();img.onload=()=>{images[key]=img;res();};img.onerror=()=>res();img.src=src;});
  }
  const TEAL='#0b6c76',TEAL_D='#085a63',INK='#14232e',MUTED='#6b7c88',LINE='#d8e1e7',SOFT='#f3f6f8',GREEN='#08795a';
  const cityOf=code=>{const n=String(names[code]||'');return n.split(' (')[0]||'';};
  const weekdays=['DOMINGO','SEGUNDA','TERÇA','QUARTA','QUINTA','SEXTA','SÁBADO'];
  const months=['JAN.','FEV.','MAR.','ABR.','MAIO','JUN.','JUL.','AGO.','SET.','OUT.','NOV.','DEZ.'];
  function longDate(iso){
    if(!/^\d{4}-\d\d-\d\d/.test(iso||''))return '';
    const [y,m,d]=iso.slice(0,10).split('-').map(Number);const dt=new Date(Date.UTC(y,m-1,d));
    return `${weekdays[dt.getUTCDay()]}, ${String(d).padStart(2,'0')} ${months[m-1]} ${y}`;
  }
  const hm=n=>`${Math.floor(n/60)}h${n%60?String(n%60).padStart(2,'0')+'min':''}`;
  function rr(x,y,w,h,r,fillColor,stroke){
    ctx.beginPath();ctx.moveTo(x+r,y);ctx.arcTo(x+w,y,x+w,y+h,r);ctx.arcTo(x+w,y+h,x,y+h,r);ctx.arcTo(x,y+h,x,y,r);ctx.arcTo(x,y,x+w,y,r);ctx.closePath();
    if(fillColor){ctx.fillStyle=fillColor;ctx.fill();}
    if(stroke){ctx.strokeStyle=stroke;ctx.lineWidth=2;ctx.stroke();}
  }
  function text(t,x,y,font,color,align='left'){ctx.font=font;ctx.fillStyle=color;ctx.textAlign=align;ctx.fillText(String(t??''),x,y);ctx.textAlign='left';}
  function fitText(t,x,y,maxW,size,weight,color,align='left'){let s=size;ctx.font=`${weight} ${s}px Arial`;while(s>14&&ctx.measureText(String(t)).width>maxW){s-=1;ctx.font=`${weight} ${s}px Arial`;}text(t,x,y,`${weight} ${s}px Arial`,color,align);}
  function drawImageBox(img,x,y,size,bg='#ffffff'){
    rr(x,y,size,size,18,bg);
    if(!img)return false;
    const pad=8,box=size-pad*2,ratio=Math.min(box/img.width,box/img.height);
    const w=img.width*ratio,h=img.height*ratio;ctx.drawImage(img,x+(size-w)/2,y+(size-h)/2,w,h);return true;
  }
  // Dados de cada sentido: horário principal salvo (etapa 6) ou, sem ele, só a rota.
  function sideInfo(side,i){
    const row=rows.find(r=>r.key===side.key)||rows[i]||{};
    const f=(row.flight&&typeof row.flight==='object')?row.flight:{};
    const chosen=preferred.get(side.key)||{};
    return {
      label:side.key==='return'?'VOO DE VOLTA':side.key==='outbound'||side.key==='one_way'?'VOO DE IDA':`TRECHO ${i+1}`,
      origin:f.origin||side.origin||'',destination:f.destination||side.destination||'',
      stops:Array.isArray(f.stops)?f.stops:(side.stops||[]),
      waits:Array.isArray(f.waits)?f.waits:(side.wait_minutes||[]),
      dep:f.departure_time||'',arr:f.arrival_time||'',plus:Number(f.day_offset||0),
      date:chosen.departure_date||(row.display_date?row.display_date.split('/').reverse().join('-'):'')||'',
      duration:Number.isInteger(f.duration_minutes)?f.duration_minutes:(Number.isInteger(side.duration_minutes)?side.duration_minutes:null),
      cabin:side.cabin||'',fare:side.fare||'',bags:side.included_bags,
    };
  }
  // Trechos que vão para o cliente. Sem dados da etapa 5 (cotações antigas) usa
  // os trechos da cotação. No Skip, o trecho NÃO VOADO nunca aparece na arte.
  function visibleSides(){
    const base=sides.length?sides:(rows.length?rows.map(r=>({key:r.key,origin:r.origin,destination:r.destination})):[{key:'one_way',origin:data.origin,destination:data.destination}]);
    const hidden=new Set(rows.filter(r=>r&&r.status==='not_flown').map(r=>r.key));
    const shown=base.filter(side=>!hidden.has(side.key));
    return shown.length?shown:base;
  }
  // Bagagens adicionais são unidades no percurso inteiro; nunca multiplicar
  // por cada trecho/conexão. Os campos de ida e volta identificam o sentido.
  function artBagTotal(){
    const pax=Math.max(1,Number(brand.passengers||1));
    const list=visibleSides();
    const extra=Math.max(0,Number(data.extra_bags_quantity||0));
    return list.reduce((sum,side)=>{const n=Number(side.included_bags);return sum+(Number.isFinite(n)&&n>0?n*pax:0);},extra);
  }
  function artExtraForSide(side,index){
    const assigned=data.extra_bags_outbound!==null&&data.extra_bags_outbound!==undefined || data.extra_bags_return!==null&&data.extra_bags_return!==undefined;
    if(!assigned)return index===0?Math.max(0,Number(data.extra_bags_quantity||0)):0;
    return side.key==='return'?Math.max(0,Number(data.extra_bags_return||0)):
      (['outbound','one_way'].includes(side.key)||index===0)?Math.max(0,Number(data.extra_bags_outbound||0)):
      (index===visibleSides().length-1?Math.max(0,Number(data.extra_bags_return||0)):0);
  }
  // Altura exata: cabeçalho + passageiros + cada trecho (com ou sem bagagens) + resumo.
  function computeHeight(){
    const list=visibleSides();
    const flights=list.reduce((sum,side)=>{const bags=side.included_bags;return sum+30+((bags!==undefined&&bags!==''&&bags!==null)?250:178)+52;},0);
    return 304+56+22+104+56+40+flights+28+160+52+24;
  }
  function render(){
    const list=visibleSides();
    const H=computeHeight();canvas.width=1080;canvas.height=H;
    ctx.fillStyle='#e9eef1';ctx.fillRect(0,0,1080,H);
    // Moldura verde-azulada
    rr(24,24,1032,H-48,34,TEAL);
    // Cabeçalho: agência
    const hasLogo=drawImageBox(images.company,60,60,96);
    if(!hasLogo){text('✈',108,125,'bold 46px Arial',TEAL,'center');}
    fitText(brand.company_name||'ISI VIAGENS',176,96,470,32,'bold','#ffffff');
    text('COTAÇÃO DE PASSAGENS AÉREAS',176,128,'bold 17px Arial','#bfe9ee');
    if(brand.company_cnpj)text(`CNPJ ${brand.company_cnpj}`,176,155,'bold 17px Arial','#d9f2f4');
    text('PRECISA DE AJUDA?',1016,84,'bold 15px Arial','#bfe9ee','right');
    text('Fale com a gente',1016,116,'bold 27px Arial','#ffffff','right');
    if(brand.company_phone)text(brand.company_phone,1016,146,'bold 19px Arial','#d9f2f4','right');
    ctx.strokeStyle='rgba(255,255,255,.18)';ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(60,186);ctx.lineTo(1020,186);ctx.stroke();
    // Companhia + nº da cotação (no lugar do localizador: ainda não é reserva)
    drawImageBox(images.airline,60,206,72,'#1b8a94');
    if(data.issuer&&data.airline){
      // Voo emitido por um programa e operado por outra companhia (ex.: GOL → Avianca).
      fitText(`Operado pela ${data.airline}`,148,234,560,28,'bold','#ffffff');
      fitText(`EMITIDO PELA ${String(data.issuer).toLocaleUpperCase('pt-BR')}`,148,260,560,16,'bold','#d9f2f4');
      text('COTAÇÃO • AINDA NÃO É RESERVA',148,284,'bold 13px Arial','#bfe9ee');
    }else{
      fitText(data.airline||'Companhia aérea',148,240,470,30,'bold','#ffffff');
      text('COTAÇÃO • AINDA NÃO É RESERVA',148,268,'bold 15px Arial','#bfe9ee');
    }
    text('COTAÇÃO Nº',1016,232,'bold 15px Arial','#bfe9ee','right');
    text(String(data.quote_id||'—'),1016,272,'bold 38px Arial','#ffffff','right');
    // Cartão branco
    const top=304;rr(52,top,976,H-top-52,26,'#ffffff');
    let y=top+56;
    // Cotação (não é reserva): só o nome da cotação + quantidade de passageiros e bagagens.
    text('Cotação',88,y,'bold 25px Arial',INK);
    y+=22;rr(88,y,904,62,14,SOFT);
    const pax=Number(brand.passengers||1),babies=Number(brand.babies||0);
    const paxText=`👥 ${pax} ${pax===1?'passageiro':'passageiros'}${babies?` + ${babies} ${babies===1?'bebê':'bebês'}`:''}`;
    const bagTotal=artBagTotal();
    const bagText=bagTotal>0?`🧳 ${bagTotal} ${bagTotal===1?'bagagem':'bagagens'} de 23 kg`:'🧳 Sem bagagem despachada';
    ctx.font='bold 19px Arial';const bagW=ctx.measureText(bagText).width+34,paxW=ctx.measureText(paxText).width+34;
    const chipY=y+13,bagX=968-bagW,paxX=bagX-12-paxW;
    rr(paxX,chipY,paxW,36,18,'#e4ebf0');text(paxText,paxX+paxW/2,chipY+25,'bold 19px Arial',INK,'center');
    rr(bagX,chipY,bagW,36,18,'#dff3ee');text(bagText,bagX+bagW/2,chipY+25,'bold 19px Arial',GREEN,'center');
    fitText(data.name||'Cotação',110,y+40,Math.max(160,paxX-130),24,'bold',INK);
    y+=104;
    // Separador picotado com recortes laterais
    ctx.setLineDash([10,9]);ctx.strokeStyle=LINE;ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(84,y);ctx.lineTo(996,y);ctx.stroke();ctx.setLineDash([]);
    ctx.fillStyle=TEAL;ctx.beginPath();ctx.arc(52,y,16,0,Math.PI*2);ctx.arc(1028,y,16,0,Math.PI*2);ctx.fill();
    y+=56;
    text('Itinerário',88,y,'bold 25px Arial',INK);
    const kind=list.length===2&&list[1].key==='return'?'Ida e volta':list.length>2?'Multitrecho':list.length===2?'Multitrecho':'Somente ida';
    text(`${kind} · ${list.length} ${list.length===1?'trecho':'trechos'}`,992,y,'19px Arial',MUTED,'right');
    y+=40;
    list.forEach((side,i)=>{
      const info=sideInfo(side,i);
      // Título do sentido + tarifa
      text(info.label,88,y+6,'bold 17px Arial',MUTED);
      ctx.strokeStyle=LINE;ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(88+ctx.measureText(info.label).width+18,y);ctx.lineTo(info.fare?760:992,y);ctx.stroke();
      if(info.fare){text('Tarifa',800,y+6,'17px Arial',MUTED);rr(860,y-20,132,36,10,'#ffffff',LINE);fitText(info.fare,926,y+5,116,17,'bold',INK,'center');}
      y+=30;
      // Caixa do voo
      const boxH=info.bags!==undefined&&info.bags!==''&&info.bags!==null?250:178;
      rr(88,y,904,boxH,18,SOFT);
      const cy=y+92;
      text(longDate(info.date),112,y+42,'bold 16px Arial',MUTED);
      if(info.cabin&&info.cabin!=='Não informar'){rr(112,y+58,160,38,10,'#e4ebf0');fitText(info.cabin,192,y+83,140,17,'bold',INK,'center');}
      // Horário e aeroportos
      const leftX=330,rightX=968;
      if(info.dep)text(info.dep,leftX,cy-6,'bold 40px Arial',INK);
      text(`${info.origin}`,leftX,cy+(info.dep?32:6),'bold 26px Arial',INK);
      const oc=cityOf(info.origin);if(oc)text(`· ${oc}`,leftX+ctx.measureText(info.origin).width+10,cy+(info.dep?32:6),'20px Arial',MUTED);
      if(info.arr){text(info.arr,rightX-(info.plus?30:0),cy-6,'bold 40px Arial',INK,'right');if(info.plus)text(`+${info.plus}`,rightX,cy-26,'bold 18px Arial','#d0573b','right');}
      const dc=cityOf(info.destination);
      ctx.font='bold 26px Arial';const dw=ctx.measureText(info.destination).width;
      text(info.destination,rightX,cy+(info.arr?32:6),'bold 26px Arial',INK,'right');
      if(dc)text(`${dc} ·`,rightX-dw-10,cy+(info.arr?32:6),'20px Arial',MUTED,'right');
      // Linha do trajeto com paradas e esperas (sem encostar nos nomes das cidades)
      ctx.font='bold 26px Arial';const ow=ctx.measureText(info.origin).width;ctx.font='20px Arial';const ocw=oc?ctx.measureText(`· ${oc}`).width+10:0;
      ctx.font='20px Arial';const dcw=dc?ctx.measureText(`${dc} ·`).width+10:0;
      const lx1=Math.max(leftX+150,leftX+ow+ocw+24),lx2=Math.min(rightX-170,rightX-dw-dcw-24),ly=cy-14;
      ctx.setLineDash([3,7]);ctx.strokeStyle='#8fa3b1';ctx.lineWidth=2.5;ctx.beginPath();ctx.moveTo(lx1,ly);ctx.lineTo(lx2,ly);ctx.stroke();ctx.setLineDash([]);
      if(!info.stops.length){
        ctx.fillStyle=TEAL;ctx.beginPath();ctx.arc((lx1+lx2)/2,ly,17,0,Math.PI*2);ctx.fill();text('✈',(lx1+lx2)/2,ly+7,'bold 18px Arial','#ffffff','center');
        text('Direto',(lx1+lx2)/2,ly-28,'bold 16px Arial',TEAL,'center');
      }else{
        info.stops.forEach((code,k)=>{
          const x=lx1+(lx2-lx1)*(k+1)/(info.stops.length+1);
          ctx.fillStyle='#ffffff';ctx.strokeStyle='#e09a2b';ctx.lineWidth=3;ctx.beginPath();ctx.arc(x,ly,9,0,Math.PI*2);ctx.fill();ctx.stroke();
          text(code,x,ly+32,'bold 17px Arial','#8a5208','center');
          // Espera acima da parada; com pouco espaço entre paradas usa o formato curto ("3h05").
          const w=info.waits[k];
          if(Number.isInteger(w)){
            const gap=(lx2-lx1)/(info.stops.length+1)-14;
            const short=`${Math.floor(w/60)}h${String(w%60).padStart(2,'0')}`;
            ctx.font='bold 14px Arial';
            const label=ctx.measureText(`${short} de espera`).width<=gap?`${short} de espera`:short;
            text(label,x,ly-20,'bold 14px Arial','#8a5208','center');
          }
        });
        text(`${info.stops.length} ${info.stops.length===1?'parada':'paradas'}`,(lx1+lx2)/2,ly+58,'bold 15px Arial',MUTED,'center');
      }
      if(info.duration)text(hm(info.duration),(lx1+lx2)/2,info.stops.length?ly-46:ly+40,'bold 17px Arial',TEAL,'center');
      // Bagagem despachada (franquia da tarifa)
      if(boxH>200){
        ctx.strokeStyle=LINE;ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(112,y+176);ctx.lineTo(968,y+176);ctx.stroke();
        const n=Number(info.bags);
        text('Bagagens',112,y+208,'bold 17px Arial',MUTED);
        text(Number.isFinite(n)&&n>0?`🧳 Despachada 23 kg: ${n} por passageiro`:'🧳 Sem bagagem despachada incluída',250,y+208,'19px Arial',INK);
        const extra=artExtraForSide(side,list.indexOf(side));
        if(extra>0&&checkbox.checked){
          const assigned=data.extra_bags_outbound!=null||data.extra_bags_return!=null;
          text(`+ ${extra} adicional(is)${assigned?'':' no percurso (total)'}`,968,y+208,'bold 17px Arial',TEAL,'right');
        }
      }
      y+=boxH+52;
    });
    // Resumo de valores
    ctx.setLineDash([10,9]);ctx.strokeStyle=LINE;ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(84,y-18);ctx.lineTo(996,y-18);ctx.stroke();ctx.setLineDash([]);
    ctx.fillStyle=TEAL;ctx.beginPath();ctx.arc(52,y-18,16,0,Math.PI*2);ctx.arc(1028,y-18,16,0,Math.PI*2);ctx.fill();
    y+=28;
    text('Resumo da cotação',88,y,'bold 25px Arial',INK);
    const sale=Number(data.sale||0);
    const defined=data.sale!==null&&data.sale!==undefined&&Number.isFinite(Number(data.sale));
    if(defined){
      text('VALOR À VISTA',88,y+46,'bold 16px Arial',MUTED);
      text(money(sale),88,y+98,'bold 50px Arial',GREEN);
      const maxChoice=Number(document.getElementById('dbmMessageMaxInstallments')?.value||document.getElementById('dbmCompactMaxInstallments')?.value||0);
      const maxRate=typeof window.dbmFlightPaymentPreview==='function'&&maxChoice>1?window.dbmFlightPaymentPreview(maxChoice):null;
      const chosenN=maxRate&&Number.isFinite(maxRate)?maxChoice:Number(data.installments||1);
      const chosenValue=maxRate&&Number.isFinite(maxRate)?maxRate:Number(data.installment_value||0);
      if(pay.checked&&chosenN>1&&chosenValue>0)text(`ou até ${chosenN}x de ${money(chosenValue)} no cartão`,88,y+136,'bold 22px Arial',TEAL);
    }else{
      text('Valor sob consulta',88,y+70,'bold 30px Arial',INK);
    }
    text('Cotação sujeita à disponibilidade e alteração de valores',992,y+90,'16px Arial',MUTED,'right');
    text('até a emissão. Não é uma reserva.',992,y+114,'16px Arial',MUTED,'right');
  }
  const ready=Promise.all([loadImage('company',brand.company_logo),loadImage('airline',brand.airline_logo)]);
  ready.then(()=>render());
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
  document.addEventListener('dbm:commercial-entry-changed',()=>{installmentRows();render();});
  document.addEventListener('dbm:machine-fees-loaded',installmentRows);
  setTimeout(installmentRows,100);
  render();
})();
