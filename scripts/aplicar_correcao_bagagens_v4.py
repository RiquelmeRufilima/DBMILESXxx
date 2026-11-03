#!/usr/bin/env python3
"""Aplica somente a correção de CONTAGEM da bagagem no resultado e na arte.

Não toca em fórmulas, backend, banco nem calculadora; evita substituir arquivos
com mudanças recentes. Execute --dry-run e, depois, --apply.
"""
from __future__ import annotations
import argparse
import datetime
import json
import shutil
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PATCH=json.loads((Path(__file__).with_name('bagagem_patch_v4.json')).read_text(encoding='utf-8'))
CHANGES=[
    ('app/templates/calculations/result.html','result_original','result_updated'),
    ('app/static/js/flight-quote-art-20261102.js','art_original','art_updated'),
]

def main():
    parser=argparse.ArgumentParser(description='Corrige mensagem de bagagens sem alterar valores da cotação')
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--dry-run',action='store_true',help='Confere todos os arquivos sem escrever')
    mode.add_argument('--apply',action='store_true',help='Aplica somente após verificar tudo')
    args=parser.parse_args()
    changes=[]
    errors=[]
    for relative,old_key,new_key in CHANGES:
        path=ROOT/relative
        if not path.is_file():
            errors.append(f'{relative}: arquivo ausente')
            continue
        original=path.read_text(encoding='utf-8')
        old,new=PATCH[old_key],PATCH[new_key]
        if old in original and new not in original:
            changes.append((path, original, original.replace(old,new,1)))
        elif new in original and old not in original:
            print(f'JÁ CORRIGIDO: {relative}')
        else:
            errors.append(f'{relative}: conteúdo diferente da versão V4; não alterado')
    if errors:
        print('INCOMPATÍVEL — nenhum arquivo alterado.')
        for error in errors:print(' • '+error)
        sys.exit(2)
    if args.dry_run:
        print('DRY-RUN OK — nenhum arquivo alterado.')
        for path,*_ in changes:print(' • Atualização disponível:',path.relative_to(ROOT))
        return
    if not changes:
        print('ATUALIZAÇÃO JÁ APLICADA — nenhum arquivo alterado.')
        return
    backup=ROOT/('backup_bagagem_v4_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S'))
    backup.mkdir(parents=True,exist_ok=False)
    for path,old,_ in changes:
        saved=backup/path.relative_to(ROOT)
        saved.parent.mkdir(parents=True,exist_ok=True)
        saved.write_text(old,encoding='utf-8')
    try:
        for path,_,updated in changes:
            temp=path.with_name(path.name+'.tmp_bag_v4')
            temp.write_text(updated,encoding='utf-8')
            temp.replace(path)
    except Exception:
        for path,original,_ in changes:path.write_text(original,encoding='utf-8')
        raise
    print('CORREÇÃO APLICADA. Backup:',backup)
    for path,*_ in changes:print(' •',path.relative_to(ROOT))
    print('Teste: python -m pytest tests/test_restauracao_controles.py tests/test_correcao_bagagens_v4.py -q')

if __name__=='__main__': main()
