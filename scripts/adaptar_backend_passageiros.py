#!/usr/bin/env python3
"""Adicionar suporte a adultos/crianças para versões reconhecidas do DBMILESX.
Não altera Neon; exige migração aditiva quando o modelo antigo não possui children.
"""
from __future__ import annotations
import argparse
import datetime
import re
import shutil
import sys
from pathlib import Path

ROOT=Path.cwd()
ROUTER=Path('app/routers/calculations.py')
MODEL=Path('app/models.py')


def one(text, old, new, title):
    if new in text: return text
    count=text.count(old)
    if count!=1:raise ValueError(f'{title}: esperado 1 trecho, encontrado {count}. Não instalar sem adaptar ao código atual.')
    return text.replace(old,new,1)


def patch_backend(s):
    delim='@router.post("/base/save")'
    if delim not in s:raise ValueError('Rota /base/save não localizada.')
    p=s.index('async def save_base(', s.index(delim))
    q=s.find('\n@router.',p+len('async def save_base('))
    if q<0:raise ValueError('Final da rota /base/save não localizado.')
    body=s[p:q]
    if not re.search(r'form\.get\([\'\"]adults[\'\"]\)',body):
        body=one(body,
            '        babies = max(0, int(form.get("babies") or 0))\n        option_id = int(form.get("option_id") or 0) or None',
            '        babies = max(0, int(form.get("babies") or 0))\n        children = max(0, int(form.get("children") or 0))\n        if form.get("adults") not in (None, ""):\n            passengers = max(1, int(form.get("adults") or 0) + children)\n        children = min(children, max(0, passengers - 1))\n        option_id = int(form.get("option_id") or 0) or None',
            'Recebimento de adultos e crianças')
    if '    group.children = children\n' not in body:
        body=one(body,'    group.passengers = passengers\n    group.babies = babies',
                  '    group.passengers = passengers\n    group.children = children\n    group.babies = babies',
                  'Persistência dos passageiros pagantes')
    s=s[:p]+body+s[q:]
    marker='def _blank_base()'
    p=s.index(marker);q=s.find('\ndef ',p+len(marker))
    section=s[p:q]
    if '"children":' not in section:
        section=one(section,'        "passengers": 1,\n        "babies": 0,',
                   '        "passengers": 1,\n        "children": 0,\n        "babies": 0,',
                   'Cotação padrão')
        s=s[:p]+section+s[q:]
    marker='def _base_from_group('
    p=s.index(marker);q=s.find('\ndef ',p+len(marker))
    section=s[p:q]
    if '"children":' not in section:
        anchor='        "babies": max(0, int(selected.get("babies") if selected.get("babies") is not None else (group.babies or 0))),'
        section=one(section,anchor, anchor+'\n        "children": max(0, min(int(getattr(group, "children", 0) or 0), max(1, int(selected.get("passengers") if selected.get("passengers") is not None else (group.passengers or 1))) - 1)),', 'Carregar crianças ao editar')
        s=s[:p]+section+s[q:]
    # Dados de adultos/crianças precisam estar disponíveis para a mensagem final.
    marker='return templates.TemplateResponse(request, "calculations/result.html", context('
    if 'group_children=group_children' not in s:
        if s.count(marker)!=1: raise ValueError('Resultado não possui o padrão esperado.')
        prep='    group_children = 0\n    if link and link.group_id:\n        group_row = db.get(QuoteGroup, link.group_id)\n        group_children = int(getattr(group_row, "children", 0) or 0) if group_row else 0\n    group_children = max(0, min(group_children, max(0, int(quote.passengers or 1) - 1)))\n'
        s=s.replace('    '+marker,prep+'    '+marker,1)
        if 'commercial_meta=commercial_meta))' in s:
            s=one(s,'commercial_meta=commercial_meta))','commercial_meta=commercial_meta, group_children=group_children))','Resultado adultos/crianças')
        else:
            s=one(s,'breakdown=breakdown, segments=segments))','breakdown=breakdown, segments=segments, group_children=group_children))','Resultado adultos/crianças (versão antiga)')
    return s


def patch_model(s):
    marker='class QuoteGroup(Base):'
    p=s.find(marker)
    q=s.find('\nclass ',p+len(marker))
    if p<0 or q<0:raise ValueError('Modelo QuoteGroup não encontrado.')
    section=s[p:q]
    if '    children: Mapped[int]' in section:return s,False
    section=one(section,
        '    passengers: Mapped[int] = mapped_column(Integer, default=1, nullable=False)\n    babies:',
        '    passengers: Mapped[int] = mapped_column(Integer, default=1, nullable=False)\n    # Crianças pagantes contam dentro de passengers.\n    children: Mapped[int] = mapped_column(Integer, default=0, nullable=False)\n    babies:',
        'Modelo crianças pagantes')
    return s[:p]+section+s[q:],True


def compute(root):
    original={f:(root/f).read_text(encoding='utf-8') for f in (ROUTER,MODEL)}
    model,altered=patch_model(original[MODEL])
    return original,{ROUTER:patch_backend(original[ROUTER]),MODEL:model},altered


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--dry-run',action='store_true')
    opts=ap.parse_args()
    try:
        original,updates,needs_sql=compute(ROOT)
        for file,source in updates.items():
            if file.suffix=='.py':compile(source,str(file),'exec')
    except (ValueError,OSError,SyntaxError) as exc:
        print('INCOMPATÍVEL (nada modificado):',exc)
        return 1
    changed=[p for p in updates if original[p]!=updates[p]]
    print('Pré-verificação aprovada; alterações:',*(str(p) for p in changed),sep='\n • ')
    if needs_sql:
        print('IMPORTANTE: sua versão não possui coluna children. O SQL incluído precisa ser executado no Neon ANTES do deploy.')
    if opts.dry_run:
        print('DRY-RUN OK. Nenhum arquivo modificado.');return 0
    if not changed:
        print('Já aplicado.');return 0
    backup=ROOT/('backup_pax_definitivo_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S'))
    try:
        for file in changed:
            (backup/file).parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(ROOT/file,backup/file)
        for file in changed:
            tmp=(ROOT/file).with_suffix('.pax-tmp')
            tmp.write_text(updates[file],encoding='utf-8')
            tmp.replace(ROOT/file)
    except OSError as exc:
        for file in changed:
            if (backup/file).exists():shutil.copy2(backup/file,ROOT/file)
        print('Erro ao gravar (restaurado do backup):',exc)
        return 2
    print('INSTALADO; backup:',backup)
    return 0

if __name__=='__main__':sys.exit(main())
