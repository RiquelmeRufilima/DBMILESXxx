"""Regressions: DBMILESX legacy data preserved in new optional UI."""
from __future__ import annotations
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]


def read(rel):return (ROOT/rel).read_text(encoding='utf-8')


def test_passageiros_adultos_criancas_bebes_separados():
    page=read('app/templates/calculations/new.html')
    for ident in ('paxAdults','paxChildren','paxTotal'):
        assert f'id="{ident}"' in page
    assert 'name="adults"' in page and 'name="children"' in page and 'name="babies"' in page
    assert 'name="passengers"' in page


def test_tarifa_e_classe_reaproveitam_listas_originais():
    js=read('app/static/js/flight-itinerary-20261102.js')
    assert 'data-side-field="fare">${optionsLike(fareSelect,fare)}</select>' in js
    assert 'data-side-field="cabin">${optionsLike(cabinSelect,cabin)}</select>' in js
    assert "optionsLike(bagSelect,bags)" in js
    assert 'data-side-field="fare" type="text"' not in js


def test_configuracoes_mensagem_disponiveis():
    html=read('app/templates/calculations/result.html')
    for value in ('total','per_person','per_leg','per_person_leg'):
        assert f'value="{value}"' in html
    for ident in ('dbmMessageMaxInstallments','dbmMessageShowAllInstallments','dbmMessageShowTimes','dbmMessageShowFare'):
        assert f'id="{ident}"' in html
    assert 'const bagText=getBaggageLines()' in html
    assert "const price=`👥 Valor total para ${people}" in html
    assert "if(saleKnown())" in html


def test_arte_sem_lucro_nao_usa_custo_como_venda():
    html=read('app/templates/calculations/result.html')
    js=read('app/static/js/flight-quote-art-20261102.js')
    assert "'sale':quote.commercial.sale_value if quote.commercial and quote.commercial.profit_value is not none else none" in html
    assert 'if(record.removed){data.sale=null' in js
    assert 'if(defined){' in js


def test_templates_jinja_validos():
    from jinja2 import Environment
    env=Environment()
    for name in ['new.html','result.html']:
        env.parse(read('app/templates/calculations/'+name))


def test_javascript_sintaxe_valida(tmp_path):
    if not shutil.which('node'):pytest.skip('Node não instalado neste ambiente')
    paths=['app/static/js/flight-itinerary-20261102.js','app/static/js/flight-quote-art-20261102.js']
    for p in paths:
        proc=subprocess.run(['node','--check',str(ROOT/p)],capture_output=True,text=True)
        assert proc.returncode==0,proc.stderr
    result=read('app/templates/calculations/result.html')
    m=re.search(r'<script>\s*\(\(\) => \{\s*const note = document.getElementById\(\'quoteObservations\'\);.*?</script>',result,re.S)
    assert m is not None
    embedded=re.sub(r'\{\{.*?\}\}','null',m.group(0)[8:-9],flags=re.S)
    f=tmp_path/'result.js';f.write_text(embedded,encoding='utf-8')
    proc=subprocess.run(['node','--check',str(f)],capture_output=True,text=True)
    assert proc.returncode==0,proc.stderr


def test_bagagem_franquia_mais_adicional_sem_duplicar_conexoes(tmp_path):
    if not shutil.which('node'):pytest.skip('Node não instalado neste ambiente')
    result=read('app/templates/calculations/result.html')
    start=result.index('function getBaggageLines(){')
    end=result.index(' function itineraryExtraDetails(){',start)
    source=result[start:end]
    probe=r'''const assert=require('node:assert/strict');
function calculate(opts){
  const passengers=opts.passengers,baggage=opts.extra,fareIncluded=opts.fare;
  const itinerarySides=opts.sides,itineraryData={bags_applies_to:opts.where};
  const bagModeBox={hidden:null};
  const selectedPriceMode=()=>opts.mode;
  const bagQty=n=>`${n} ${n===1?'bagagem de 23kg inclusa':'bagagens de 23kg inclusas'}`;
  FUNC
  const result=getBaggageLines();
  return {result,hidden:bagModeBox.hidden};
}
const twoLegs=[{key:'outbound',included_bags:'1',stops:['BSB'],legs:[{},{},{}]},{key:'return',included_bags:'1',legs:[{}]}];
assert.match(calculate({passengers:2,extra:1,fare:'1',sides:twoLegs,where:'all',mode:'total'}).result,/\+3 bagagens/);
assert.ok(!calculate({passengers:2,extra:1,fare:'1',sides:twoLegs,where:'all',mode:'total'}).result.includes('+5'));
assert.match(calculate({passengers:2,extra:1,fare:'1',sides:twoLegs,where:'all',mode:'per_person'}).result,/por passageiro/);
assert.match(calculate({passengers:2,extra:1,fare:'1',sides:twoLegs,where:'return',mode:'per_leg'}).result,/VOLTA/);
assert.match(calculate({passengers:2,extra:1,fare:'1',sides:twoLegs,where:'return',mode:'per_person_leg'}).result,/por passageiro/);
const none=calculate({passengers:1,extra:0,fare:'0',sides:[{key:'one_way',included_bags:'0'}],where:'all',mode:'total'});
assert.equal(none.result,'');assert.equal(none.hidden,true);
'''.replace('FUNC',source)
    f=tmp_path/'bags.cjs';f.write_text(probe,encoding='utf-8')
    proc=subprocess.run(['node',str(f)],capture_output=True,text=True)
    assert proc.returncode==0,proc.stderr
