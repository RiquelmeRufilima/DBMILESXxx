#!/usr/bin/env python3
"""DBMILESX — recuperação conjunta, sem substituição de arquivos inteiros.
Valida TODAS as alterações antes de salvar qualquer arquivo; faz backup e rollback.
"""
from __future__ import annotations
import argparse
import datetime
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

import adaptar_backend_passageiros as backend
import aplicar_restauracao_definitiva_v2 as restore


def run(root: Path, dry_run: bool, schema_ready: bool) -> int:
    paths=[backend.ROUTER,backend.MODEL,Path(restore.NEW),Path(restore.RESULT),Path(restore.FLIGHT),Path(restore.ART)]
    try:
        originals={str(p):(root/p).read_text(encoding='utf-8') for p in paths}
        newmodel,needs_schema=backend.patch_model(originals[str(backend.MODEL)])
        output={str(backend.ROUTER):backend.patch_backend(originals[str(backend.ROUTER)]),str(backend.MODEL):newmodel}
        output[restore.NEW]=restore.patch_new(originals[restore.NEW])
        output[restore.RESULT]=restore.patch_result(originals[restore.RESULT])
        src=originals[restore.FLIGHT]
        expected=(Path(__file__).resolve().parent.parent/'patches/restore/app/static/js/flight-itinerary-20261102.js').read_text(encoding='utf-8')
        if src==expected:output[restore.FLIGHT]=src
        elif hashlib.sha256(src.encode()).hexdigest()==restore.EXPECTED_JS_SHA:output[restore.FLIGHT]=expected
        else:raise ValueError('JS do itinerário diferente: não sobrescrevemos sua versão. Envie os arquivos atuais.')
        output[restore.ART]=restore.patch_art(originals[restore.ART])
        for f,content in output.items():
            if f.endswith('.py'):compile(content,f,'exec')
        from jinja2 import Environment
        env=Environment()
        for f in (restore.NEW,restore.RESULT):env.parse(output[f])
        if shutil.which('node'):
            for f in (restore.FLIGHT,restore.ART):
                cp=subprocess.run(['node','--check','-'],input=output[f],capture_output=True,text=True)
                if cp.returncode:raise ValueError(f'JS inválido em {f}: {cp.stderr[:500]}')
    except (OSError,ValueError,SyntaxError,RuntimeError) as exc:
        print('INCOMPATÍVEL — NENHUM ARQUIVO ALTERADO:',exc)
        return 1
    changed=[f for f in output if output[f]!=originals[f]]
    print('ARQUIVOS PRONTOS:',*(('• '+f) for f in changed),sep='\n')
    if needs_schema:
        print('MODELO ANTIGO DETECTADO: exige SQL aditivo em migrations/01_children_neon.sql antes de publicar.')
    if dry_run:
        print('DRY-RUN OK — arquivos preservados.');return 0
    if needs_schema and not schema_ready:
        print('INSTALAÇÃO PAUSADA. Execute a migração SQL no Neon após backup e rode --schema-ready.')
        return 3
    if not changed:
        print('JÁ INSTALADO — não houve alteração.');return 0
    backup=root/('backup_restauracao_definitiva_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S'))
    written=[]
    try:
        for f in changed:
            dest=backup/f;dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(root/f,dest)
        for f in changed:
            dest=root/f;temp=dest.with_name(dest.name+'.pending')
            temp.write_text(output[f],encoding='utf-8')
            temp.replace(dest);written.append(f)
    except OSError as exc:
        for f in written:shutil.copy2(backup/f,root/f)
        print('ERRO AO GRAVAR — backup restaurado:',exc)
        return 2
    print('INSTALAÇÃO COMPLETA. Backup:',backup)
    return 0


def main():
    a=argparse.ArgumentParser()
    a.add_argument('--dry-run',action='store_true')
    a.add_argument('--schema-ready',action='store_true',help='Confirma que o Neon já possui web_quote_groups.children (quando necessário).')
    o=a.parse_args()
    return run(Path.cwd(),o.dry_run,o.schema_ready)

if __name__=='__main__':sys.exit(main())
