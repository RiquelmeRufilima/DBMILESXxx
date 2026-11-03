#!/usr/bin/env python3
"""Atualização incremental e segura de horários, salvamento e mensagens DBMILESX.

Primeiro verifica TODOS os checksums. Não instala versão incompatível.
Cria backup dos originais antes de qualquer alteração.
"""
from pathlib import Path
from hashlib import sha256
import argparse
import json
import shutil
from datetime import datetime
import sys

PACKAGE_ROOT=Path(__file__).resolve().parents[1]
PROJECT_ROOT=Path.cwd()
MANIFEST=PACKAGE_ROOT/'patch_manifest.json'
PAYLOAD=PACKAGE_ROOT/'payload'

def sha(path):
    return sha256(path.read_bytes()).hexdigest() if path.is_file() else None

def main():
    parser=argparse.ArgumentParser(description='Aplicar correção V4 sem sobrescrever versões divergentes.')
    parser.add_argument('--dry-run',action='store_true',help='Só verifica. Não altera nada.')
    parser.add_argument('--apply',action='store_true',help='Aplica após verificar compatibilidade.')
    args=parser.parse_args()
    if not args.dry_run and not args.apply:
        parser.error('Escolha --dry-run ou --apply')
    if not (PROJECT_ROOT/'app'/'routers'/'calculations.py').exists():
        sys.exit('ERRO: execute a partir da RAIZ de DBMILESXxx.')
    if not MANIFEST.exists():sys.exit('ERRO: patch_manifest.json não encontrado. Extraia o ZIP completo.')
    entries=json.loads(MANIFEST.read_text())['files']
    states=[]
    conflicts=[]
    for entry in entries:
        rel=Path(entry['path'])
        if rel.is_absolute() or '..' in rel.parts:sys.exit('Manifest inválido.')
        target=PROJECT_ROOT/rel
        payload=PAYLOAD/rel
        if sha(payload)!=entry['updated_sha256']:
            sys.exit(f'Arquivo de atualização corrompido: {rel}')
        current=sha(target)
        if current==entry['updated_sha256']:status='ATUALIZADO'
        elif current==entry['original_sha256']:status='APLICAR'
        else:
            status='INCOMPATÍVEL'
            conflicts.append(str(rel))
        states.append((entry,target,payload,status))
    print('\n'.join(f'{state:13} {entry["path"]}' for entry,_,_,state in states))
    if conflicts:
        print('\nINCOMPATÍVEL: nenhum arquivo alterado. Seu projeto tem diferenças em:')
        print('\n'.join('  - '+item for item in conflicts))
        sys.exit(2)
    pending=[(entry,target,payload) for entry,target,payload,status in states if status=='APLICAR']
    if not pending:
        print('\nJÁ INSTALADO. Nenhum arquivo precisa mudar.')
        return
    if args.dry_run:
        print(f'\nDRY-RUN OK: {len(pending)} arquivo(s) pronto(s). Nada alterado.')
        return
    backup=PROJECT_ROOT/('backup_dbm_horarios_v4_'+datetime.now().strftime('%Y%m%d_%H%M%S'))
    done=[]
    try:
        for entry,target,payload in pending:
            if target.is_file():
                target_backup=backup/entry['path'];target_backup.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(target,target_backup)
        for entry,target,payload in pending:
            target.parent.mkdir(parents=True,exist_ok=True)
            temp=target.with_name(target.name+'.dbm-v4-tmp')
            shutil.copy2(payload,temp)
            temp.replace(target)
            done.append((entry,target))
    except Exception:
        for entry,target in reversed(done):
            saved=backup/entry['path']
            if saved.is_file():shutil.copy2(saved,target)
            else:target.unlink(missing_ok=True)
        raise
    print(f'\nINSTALAÇÃO CONCLUÍDA: {len(done)} arquivo(s).')
    print(f'Backup: {backup}')
    print('Agora execute os testes. Não publique se falharem.')

if __name__=='__main__':main()
