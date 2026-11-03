#!/usr/bin/env python3
"""DBMILESX — correção de painel de mensagens e alternativas de horário.

Sem dependências adicionais para instalar. Pré-verifica todos os arquivos e
não sobrescreve um checkout desconhecido. Não toca no Neon, MFA ou fórmulas.
"""
from __future__ import annotations
import argparse, datetime, hashlib, json, shutil, subprocess, sys
from pathlib import Path

ROOT=Path.cwd()
PACK=Path(__file__).resolve().parents[1]
MANIFEST=PACK/'patches/manifest.json'
NEW_FILES={
 'app/static/css/dbm-message-settings-20261103.css',
 'tests/test_opcoes_voos_mensagem_v3.py',
}


def apply_all(dry_run=False):
    spec=json.loads(MANIFEST.read_text(encoding='utf-8'))
    edits={}; failures=[]
    for name,hunks in spec['changes'].items():
        target=ROOT/name
        if not target.exists():
            failures.append(f'{name}: arquivo não encontrado');continue
        original=target.read_text(encoding='utf-8')
        updated=original
        for i,h in enumerate(hunks,1):
            before,after=h['before'],h['after']
            if updated.count(before)==1:
                updated=updated.replace(before,after,1)
            elif after in updated and before not in updated:
                pass  # Trecho já instalado
            else:
                failures.append(f'{name}, parte {i}: versão diferente da esperada')
        if updated!=original:edits[name]=updated.encode('utf-8')
    for name in NEW_FILES:
        src=PACK/'patches/novos'/name
        target=ROOT/name
        if not src.is_file():
            failures.append(f'{name}: fonte nova ausente');continue
        desired=src.read_bytes()
        if target.exists():
            if target.read_bytes()!=desired:failures.append(f'{name}: existe com conteúdo diferente')
        else:edits[name]=desired
    if failures:
        print('INCOMPATÍVEL — nenhum arquivo foi alterado.')
        for failure in failures:print(' •',failure)
        print('Envie o ZIP mais recente do projeto antes de forçar qualquer substituição.')
        return 2
    for name,bytes_ in edits.items():
        if name.endswith('.py'):
            try:compile(bytes_.decode('utf-8'),name,'exec')
            except Exception as error:print('Python inválido:',error);return 2
        if name.endswith('.js') and shutil.which('node'):
            p=subprocess.run(['node','--check','-'],input=bytes_.decode('utf-8'),capture_output=True,text=True)
            if p.returncode:print('JavaScript inválido em',name,p.stderr[:400]);return 2
    try:
        from jinja2 import Environment
        for name,content in edits.items():
            if name.endswith('.html'):Environment().parse(content.decode('utf-8'))
    except ImportError:pass
    except Exception as error:print('HTML/Jinja inválido:',error);return 2
    print('Arquivos pendentes:',len(edits))
    for name in edits:print(' +',name)
    if dry_run:
        print('DRY-RUN OK — nenhum arquivo modificado.');return 0
    if not edits:
        print('JÁ INSTALADO — nenhum arquivo precisa ser alterado.');return 0
    backup=ROOT/('backup_opcoes_mensagem_20261103_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S'))
    try:
        # Backup de tudo ANTES de começar a gravar.
        for name in edits:
            src=ROOT/name
            if src.exists():
                dst=backup/name;dst.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(src,dst)
        written=[]
        for name,data in edits.items():
            target=ROOT/name;target.parent.mkdir(parents=True,exist_ok=True)
            tmp=target.with_name(target.name+'.dbm-tmp')
            tmp.write_bytes(data);tmp.replace(target);written.append(name)
    except Exception as error:
        print('ERRO — tentando reverter:',error)
        for name in locals().get('written',[]):
            source=backup/name
            if source.exists():shutil.copy2(source,ROOT/name)
            else:(ROOT/name).unlink(missing_ok=True)
        return 2
    print('ATUALIZAÇÃO INSTALADA. Backup:',backup)
    return 0

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--dry-run',action='store_true')
    args=p.parse_args()
    sys.exit(apply_all(args.dry_run))
