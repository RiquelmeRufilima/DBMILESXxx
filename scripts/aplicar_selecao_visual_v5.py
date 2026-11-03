#!/usr/bin/env python3
"""Instala seleção visual de voos V5. Verifica TODOS os checksums antes de escrever.
Sem migrações, exclusões de dados ou substituição de arquivos divergentes.
"""
import argparse, hashlib, json, shutil, sys
from pathlib import Path
from datetime import datetime
ROOT=Path.cwd()
PKG=Path(__file__).resolve().parents[1]
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None

def main():
    parser=argparse.ArgumentParser(description='Seleção visual de voos V5 — instalador com backup')
    g=parser.add_mutually_exclusive_group(required=True)
    g.add_argument('--dry-run',action='store_true')
    g.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    if not (ROOT/'app/routers/calculations.py').is_file():sys.exit('ERRO: execute na raiz DBMILESXxx')
    manifest=json.loads((PKG/'patch_manifest.json').read_text(encoding='utf-8'))['files']
    tasks=[];conflicts=[]
    for item in manifest:
        rel=Path(item['path'])
        if rel.is_absolute() or '..' in rel.parts:sys.exit('Caminho inválido no manifesto')
        src=PKG/'payload'/rel;target=ROOT/rel
        if digest(src)!=item['updated_sha256']:sys.exit('ZIP incompleto/corrompido: '+str(rel))
        cur=digest(target)
        if cur==item['updated_sha256']:status='JÁ INSTALADO'
        elif cur==item['original_sha256']:status='APLICAR'
        else:status='INCOMPATÍVEL';conflicts.append(str(rel))
        print(f'{status:14} {rel}')
        if status=='APLICAR':tasks.append((rel,src,target))
    if conflicts:
        print('\nINCOMPATÍVEL: nenhum arquivo foi alterado. NÃO FORCE. Arquivos:')
        print('\n'.join(' - '+f for f in conflicts))
        return 2
    if args.dry_run:
        print(f'\nDRY-RUN OK: {len(tasks)} arquivo(s) pronto(s). Sem mudanças.')
        return 0
    if not tasks:
        print('\nJÁ INSTALADO. Nenhuma alteração.')
        return 0
    backup=ROOT/('backup_dbm_selecao_visual_v5_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    for rel,src,target in tasks:
        if target.is_file():
            saved=backup/rel;saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,saved)
    done=[]
    try:
        for rel,src,target in tasks:
            target.parent.mkdir(parents=True,exist_ok=True)
            temp=target.with_name(target.name+'.v5temp')
            shutil.copy2(src,temp);temp.replace(target)
            done.append((rel,target))
    except Exception:
        for rel,target in reversed(done):
            saved=backup/rel
            if saved.is_file():shutil.copy2(saved,target)
            else:target.unlink(missing_ok=True)
        raise
    print(f'\nV5 INSTALADA: {len(done)} arquivo(s). Backup: {backup}')
    print('Execute pytest ANTES do commit e do deploy. Nenhuma tabela ou registro foi apagado.')
    return 0
if __name__=='__main__':sys.exit(main())
