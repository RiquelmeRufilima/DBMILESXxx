#!/usr/bin/env python3
"""Revisão incremental do itinerário: compacta, paradas opcionais, sem duplicar bagagem.

Rode na RAIZ do Codespaces:
 python scripts/aplicar_ajuste_paradas_compactas.py --dry-run
 python scripts/aplicar_ajuste_paradas_compactas.py

Confere hashes da versão anterior do complemento, cria backup, não toca Neon.
"""
from __future__ import annotations
import argparse
from datetime import datetime
import hashlib
from pathlib import Path
import shutil
import sys

FILES = {
 'app/static/js/flight-itinerary-20261102.js': 'b48ec728a7f13aa224b4703ab28f3f90d6f4b65f3edce639314ced03b4875689',
 'app/static/js/flight-quote-art-20261102.js': 'da021f1da8b6ce410a9e945b89c2627d5f9fd96345ea9eb4b5d9e9050a331d7f',
 'app/static/css/flight-itinerary-20261102.css': '1684128b4d9ad5757a170dfb8e5e0bdb6a000109fb537565823967f104fbb696',
 'app/services/flight_itinerary.py': '1f87dc17728ebdfe7f9effd420bafee4d2d15fc782d9fad3def3fa7d4e63edf9',
 'tests/test_flight_itinerary.py': 'd2958968d76851f3781ed5f8dd98a3e9f6fbe337f7cd58d8316b54e31aac43d9',
}
TEMPLATES = {
 'app/templates/calculations/new.html': (
    ('/static/css/flight-itinerary-20261102.css?v=20261102.1', '/static/css/flight-itinerary-20261102.css?v=20261102.2'),
    ('/static/js/flight-itinerary-20261102.js?v=20261102.1', '/static/js/flight-itinerary-20261102.js?v=20261102.2'),
 ),
 'app/templates/calculations/result.html': (
    ('/static/css/flight-itinerary-20261102.css?v=20261102.1', '/static/css/flight-itinerary-20261102.css?v=20261102.2'),
    ('/static/js/flight-quote-art-20261102.js?v=20261102.1', '/static/js/flight-quote-art-20261102.js?v=20261102.2'),
    ("'itinerary':inputs.get('_itinerary_v1', {}),", "'itinerary':inputs.get('_itinerary_v1', {}), 'extra_bags_quantity':quote.bags,"),
    ('Exibir preço das bagagens adicionais', 'Mostrar bagagens adicionais'),
 ),
}


def sha(data: bytes) -> str:
 return hashlib.sha256(data).hexdigest()


def run(dry_run: bool) -> int:
 root = Path.cwd()
 package = Path(__file__).resolve().parent.parent
 if not (root/'app/routers/calculations.py').is_file():
  print('ERRO: execute a partir da raiz do DBMILESXxx, não da pasta scripts.')
  return 2
 changes={}
 errors=[]
 for name, old_hash in FILES.items():
  target=root/name
  source=package/"patches"/"ajuste_paradas_compactas"/name
  if not source.is_file() or not target.is_file():
   errors.append(f'{name}: arquivo ausente no pacote ou na instalação anterior')
   continue
  actual=target.read_bytes(); desired=source.read_bytes()
  if actual == desired:continue
  if sha(actual) != old_hash:
   errors.append(f'{name}: versão diferente da atualização anterior; não será sobrescrita.')
   continue
  changes[name]=desired
 for name, replacements in TEMPLATES.items():
  target=root/name
  if not target.is_file():
   errors.append(f'{name}: não encontrado')
   continue
  original=target.read_text(encoding='utf-8')
  updated=original
  for old,new in replacements:
   if new in updated:
    continue
   if updated.count(old)!=1:
    errors.append(f'{name}: referência incompatível: {old}')
   else:updated=updated.replace(old,new,1)
  if updated!=original:changes[name]=updated.encode('utf-8')
 if errors:
  print('NENHUMA ALTERAÇÃO — compatibilidade não confirmada:')
  for error in errors:print(' •',error)
  print('Não copie arquivos manualmente sobre versões diferentes. Envie um ZIP atualizado do projeto para adaptação.')
  return 1
 print('Compatibilidade OK. Arquivos a atualizar:',len(changes))
 for name in changes:print(' +',name)
 if dry_run:
  print('DRY-RUN OK — nada foi modificado.')
  return 0
 if not changes:
  print('JÁ INSTALADO — nenhum arquivo precisou ser alterado.')
  return 0
 backup=root/('backup_ajuste_paradas_'+datetime.now().strftime('%Y%m%d_%H%M%S'))
 done=[]
 try:
  for name,new_content in changes.items():
   target=root/name
   saved=backup/name
   saved.parent.mkdir(parents=True,exist_ok=True)
   shutil.copy2(target,saved)
   tmp=target.with_name(target.name+'.dbm-update-tmp')
   tmp.write_bytes(new_content)
   tmp.replace(target)
   done.append(name)
 except OSError as exc:
  print('Falha ao instalar. Restaurando versões anteriores:',exc)
  for name in done:shutil.copy2(backup/name,root/name)
  return 2
 print('APLICAÇÃO CONCLUÍDA. Backup:',backup)
 print('Testar: python -m pytest tests/test_flight_itinerary.py -q')
 print('Depois: python -m pytest tests/ -q')
 return 0


def main() -> int:
 parser=argparse.ArgumentParser()
 parser.add_argument('--dry-run',action='store_true')
 args=parser.parse_args()
 return run(args.dry_run)

if __name__=='__main__':sys.exit(main())
