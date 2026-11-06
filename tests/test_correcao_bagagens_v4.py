"""Teste isolado: contabiliza bagagens por sentido, não por conexão."""
from pathlib import Path
import subprocess
import shutil
import pytest

ROOT=Path(__file__).resolve().parents[1]

def test_bagagens_tarifa_adicional_por_sentido_sem_multiplicar_conexoes(tmp_path):
    if not shutil.which('node'):
        pytest.skip('Node não disponível')
    content=(ROOT/'app/templates/calculations/result.html').read_text(encoding='utf8')
    start=content.index(' function getBaggageLines(){')
    end=content.index(' function itineraryExtraDetails(){',start)
    func=content[start:end]
    source=r"""const assert=require('node:assert/strict');
function run(args){
 const passengers=args.passengers, baggage=args.extra, fareIncluded=args.fare;
 const itinerarySides=args.sides,itineraryData={bags_applies_to:args.scope};
 const bagModeBox={hidden:null},selectedPriceMode=()=>args.mode;
 const bagQty=n=>`${n} ${n===1?'bagagem de 23kg inclusa':'bagagens de 23kg inclusas'}`;
 FUNCTION
 return {text:getBaggageLines(),hidden:bagModeBox.hidden};
}
const ida={key:'outbound',included_bags:'1',stops:['BSB','GRU'],legs:[{},{},{}]};
const volta={key:'return',included_bags:'1',legs:[{}]};
const full={passengers:2,extra:1,fare:'1',sides:[ida,volta],scope:'all',mode:'total'};
assert.equal(run(full).text,'✅ +3 bagagens de 23kg inclusas\n');
assert.equal(run({...full,sides:[{...ida,stops:[],legs:[{}]},volta]}).text,run(full).text);
assert.match(run({...full,mode:'per_person'}).text,/por passageiro/);
assert.match(run({...full,mode:'per_leg'}).text,/IDA: 3 bagagens/);
assert.match(run({...full,mode:'per_leg'}).text,/VOLTA: 3 bagagens/);
assert.match(run({...full,mode:'per_person_leg'}).text,/VOLTA: 1 bagagem de 23kg inclusa por passageiro/);
const onlyReturn={...full,scope:'return',mode:'total'};
assert.match(run(onlyReturn).text,/IDA: 2 bagagens/);
assert.match(run(onlyReturn).text,/VOLTA: 3 bagagens/);
const one={passengers:1,extra:0,fare:'0',sides:[{key:'one_way',included_bags:'0'}],scope:'all',mode:'total'};
assert.equal(run(one).text,'');assert.equal(run(one).hidden,true);
const multi={...full,sides:[{...ida,key:'segment_1'},{...volta,key:'segment_2'}],mode:'per_leg'};
assert.match(run(multi).text,/TRECHO 1/);assert.match(run(multi).text,/TRECHO 2/);
""".replace('FUNCTION',func)
    target=tmp_path/'bags.cjs'
    target.write_text(source,encoding='utf8')
    p=subprocess.run(['node',str(target)],capture_output=True,text=True)
    assert p.returncode==0,p.stderr

def test_arte_percurso_completo_em_cada_sentido():
    art=(ROOT/'app/static/js/flight-quote-art-20261102.js').read_text(encoding='utf8')
    # Adicional mostrado em CADA sentido (ou só no escolhido), apenas com a opção marcada.
    assert "if(extra>0&&checkbox.checked&&(where==='all'||where===side.key))" in art
    assert 'na cotação (sentido não especificado)' not in art
