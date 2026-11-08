"""Regressão: bagagens adicionais pertencem ao percurso, sem duplicação."""
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
 const itinerarySides=args.sides;
 const includedBags=JSON.stringify({_meta:args.meta||{}});
 const bagModeBox={hidden:null},selectedPriceMode=()=>args.mode;
 const bagQty=n=>`${n} ${n===1?'bagagem de 23kg inclusa':'bagagens de 23kg inclusas'}`;
 FUNCTION
 return {text:getBaggageLines(),hidden:bagModeBox.hidden};
}
const ida={key:'outbound',included_bags:'1',stops:['BSB','GRU'],legs:[{},{},{}]};
const volta={key:'return',included_bags:'1',legs:[{}]};
const legacy={passengers:2,extra:2,fare:'1',sides:[ida,volta],mode:'total'};
// Dois adicionais no percurso inteiro, e não dois adicionais em cada lado.
assert.equal(run(legacy).text,'✅ +6 bagagens de 23kg inclusas\n');
assert.equal(run({...legacy,sides:[{...ida,stops:[],legs:[{}]},volta]}).text,run(legacy).text);
assert.match(run({...legacy,mode:'per_person'}).text,/2 bagagens de 23kg inclusas adicionais no percurso inteiro/);
const oldLeg=run({...legacy,mode:'per_leg'}).text;
assert.match(oldLeg,/IDA: 2 bagagens/);
assert.match(oldLeg,/VOLTA: 2 bagagens/);
assert.match(oldLeg,/2 bagagens de 23kg inclusas adicionais no percurso inteiro/);
assert.doesNotMatch(oldLeg,/IDA: 4 bagagens/);
const separated={...legacy,meta:{extra_bags_outbound:1,extra_bags_return:1}};
assert.equal(run(separated).text,'✅ +6 bagagens de 23kg inclusas\n');
assert.match(run({...separated,mode:'per_leg'}).text,/IDA: 3 bagagens/);
assert.match(run({...separated,mode:'per_leg'}).text,/VOLTA: 3 bagagens/);
assert.match(run({...separated,mode:'per_person_leg'}).text,/VOLTA: 1 bagagem de 23kg inclusa por passageiro/);
const one={passengers:1,extra:0,fare:'0',sides:[{key:'one_way',included_bags:'0'}],mode:'total'};
assert.equal(run(one).text,'');assert.equal(run(one).hidden,true);
const multi={...legacy,sides:[{...ida,key:'segment_1'},{...volta,key:'segment_2'}],mode:'per_leg'};
assert.match(run(multi).text,/TRECHO 1/);assert.match(run(multi).text,/TRECHO 2/);
""".replace('FUNCTION',func)
    target=tmp_path/'bags.cjs'
    target.write_text(source,encoding='utf8')
    p=subprocess.run(['node',str(target)],capture_output=True,text=True)
    assert p.returncode==0,p.stderr

def test_arte_nao_multiplica_adicionais_por_sentido():
    art=(ROOT/'app/static/js/flight-quote-art-20261102.js').read_text(encoding='utf8')
    assert 'function artExtraForSide(side,index)' in art
    assert '},extra);' in art
    assert "(where==='all'||where===side.key)?extra:0" not in art
