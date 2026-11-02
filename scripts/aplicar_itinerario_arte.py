#!/usr/bin/env python3
"""Incremental/abort-on-mismatch: itinerário e arte, preservando outras correções.

Run from the DBMILESX project root, e.g.
    python scripts/aplicar_itinerario_arte.py --dry-run
    python scripts/aplicar_itinerario_arte.py
"""
from __future__ import annotations

import argparse
import ast
import datetime
from pathlib import Path
import shutil
import sys

ROOT = Path.cwd()
MODULE_NAME = "dbm_itinerary_20261102"
ASSETS = [
    "app/services/flight_itinerary.py",
    "app/static/js/flight-itinerary-20261102.js",
    "app/static/js/flight-quote-art-20261102.js",
    "app/static/css/flight-itinerary-20261102.css",
    "tests/test_flight_itinerary.py",
]
ROUTER = "app/routers/calculations.py"
CALC = "app/templates/calculations/new.html"
RESULT = "app/templates/calculations/result.html"


class Incompatible(RuntimeError):
    pass


def replace_once(src: str, old: str, new: str, where: str) -> str:
    if new in src:
        return src
    count = src.count(old)
    if count != 1:
        raise Incompatible(f"{where}: esperava 1 ocorrência de {old[:80]!r}; encontrei {count}. Nenhuma mudança aplicada.")
    return src.replace(old, new, 1)


def update_router(source: str) -> str:
    source = replace_once(
        source,
        "from ..services.calculator import CalculationResult, calculate\n",
        "from ..services.calculator import CalculationResult, calculate\nfrom ..services.flight_itinerary import normalize_itinerary\n",
        ROUTER,
    )
    source = replace_once(
        source,
        '    values["_flight_details"] = flight_details\n',
        '''    values["_flight_details"] = flight_details
    # Opcional: todos os campos por conexão ficam no input_json da própria cotação.
    # Se a versão atual do formulário não enviar os campos (JS desativado),
    # preserva os dados anteriores na edição para evitar apagá-los.
    submitted_itinerary = form.get("itinerary_json")
    if submitted_itinerary is None and existing_option is not None:
        values["_itinerary_v1"] = existing_input.get("_itinerary_v1", {})
    else:
        values["_itinerary_v1"] = normalize_itinerary(submitted_itinerary, selected_segments)
''', ROUTER,
    )
    source = replace_once(
        source,
        '''    quote = existing_option
    if quote is None:
''',
        '''    # O custo de bagagens pagas só é somado se o agente marcar essa
    # opção expressamente. Sem a marcação, as fórmulas atuais não mudam.
    # A venda adicional é informativa; o preço ao cliente segue em Editar lucro.
    itinerary_extra = values.get("_itinerary_v1", {})
    if (not is_skip_record and isinstance(itinerary_extra, dict)
            and itinerary_extra.get("charge_extra_bags") is True):
        extra_baggage_cost = round(float(itinerary_extra.get("extra_bags_cost") or 0), 2)
        if extra_baggage_cost > 0:
            result.total = round(result.total + extra_baggage_cost, 2)
            result.baggage_total = round(result.baggage_total + extra_baggage_cost, 2)
            result.breakdown["bagagens_adicionais_itinerario"] = extra_baggage_cost

    quote = existing_option
    if quote is None:
''', ROUTER,
    )
    ast.parse(source)
    return source


def update_calc(source: str) -> str:
    source = replace_once(
        source,
        '''      <script type="application/json" id="partnerAirlineOptionsJson">''',
        '''      <input type="hidden" name="itinerary_json" id="dbmItineraryJson" value="">
      <script type="application/json" id="dbmItineraryInitial">{{ (field_values.get('_itinerary_v1', {}) if field_values is defined else {})|tojson }}</script>
      <link rel="stylesheet" href="/static/css/flight-itinerary-20261102.css?v=20261102.1">
      <script defer src="/static/js/flight-itinerary-20261102.js?v=20261102.1"></script>
      <script type="application/json" id="partnerAirlineOptionsJson">''', CALC,
    )
    return source


def update_result(source: str) -> str:
    source = replace_once(
        source,
        '''  <label for="quoteClientMessage"><strong>Mensagem para o cliente</strong></label>''',
        '''  <details class="dbm-compact-installments" id="dbmCompactInstallments">
    <summary>💳 Parcelamento para o cliente — ver até o limite escolhido</summary>
    <label>Mostrar até <select id="dbmCompactMaxInstallments">
      {% for n in range(1, 25) %}<option value="{{ n }}" {% if n == 12 %}selected{% endif %}>{{ n }}x</option>{% endfor %}
    </select></label>
    <div class="dbm-compact-hint">Valores pela tabela de taxas da máquina da cotação, considerando a entrada Pix quando cadastrada. Não mostra o total do cartão.</div>
    <div id="dbmCompactInstallmentsList" aria-live="polite"></div>
  </details>
  <label for="quoteClientMessage"><strong>Mensagem para o cliente</strong></label>''', RESULT,
    )
    source = replace_once(
        source,
        '''</section>
<style>
 .dbm-share-options''',
        '''  <section class="dbm-art-section" id="dbmFlightArtArea" aria-label="Arte da cotação">
    <div class="dbm-art-head"><h3>✈️ Arte da Cotação</h3><span>Imagem PNG • opcional</span></div>
    <p class="dbm-art-note">Prévia ilustrada a partir dos dados da cotação, sem custo de geração e sem mostrar custos ou lucros internos.</p>
    <div class="dbm-art-buttons">
      <label><input type="checkbox" id="dbmArtShowBagPrices"> Exibir preço das bagagens adicionais</label>
      <label><input type="checkbox" id="dbmArtShowPayments" checked> Exibir parcelas salvas</label>
    </div>
    <canvas class="dbm-art-preview" width="1080" height="1300" role="img" aria-label="Prévia da arte da cotação"></canvas>
    <div class="dbm-art-buttons">
      <button class="primary-button small-button" type="button" id="dbmArtGenerate">Atualizar arte</button>
      <button class="secondary-button small-button" type="button" id="dbmArtDownload">Baixar PNG</button>
      <button class="secondary-button small-button" type="button" id="dbmArtShare">Compartilhar</button>
    </div>
  </section>
  <script id="dbmFlightArtData" type="application/json">{{ {'quote_id':quote.id,
       'name':quote.trip.client_name if quote.trip and quote.trip.client_name else quote.quote_name,
       'origin':quote.origin,'destination':quote.destination,
       'airline':quote.airline.name if quote.airline else '',
       'itinerary':inputs.get('_itinerary_v1', {}),
       'sale':quote.commercial.sale_value if quote.commercial and quote.commercial.sale_value is not none else quote.total,
       'cost':quote.total,
       'installments':quote.commercial.card_installments if quote.commercial else 1,
       'installment_value':quote.commercial.card_installment_value if quote.commercial else 0}|tojson }}</script>
  <link rel="stylesheet" href="/static/css/flight-itinerary-20261102.css?v=20261102.1">
  <script defer src="/static/js/flight-quote-art-20261102.js?v=20261102.1"></script>
</section>
<style>
 .dbm-share-options''', RESULT,
    )
    # Reuse the exact machine fee table from the existing messaging module;
    # do not invent rates or call Neon from the new feature.
    source = replace_once(
        source,
        " const payFreeN=document.getElementById('dbmPayFreeN');",
        ''' // Compartilha a tabela vigente de parcelas com a prévia compacta.
 window.dbmFlightMaxInstallments = function(){
   const table=machineTables.find(t=>t.name===commercialMeta.machine_name)||machineTables[0];
   const opts=Object.keys(table?.rates||{}).map(Number).filter(n=>n>=1&&n<=24);
   return opts.length?Math.max(...opts):1;
 };
 window.dbmFlightPaymentPreview = function(n){
   n=Math.max(1,Math.min(24,Number(n)||1));
   const entry=Math.max(0,Number(commercialMeta.entry_amount||0));
   const financed=Math.max(0,sale-entry);
   const rate=n>1?machineRate(n):0;
   return rate>=0&&rate<100?Math.round(financed/(1-rate/100)*100)/(100*n):null;
 };
 const payFreeN=document.getElementById('dbmPayFreeN');''', RESULT,
    )
    # Remove the unwanted card grand-total from the visible installment preview.
    source = source.replace("`${intN}x de R$ ${m(intTotal/intN)} (total R$ ${m(intTotal)})`",
                            "`${intN}x de R$ ${m(intTotal/intN)}`")
    # Notify the compact panel when asynchronously loaded machine fees change.
    if "machineTables=d.tables;refreshClient();document.dispatchEvent(new Event('dbm:machine-fees-loaded'));" not in source:
        source = source.replace('machineTables=d.tables;refreshClient();',
                                "machineTables=d.tables;refreshClient();document.dispatchEvent(new Event('dbm:machine-fees-loaded'));")
    return source


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument('--dry-run',action='store_true',help='Verificar compatibilidade sem alterar arquivos')
    args=parser.parse_args()
    here=Path(__file__).resolve().parent.parent
    if not (ROOT/'app/routers/calculations.py').is_file():
        print('ERRO: execute na pasta raiz do DBMILESX (onde existe app/routers/calculations.py).')
        return 2
    try:
        originals = {name:(ROOT/name).read_text(encoding='utf-8') for name in (ROUTER,CALC,RESULT)}
        modified = {ROUTER:update_router(originals[ROUTER]),
                    CALC:update_calc(originals[CALC]),
                    RESULT:update_result(originals[RESULT])}
        for name in ASSETS:
            if not (here/name).is_file():
                raise Incompatible(f'Pacote incompleto: falta {name}')
        for name in ASSETS:
            target=ROOT/name
            if target.exists() and target.read_bytes() != (here/name).read_bytes():
                raise Incompatible(f'Arquivo já existe e difere: {name}. Compare antes de substituir.')
    except (Incompatible,OSError,SyntaxError) as exc:
        print('SEM ALTERAÇÕES —',exc)
        return 1
    changed=[name for name in (ROUTER,CALC,RESULT) if modified[name]!=originals[name]]
    assets=[name for name in ASSETS if not (ROOT/name).exists()]
    print('Compatibilidade OK. Arquivos a modificar:', ', '.join(changed) or 'nenhum')
    print('Novos arquivos:', ', '.join(assets) or 'nenhum')
    if args.dry_run:
        print('DRY-RUN OK — nenhum arquivo alterado.')
        return 0
    backups=ROOT/f'backup_itinerario_arte_{datetime.datetime.now():%Y%m%d_%H%M%S}'
    try:
        if changed:
            for name in changed:
                target=backups/name
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(ROOT/name,target)
        for name in assets:
            target=ROOT/name;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(here/name,target)
        for name in changed:
            (ROOT/name).write_text(modified[name],encoding='utf-8')
    except OSError as exc:
        print('FALHA durante cópia. Restaurando arquivos conhecidos:',exc)
        for name in changed:
            saved=backups/name
            if saved.exists(): shutil.copy2(saved,ROOT/name)
        return 2
    print('INSTALAÇÃO OK. Backup:',backups if changed else 'não necessário')
    print('Teste: python -m pytest tests/test_flight_itinerary.py -q')
    return 0


if __name__=='__main__':sys.exit(main())
