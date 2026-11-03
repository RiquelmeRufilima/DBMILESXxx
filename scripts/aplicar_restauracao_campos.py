#!/usr/bin/env python3
"""DBMILESX: restore original fare/pax options + message controls, safely.

Runs on current Codespaces files, never overwrites unknown template versions.
Preflight is atomic, all changes written only after matching anchors and syntax.
"""
from __future__ import annotations
import argparse
import datetime
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys

FLIGHT = 'app/static/js/flight-itinerary-20261102.js'
ART = 'app/static/js/flight-quote-art-20261102.js'
NEW = 'app/templates/calculations/new.html'
RESULT = 'app/templates/calculations/result.html'
EXPECTED_JS_SHA = 'ba855d15908bff799a22a32d8bcf4be720afad162162298eb3be5a3facfa73b4'


def once(text, old, new, label):
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise ValueError(f'{label}: esperado 1 trecho, encontrado {count}. Versão diferente; instale somente após revisão.')
    return text.replace(old, new, 1)


def patch_new(s):
    # The base form already has separate inputs on the verified branch.
    if 'id="paxAdults"' not in s or 'id="paxChildren"' not in s or 'id="paxTotal"' not in s:
        old='''    <div class="form-grid cols-2">
      <label>Passageiros pagantes<input type="number" name="passengers" value="{{ base.passengers }}" min="1" max="100" required></label>
      <label>Bebês<input type="number" name="babies" value="{{ base.babies }}" min="0" max="100"></label>
    </div>'''
        replacement='''    {% set base_children = base.children|default(0)|int %}
    <div class="form-grid cols-3 dbm-pax-visible" id="paxSplit" aria-label="Passageiros separados em adultos, crianças e bebês">
      <label>Adultos pagantes<input type="number" name="adults" id="paxAdults" value="{{ [base.passengers|int - base_children, 1]|max }}" min="1" max="100" required></label>
      <label>Crianças pagantes<input type="number" name="children" id="paxChildren" value="{{ base_children }}" min="0" max="99"></label>
      <label>Bebês<input type="number" name="babies" value="{{ base.babies }}" min="0" max="100"></label>
    </div>
    <input type="hidden" name="passengers" id="paxTotal" value="{{ base.passengers }}">
    <small id="paxTotalHint" class="muted">Passageiros pagantes: {{ base.passengers }}</small>
    <script>(()=>{
      const adults=document.getElementById('paxAdults'),kids=document.getElementById('paxChildren');
      const total=document.getElementById('paxTotal'),hint=document.getElementById('paxTotalHint');
      const sync=()=>{const n=Math.max(1,(Number(adults.value)||0)+(Number(kids.value)||0));total.value=n;hint.textContent=`Passageiros pagantes: ${n} (adultos + crianças)`};
      [adults,kids].forEach(input=>input.addEventListener('input',sync));sync();
    })();</script>'''
        s=once(s,old,replacement,'restaurar adultos/crianças da tela antiga')
    # The user's original tariff catalog must still exist behind the new UI.
    for field in ('fare_brand', 'cabin_class', 'included_bags_per_passenger'):
        if f'name="{field}"' not in s:
            raise ValueError(f'Campo legado ausente: {field}')
    # Highlight the original adults / child controls, not duplicate their names.
    s = once(s, '<div class="form-grid cols-3" id="paxSplit">',
        '<div class="form-grid cols-3 dbm-pax-visible" id="paxSplit" aria-label="Passageiros separados em adultos, crianças e bebês">',
        'adultos/crianças')
    # Bust cache only when asset URL exists. Check old or already updated version.
    s = once(s, '/static/js/flight-itinerary-20261102.js?v=20261102.3',
        '/static/js/flight-itinerary-20261102.js?v=20261102.4', 'cache de itinerário')
    return s


MESSAGE_CONTROLS = '''    <div class="dbm-message-new-settings" id="dbmMessageSettings" aria-label="Configurações opcionais da mensagem">
      <div class="dbm-message-heading">⚙️ Configurações da mensagem</div>
      <label class="dbm-message-max">Máximo de parcelas para o cliente
        <select id="dbmMessageMaxInstallments" aria-label="Máximo de parcelas para o cliente">
          <option value="3">3x</option><option value="6">6x</option><option value="10">10x</option><option value="12" selected>12x</option><option value="15">15x</option>
        </select>
      </label>
      <label><input type="checkbox" id="dbmMessageShowAllInstallments"> Mostrar todas as parcelas até o máximo escolhido</label>
      <label><input type="checkbox" id="dbmMessageShowTimes"> Mostrar horários e duração (se informados)</label>
      <label><input type="checkbox" id="dbmMessageShowFare"> Mostrar tarifa e classe (se informadas)</label>
      <fieldset id="dbmBaggageModes"><legend>Como mostrar as bagagens</legend>
        <label><input type="radio" name="dbmMessagePriceMode" value="total" checked> Quantidade total de bagagens</label>
        <label><input type="radio" name="dbmMessagePriceMode" value="per_person"> Bagagem por passageiro</label>
        <label><input type="radio" name="dbmMessagePriceMode" value="per_leg"> Bagagem por trecho</label>
        <label><input type="radio" name="dbmMessagePriceMode" value="per_person_leg"> Por passageiro e por trecho</label>
      </fieldset>
      <small>As bagagens incluem a franquia da tarifa mais as adicionais. Conexões não duplicam bagagens.</small>
    </div>'''


HELPERS = r''' const msgMaxInstallments = document.getElementById('dbmMessageMaxInstallments');
 const msgShowAll = document.getElementById('dbmMessageShowAllInstallments');
 const msgShowFare = document.getElementById('dbmMessageShowFare');
 let itineraryData={};
 try { const raw=JSON.parse(includedBags||'{}');itineraryData=raw._itinerary_v1||{}; } catch(_){}
 const itinerarySides=Array.isArray(itineraryData.sides)?itineraryData.sides:[];
 const bagModeBox=document.getElementById('dbmBaggageModes');
 const saleKnown=()=>typeof profitDefined!=='undefined'?!!profitDefined:{{ (quote.commercial is not none and quote.commercial.profit_value is not none)|tojson }};
 const bagQty=n=>`${n} ${n===1?'bagagem de 23kg inclusa':'bagagens de 23kg inclusas'}`;
 function getBaggageLines(){
   const paid=Math.max(1,Number(passengers)||1);
   const added=Math.max(0,Number(baggage)||0);
   const original=Number(fareIncluded);
   const fallback=Number.isFinite(original)&&original>0?original:0;
   const mode=selectedPriceMode();
   const segments=itinerarySides.length?itinerarySides:[{key:'one_way',included_bags:String(fareIncluded||'')}];
   const franchisePerSide=segments.map(s=>{
     const n=Number(s.included_bags);
     return s.included_bags==null||s.included_bags===''?fallback:(Number.isFinite(n)&&n>0?n:0);
   });
   // A mesma mala na ida e na volta não é duas malas distintas.
   const baseIncluded=Math.max(fallback,...franchisePerSide)*paid;
   const total=baseIncluded+added;
   if(bagModeBox)bagModeBox.hidden=total===0;
   if(total===0)return '';
   const line=txt=>`✅ +${txt}\n`;
   if(mode==='total')return line(bagQty(total));
   if(mode==='per_person'){
     const base=Math.max(fallback,...franchisePerSide);
     return (base>0?line(`${bagQty(base)} por passageiro`):'')+
       (added>0?line(`${bagQty(added)} adicionais na cotação`):'');
   }
   const scope=String(itineraryData.bags_applies_to||'all');
   const labelOf=(side,i)=>side.key==='return'?'VOLTA':side.key==='outbound'||side.key==='one_way'?'IDA':`TRECHO ${i+1}`;
   const lines=[];
   segments.forEach((side,i)=>{
     const included=franchisePerSide[i];
     // 'all' representa uma quantidade no percurso inteiro, não uma cópia por conexão.
     const extras=scope!=='all'&&scope===side.key?added:0;
     if(included*paid+extras===0)return;
     const label=labelOf(side,i);
     if(mode==='per_person_leg'){
       if(included)lines.push(line(`${label}: ${bagQty(included)} por passageiro`).trimEnd());
       if(extras)lines.push(line(`${label}: ${bagQty(extras)} adicionais na cotação`).trimEnd());
     }else{
       lines.push(line(`${label}: ${bagQty(included*paid+extras)}`).trimEnd());
     }
   });
   if(scope==='all'&&added>0)lines.push(line(`Percurso completo: ${bagQty(added)} adicionais`).trimEnd());
   return lines.length?lines.join('\n')+'\n':'';
 }
 function itineraryExtraDetails(){
   let text='';
   if(msgShowFare?.checked){
     itinerarySides.forEach((side,i)=>{
       const fields=[side.cabin,side.fare].filter(v=>v&&v!=='Não informar'&&v!=='Não informado');
       if(fields.length)text+=`💺 ${side.key==='return'?'VOLTA':side.key==='outbound'||side.key==='one_way'?'IDA':`TRECHO ${i+1}`}: ${fields.join(' • ')}\n`;
     });
     if(!itinerarySides.length){
       const fields=[{{ (quote.cabin_class or '')|tojson }},fare].filter(v=>v&&v!=='Não informada');
       if(fields.length)text+=`💺 ${fields.join(' • ')}\n`;
     }
   }
   if(showTimes.checked){
     itinerarySides.forEach((side,i)=>{
       const legs=Array.isArray(side.legs)?side.legs:[];
       const head=side.key==='return'?'VOLTA':side.key==='outbound'||side.key==='one_way'?'IDA':`TRECHO ${i+1}`;
       const filled=legs.filter(leg=>leg.departure||leg.arrival);
       if(!filled.length)return;
       text+=`🕒 ${head}:\n`;
       filled.forEach(leg=>{
         const fmt=v=>/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(v||'')?v.slice(8,10)+'/'+v.slice(5,7)+'/'+v.slice(0,4)+' '+v.slice(11,16):v||'—';
         const d=fmt(leg.departure);
         const a=fmt(leg.arrival);
         text+=`  ${leg.origin||'?'} → ${leg.destination||'?'}: ${d} → ${a}\n`;
       });
       if(Number.isInteger(side.duration_minutes))text+=`⏱️ Duração total: ${Math.floor(side.duration_minutes/60)}h${String(side.duration_minutes%60).padStart(2,'0')}\n`;
     });
   }
   return text;
 }
 function installmentList(){
   const supported=typeof window.dbmFlightMaxInstallments==='function'?window.dbmFlightMaxInstallments():15;
   const max=Math.max(2,Math.min(15,supported,Number(msgMaxInstallments?.value||12)));
   const entry=Math.max(0,Number(commercialMeta.entry_amount||0));
   const financed=Math.max(0,sale-entry);
   const money=n=>Number(n||0).toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2});
   const lines=[];
   for(let n=1;n<=max;n++){
     const rate=n===1?0:machineRate(n);
     if(rate<0||rate>=100)continue;
     const total=n===1?financed:Math.round(financed/(1-rate/100)*100)/100;
     lines.push(`• ${n}x de R$ ${money(total/n)}${n===1?' à vista':' com juros'}`);
   }
   return lines.length?'💳 Parcelamento disponível:\n'+lines.join('\n'):' ';
 }
'''


def patch_result(s):
    anchor='''    <fieldset><legend>Bagagens na mensagem</legend><label><input type="radio" name="dbmMessagePriceMode" value="total" checked> Total da cotação</label><label><input type="radio" name="dbmMessagePriceMode" value="per_person"> Por passageiro</label></fieldset>
    <label><input type="checkbox" id="dbmMessageShowTimes"> Informar datas e horários dos voos, quando cadastrados</label>'''
    s=once(s,anchor,MESSAGE_CONTROLS,'controles de mensagem')
    css='''<style>
 .dbm-share-options'''
    css2='''<style>
.dbm-message-new-settings{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px 16px;padding:12px;border:1px solid #365e7d;border-radius:11px;background:rgba(21,67,101,.2)}
.dbm-message-heading{grid-column:1/-1;font-weight:900;font-size:.85rem}
.dbm-message-new-settings>label{display:flex!important;justify-content:flex-start;align-items:center;min-width:0}
.dbm-message-max select{max-width:110px;min-width:74px;min-height:34px;margin-left:8px;border-radius:8px;background:var(--panel-2,#0a2034);color:var(--text,#fff);border:1px solid #537795}
.dbm-message-new-settings fieldset{grid-column:1/-1;display:grid!important;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px;padding:0}
.dbm-message-new-settings fieldset legend{grid-column:1/-1}
.dbm-message-new-settings small{grid-column:1/-1}
.dbm-message-new-settings fieldset[hidden]{display:none!important}
.dbm-pax-visible{position:relative;z-index:0}
#dbmCompactInstallments{display:none!important} /* selector duplicado: controlado acima */
html[data-theme='light'] .dbm-message-new-settings{background:#f4faff;color:#193c56;border-color:#c1dbee}
html[data-theme='light'] .dbm-message-max select{background:#fff;color:#193c56;border-color:#bed5e5}
@media(max-width:650px){.dbm-message-new-settings,.dbm-message-new-settings fieldset{grid-template-columns:1fr}}
 .dbm-share-options'''
    s=once(s,css,css2,'CSS da mensagem')
    needle=" const showTimes = document.getElementById('dbmMessageShowTimes');"
    s=once(s,needle,needle+'\n'+HELPERS,'helpers de mensagem')
    # original included baggage and extra displayed separately; replace with new summed logic.
    start='''   const bagCount=Number(fareIncluded)||0;'''
    end='''   const obs=note.value.trim();'''
    if '   const bagText=getBaggageLines();' not in s:
        if start not in s or end not in s:
            raise ValueError('Bloco de bagagem da mensagem não corresponde à versão esperada.')
        a=s.index(start);b=s.index(end,a)
        s=s[:a]+'''   const bagText=getBaggageLines();
   const optionalDetails=itineraryExtraDetails();
'''+s[b:]
    s=once(s,r'''   const benefits=`✅ Todas as taxas inclusas\n✅ Suporte durante toda a viagem\n✅ Suporte jurídico\n${bag}${extra}${obs?`✅ ${obs}\n`:''}`;''',
      r'''   const benefits=`✅ Todas as taxas inclusas\n✅ Suporte durante toda a viagem\n✅ Suporte jurídico\n${bagText}${optionalDetails}${obs?`✅ ${obs}\n`:''}`;''','benefícios da mensagem')
    s=once(s,'''   const discount=displayCompare>displaySale?`De: R$ ~${moneyPlain(displayCompare)}~\\n`:'';''',
      '''   const discount=saleKnown()&&displayCompare>displaySale?`De: R$ ~${moneyPlain(displayCompare)}~\\n`:'';''','comparação de preços')
    s=once(s,'''   const price=`👥 Valor total para ${people}.\\n\\n${discount}${paymentLines(false,paid,displaySale)}`;''',
      '''   let payText='';
   if(saleKnown()){
     if(msgShowAll?.checked && payState.interest){
       // Mantém à vista e sem juros quando selecionados; substitui somente
       // a linha com juros pelo desdobramento completo de parcelas.
       const current=paymentLines(false,paid,displaySale).trimEnd().split('\\n');
       payText=current.filter(line=>!line.includes('com juros')).join('\\n')+'\\n'+installmentList()+'\\n';
     }else payText=paymentLines(false,paid,displaySale);
   }
   const price=`👥 Valor total para ${people}.\\n${saleKnown()?'\\n'+discount+payText:''}`;''','preço sem lucro')
    # Do not repeat segments when section times already displayed from itinerary.
    s=once(s," const priceSwitches = document.querySelectorAll('[name=\"dbmMessagePriceMode\"]');", 
      " const priceSwitches = document.querySelectorAll('[name=\"dbmMessagePriceMode\"]');", 'radio bagagem') if False else s
    old=" showTimes.addEventListener('change',()=>{if(!editor.dataset.edited)editor.value=template()});"
    new=''' showTimes.addEventListener('change',()=>{if(!editor.dataset.edited)editor.value=template()});
 msgShowFare?.addEventListener('change',()=>{if(!editor.dataset.edited)editor.value=template()});
 msgShowAll?.addEventListener('change',()=>{if(msgShowAll.checked){payState.interest=true;syncEyes()}if(!editor.dataset.edited)editor.value=template()});
 function syncMessageMaxAvailability(){
   if(!msgMaxInstallments)return;
   const supported=typeof window.dbmFlightMaxInstallments==='function'?window.dbmFlightMaxInstallments():15;
   [...msgMaxInstallments.options].forEach(o=>o.disabled=Number(o.value)>supported);
   if(Number(msgMaxInstallments.value)>supported){
     const eligible=[...msgMaxInstallments.options].filter(o=>!o.disabled);
     if(eligible.length)msgMaxInstallments.value=eligible.at(-1).value;
   }
 }
 document.addEventListener('dbm:machine-fees-loaded',syncMessageMaxAvailability);
 syncMessageMaxAvailability();
 msgMaxInstallments?.addEventListener('change',()=>{
   // Só muda a apresentação; não salva nem altera a venda cadastrada.
   const max=Number(msgMaxInstallments.value);
   const supported=typeof window.dbmFlightMaxInstallments==='function'?window.dbmFlightMaxInstallments():15;
   const selected=Math.min(max,Math.max(1,supported));
   payIntN.value=String(selected);payIntTotal.value='';
   payState.interest=true;syncEyes();
   const oldMax=document.getElementById('dbmCompactMaxInstallments');
   if(oldMax && [...oldMax.options].some(op=>op.value===String(selected))){oldMax.value=String(selected);oldMax.dispatchEvent(new Event('change'));}
   if(!editor.dataset.edited)editor.value=template();
 });'''
    s=once(s,old,new,'atualização de controles')
    # the original preview intentionally avoids displaying the grand total on the card
    s=s.replace('`${intN}x de R$ ${m(intTotal/intN)} (total R$ ${m(intTotal)})`','`${intN}x de R$ ${m(intTotal/intN)}`')
    # Bust cache for the modified PNG export script.
    if '/static/js/flight-quote-art-20261102.js?v=20261102.4' not in s:
        old_url=next((f'/static/js/flight-quote-art-20261102.js?v=20261102.{v}'
                      for v in (3,2,1) if f'/static/js/flight-quote-art-20261102.js?v=20261102.{v}' in s),None)
        if not old_url:raise ValueError('Arte PNG: versão de cache inesperada.')
        s=once(s,old_url,'/static/js/flight-quote-art-20261102.js?v=20261102.4','cache da arte PNG')
    # Horários do itinerário novo e lista antiga não devem ser repetidos.
    s=s.replace('const flightInfo=selectedFlights.length && showTimes.checked?',
      'const flightInfo=selectedFlights.length && showTimes.checked && !itinerarySides.some(s=>(s.legs||[]).some(l=>l.departure||l.arrival))?')
    # JSON for artwork must never expose an undefined sale as cost.
    s=s.replace("'sale':quote.commercial.sale_value if quote.commercial and quote.commercial.sale_value is not none else quote.total,",
                "'sale':quote.commercial.sale_value if quote.commercial and quote.commercial.profit_value is not none else none,")
    # Existing page may use correct Python None rather than none. Use Jinja `none`.
    return s


def patch_art(s):
    s=once(s,"    fill('VALOR À VISTA',67,footerStart+51,'bold 21px Arial','#506f82');\n    fill(money(sale),68,footerStart+110,'bold 48px Arial','#087753');",
       "    const defined=data.sale!==null&&data.sale!==undefined&&Number.isFinite(Number(data.sale));\n    if(defined){\n      fill('VALOR À VISTA',67,footerStart+51,'bold 21px Arial','#506f82');\n      fill(money(sale),68,footerStart+110,'bold 48px Arial','#087753');\n    }",'arte sem preço não definido')
    s=once(s,"    if(pay.checked && chosenN>1 && chosenValue>0){",
       "    if(defined && pay.checked && chosenN>1 && chosenValue>0){",'arte parcelamento condicionado')
    s=once(s,"if(record.removed){data.sale=Number(data.cost||data.sale||0);data.installments=1;data.installment_value=0;}",
       "if(record.removed){data.sale=null;data.installments=1;data.installment_value=0;}", 'arte preço removido')
    return s


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--dry-run',action='store_true')
    args=p.parse_args()
    root=Path.cwd();package=Path(__file__).resolve().parent.parent
    needed=[NEW, RESULT, FLIGHT, ART]
    if any(not (root/n).is_file() for n in needed):
        print('ERRO: execute na raiz DBMILESXxx com as atualizações de itinerário e arte já instaladas.')
        return 2
    originals={name:(root/name).read_text(encoding='utf-8') for name in needed}
    backend=root/'app/routers/calculations.py'
    if not backend.is_file() or 'form.get("adults")' not in backend.read_text(encoding='utf-8'):
        print('INCOMPATÍVEL: o backend atual não reconhece adultos/crianças separados. Nenhum arquivo alterado.')
        return 1
    updates={}
    try:
        updates[NEW]=patch_new(originals[NEW])
        updates[RESULT]=patch_result(originals[RESULT])
        oldflight=originals[FLIGHT]
        expected=(package/'patches/restore/app/static/js/flight-itinerary-20261102.js').read_text(encoding='utf-8')
        if oldflight==expected:updates[FLIGHT]=oldflight
        elif hashlib.sha256(oldflight.encode()).hexdigest()==EXPECTED_JS_SHA:updates[FLIGHT]=expected
        else:raise ValueError('O JS do itinerário difere do Modelo 2. Envie a versão atual para adaptação segura.')
        updates[ART]=patch_art(originals[ART])
        if shutil.which('node'):
            for file in [FLIGHT,ART]:
                probe=subprocess.run(['node','--check','-'],input=updates[file],capture_output=True,text=True)
                if probe.returncode:raise ValueError(f'Sintaxe JavaScript inválida: {file}: {probe.stderr[:700]}')
    except ValueError as exc:
        print('INCOMPATÍVEL — nenhum arquivo alterado:',exc)
        return 1
    changed=[name for name in needed if updates[name]!=originals[name]]
    print('Compatibilidade OK. Arquivos alterados:',*changed,sep='\n • ')
    if args.dry_run:
        print('DRY-RUN OK. Nada foi modificado.')
        return 0
    if not changed:
        print('Já instalado. Nenhuma alteração repetida.')
        return 0
    backup=root/('backup_restauracao_controles_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S'))
    written=[]
    try:
        for name in changed:
            dest=backup/name;dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(root/name,dest)
        for name in changed:
            dest=root/name
            tmp=dest.with_suffix(dest.suffix+'.restore-tmp')
            tmp.write_text(updates[name],encoding='utf-8')
            tmp.replace(dest)
            written.append(name)
    except OSError as exc:
        for name in written:shutil.copy2(backup/name,root/name)
        print('ERRO: restauração do backup executada:',exc)
        return 2
    print('INSTALADO. Backup em',backup)
    return 0

if __name__=='__main__':sys.exit(main())
