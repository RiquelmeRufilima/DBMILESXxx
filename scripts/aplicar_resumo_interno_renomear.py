#!/usr/bin/env python3
"""Patch conservador DBMILESX: resumo interno conciso + renomear plataforma.

Valida todas as âncoras ANTES de escrever. Faz backups. Não altera banco.
"""
from pathlib import Path
import argparse
import datetime
import shutil
import sys

FILES = (
    'app/templates/calculations/result.html',
    'app/templates/airlines/manage.html',
    'app/routers/airlines.py',
)

INTERNAL = r''' function internalTemplate(){
   // O custo é sempre o total calculado e já inclui custos adicionais.
   let inputs={};try{inputs=JSON.parse(includedBags)||{}}catch(_){inputs={}}
   const v=(inputs.values && typeof inputs.values==='object')?inputs.values:inputs;
   const numberOf=key=>{
     const raw=v[key];if(raw===null||raw===undefined||raw==='')return null;
     let text=String(raw).replace(/[R$\s]/g,'');
     if(text.includes(','))text=text.replace(/\./g,'').replace(',','.');
     const n=Number(text);return Number.isFinite(n)?n:null;
   };
   const lines=['📊 RESUMO INTERNO DA COTAÇÃO', '', `🧮 Tipo de cálculo: ${method}`];
   if(['systems','consolidators'].includes(catalogCategory))lines.push(`🏢 Plataforma: ${airline}`);
   else if(airline && !method.toLocaleLowerCase('pt-BR').includes(airline.toLocaleLowerCase('pt-BR')))lines.push(`✈️ Programa: ${airline}`);
   lines.push(`💰 Custo total: ${formatMoney(cost)}`);
   if(profitDefined){
     lines.push(`💵 Valor cobrado: ${formatMoney(sale)}`);
     lines.push(`📈 Lucro: ${formatMoney(profit)}`);
     lines.push(`📊 Margem: ${Number(margin||0).toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2})}%`);
   }else{
     lines.push('💵 Valor cobrado: não definido');
   }
   // Cartão: informações somente quando a condição de venda foi definida.
   if(profitDefined && payState.interest){
     const n=Math.max(2,Number(payIntN.value)||2), rate=machineRate(n);
     const cardTotal=interestTotal();
     const fee=cardTotal*rate/100;
     const realProfit=profit-(fee-(cardTotal-sale));
     const pct=rate.toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2});
     lines.push(`💳 Com juros ${n}x: taxa ${pct}% = ${formatMoney(fee)} (cliente paga) • lucro real ${formatMoney(realProfit)}`);
   }
   const isMiles=/milhas|smiles|pass|pontos|aadvantage|avios/i.test(method+' '+airline) ||
       (numberOf('milhas')!==null && numberOf('milheiro')!==null);
   if(isMiles){
     const miles=numberOf('milhas'),milheiro=numberOf('milheiro');
     if(miles!==null)lines.push(`✈️ Milhas: ${(miles*1000).toLocaleString('pt-BR',{maximumFractionDigits:0})}`);
     if(milheiro!==null)lines.push(`💠 Milheiro: ${formatMoney(milheiro)}`);
     for(const key of ['taxa','taxas_impostos','taxa_embarque','taxa_resgate','taxa_adicional']){
       const value=numberOf(key);
       if(value!==null)lines.push(`🧾 ${key.replaceAll('_',' ')}: ${formatMoney(value)}`);
     }
   }
   if(numberOf('desagio')!==null)lines.push(`🧮 Deságio: ${numberOf('desagio')}%`);
   if(Number(baggage)>0){
     const amount=Number(baggage);
     let bagLine=`🧳 Bagagem adicional: ${amount} ${amount===1?'unidade':'unidades'}`;
     // Só mostra valor máximo se esse dado for realmente informado no cálculo.
     const maxBag=numberOf('bagagem_valor_maximo')??numberOf('bagagem_maxima');
     if(maxBag!==null)bagLine+=` • valor máximo: ${formatMoney(maxBag)}`;
     lines.push(bagLine);
   }
   if(skipRecord){
     lines.push('⚡ Tipo: SKIP');
     const flown=(Array.isArray(segments)?segments:[]).filter(row=>row.status==='flown');
     for(const row of flown){
       const routeName=row.route||`${row.origin||'?'} → ${row.destination||'?'}`;
       lines.push(`✈️ Trecho ${row.segment||''}: ${routeName}`.trim());
       if(Array.isArray(row.schedules)&&row.schedules.length)lines.push(...row.schedules);
       else if(row.display_date)lines.push(row.display_date);
     }
   }
   const obs=note.value.trim();if(obs)lines.push(`📝 ${obs}`);
   return lines.join('\n');
 }
'''

RENAME_ROUTE = '''@router.post("/{airline_id}/rename")
async def rename_catalog_item(airline_id: int, request: Request, db: Session = Depends(get_db)):
    """Renomeia apenas cadastros personalizados do próprio usuário/empresa."""
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    airline = db.get(Airline, airline_id)
    if airline is None or not _can_manage(user, airline):
        flash(request, "Você não tem permissão para renomear este cadastro.", "error")
        return RedirectResponse("/airlines", status_code=303)
    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada. Atualize a página e tente novamente.", "error")
        return RedirectResponse(f"/airlines/{airline_id}", status_code=303)
    name = " ".join(str(form.get("name") or "").split()).strip()
    if not 2 <= len(name) <= 180:
        flash(request, "O nome deve ter de 2 a 180 caracteres.", "error")
        return RedirectResponse(f"/airlines/{airline_id}", status_code=303)
    # Evita nomes duplicados na mesma empresa ou entre itens do mesmo usuário.
    others = db.scalars(
        select(Airline).where(Airline.id != airline_id, Airline.active.is_(True), _visibility(user))
    ).all()
    if any(item.name.strip().casefold() == name.casefold() for item in others):
        flash(request, "Já existe um cadastro com esse nome.", "error")
        return RedirectResponse(f"/airlines/{airline_id}", status_code=303)
    airline.name = name
    # Não alterar slug ou IDs: fórmulas e histórico continuam vinculados.
    db.commit()
    flash(request, "Nome atualizado com sucesso.", "success")
    return RedirectResponse(f"/airlines/{airline_id}", status_code=303)


'''

RENAME_PANEL = '''{% if can_manage and not airline.builtin %}
<section class="panel" style="margin-bottom:16px" id="rename-catalog-item">
  <div class="panel-heading"><div><span class="eyebrow">IDENTIFICAÇÃO</span><h2>Renomear cadastro</h2><p>Atualiza apenas o nome exibido. As regras e o histórico continuam intactos.</p></div></div>
  <form method="post" action="/airlines/{{ airline.id }}/rename" class="form-stack">
    <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
    <label>Novo nome<input name="name" value="{{ airline.name }}" maxlength="180" minlength="2" required></label>
    <div class="form-actions"><a class="secondary-button" href="/airlines">Voltar</a><button class="primary-button" type="submit">Salvar novo nome</button></div>
  </form>
</section>
{% endif %}
'''


def only_once_replace(text, before, after, label):
    if before not in text:
        if after in text:
            return text, False
        raise RuntimeError(f'Âncora não encontrada em {label}. Versão diferente; nenhum arquivo foi alterado.')
    if text.count(before) != 1:
        raise RuntimeError(f'Âncora ambígua em {label}; nenhum arquivo foi alterado.')
    return text.replace(before, after, 1), True


def patch_result(raw):
    s=raw
    if 'function internalTemplate(){' not in s:
        if 'Custo total: ${formatMoney(cost)}' in s: return s
        raise RuntimeError('A função internalTemplate não foi localizada.')
    a=s.index(' function internalTemplate(){')
    b=s.find('\n editor.value=template();',a)
    if b<0: raise RuntimeError('Final de internalTemplate não encontrado: não aplique sobre esta versão.')
    s=s[:a]+INTERNAL+s[b:]
    marker=' const method = {{ (quote.calculation_type.name if quote.calculation_type else \'Não informado\')|tojson }};'
    addition="\n let profitDefined = {{ (quote.commercial is not none and quote.commercial.profit_value is not none)|tojson }};"
    if addition.strip() not in s:s,_=only_once_replace(s,marker,marker+addition,'result:lucro')
    marker2=" const agency = {{ (quote.user.company.name if quote.user and quote.user.company else 'Não informada')|tojson }};"
    addition2="\n const catalogCategory = {{ (quote.airline.catalog_category if quote.airline else 'airlines')|tojson }};"
    if addition2.strip() not in s:s,_=only_once_replace(s,marker2,marker2+addition2,'result:categoria')
    # Variações do modal: ausência de lucro não deve virar valor de venda interno.
    if('if(item.removed){sale=cost;profit=0;commercialMeta={};' in s):
        s=s.replace('if(item.removed){sale=cost;profit=0;commercialMeta={};',
                    'if(item.removed){sale=cost;profit=0;profitDefined=false;commercialMeta={};',1)
    elif 'if(item.removed){sale=cost;profit=0;profitDefined=false;commercialMeta={};' in s: pass
    elif 'if(item.removed){' in s:raise RuntimeError('Evento do modal de lucro mudou. Revisão manual necessária.')
    if 'profit=Number(item.profit_value||0);profitDefined=' in s: pass
    elif 'profit=Number(item.profit_value||0);' in s:
        s=s.replace('profit=Number(item.profit_value||0);',
                    'profit=Number(item.profit_value||0);profitDefined=item.profit_value!==null&&item.profit_value!==undefined&&item.profit_value!=="";',1)
    elif 'profitDefined=item.profit_value!==null' in s: pass
    elif 'dbm:commercial-saved' in s:raise RuntimeError('Atualização de lucro mudou. Revisão manual necessária.')
    return s


def patch_manage(s):
    marker='<div class="action-cluster">'
    add='<div class="action-cluster">\n    <a class="secondary-button" href="/airlines">← Voltar</a>'
    if 'id="rename-catalog-item"' not in s:
        s,_=only_once_replace(s,marker,add,'manage:voltar')
        anchor='{% if can_manage %}\n<section class="panel" style="margin-bottom:16px">'
        s,_=only_once_replace(s,anchor,RENAME_PANEL+anchor,'manage:renomear')
    return s


def patch_router(s):
    anchor='@router.post("/{airline_id}/profile")'
    if 'async def rename_catalog_item(' not in s:
        s,_=only_once_replace(s,anchor,RENAME_ROUTE+anchor,'router:renomear')
    return s


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--dry-run',action='store_true')
    args=p.parse_args()
    root=Path.cwd()
    if not all((root/f).is_file() for f in FILES):
        sys.exit('Execute na raiz do DBMILESXxx. Arquivos esperados não encontrados.')
    old={f:(root/f).read_text(encoding='utf-8') for f in FILES}
    try:
        new={FILES[0]:patch_result(old[FILES[0]]),FILES[1]:patch_manage(old[FILES[1]]),FILES[2]:patch_router(old[FILES[2]])}
        # Compilação prévia garante que o Python gerado é válido.
        compile(new[FILES[2]],FILES[2],'exec')
    except Exception as exc:
        sys.exit(f'INCOMPATÍVEL: {exc}')
    changed=[f for f in FILES if new[f]!=old[f]]
    if args.dry_run:
        print('DRY-RUN OK; nenhum arquivo alterado.')
        print('Arquivos a alterar:',*changed,sep='\n - ')
        return
    if not changed:
        print('Atualização já aplicada; nada para modificar.')
        return
    backup=root/f'backup_resumo_interno_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}'
    for f in changed:
        destination=backup/f;destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(root/f,destination)
    try:
        for f in changed:(root/f).write_text(new[f],encoding='utf-8')
    except Exception:
        for f in changed:shutil.copy2(backup/f,root/f)
        raise
    print('Atualização aplicada. Backup em:',backup)
    print('Alterados:',*changed,sep='\n - ')

if __name__=='__main__':main()
