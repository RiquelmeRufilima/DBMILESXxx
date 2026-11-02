#!/usr/bin/env python3
"""Aplica apenas o layout modelo2 em cima da correção compacta de 02/11.

    python scripts/aplicar_layout_modelo2.py --dry-run
    python scripts/aplicar_layout_modelo2.py

Não altera o banco, backend, cálculos nem MFA.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
from datetime import datetime
from pathlib import Path

ASSETS = {
    'app/static/js/flight-itinerary-20261102.js': '60632f622d549944ab33d0aafbe117ad6fdc87cd2905ce6318e718f13d51d616',
    'app/static/css/flight-itinerary-20261102.css': '06abc68f9cfc0e4f92daaaf0c0db9d3da3e88946d9d28630c84f98e9f4f91839',
}
TEMPLATES = {
    'app/templates/calculations/new.html': (
        ('/static/js/flight-itinerary-20261102.js?v=20261102.2',
         '/static/js/flight-itinerary-20261102.js?v=20261102.3'),
        ('/static/css/flight-itinerary-20261102.css?v=20261102.2',
         '/static/css/flight-itinerary-20261102.css?v=20261102.3'),
    ),
    'app/templates/calculations/result.html': (
        ('/static/css/flight-itinerary-20261102.css?v=20261102.2',
         '/static/css/flight-itinerary-20261102.css?v=20261102.3'),
    ),
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help='Só verificar, sem instalar')
    args = parser.parse_args()
    project = Path.cwd()
    package = Path(__file__).resolve().parent.parent
    if not (project/'app/templates/calculations/new.html').is_file():
        print('ERRO: execute na raiz DBMILESXxx, onde ficam app/ e scripts/.')
        return 2
    pending: dict[str, bytes] = {}
    problems = []
    for name, old_hash in ASSETS.items():
        source = package/'patches/modelo2'/name
        target = project/name
        if not source.is_file() or not target.is_file():
            problems.append(f'{name}: arquivo ausente')
            continue
        original = target.read_bytes()
        desired = source.read_bytes()
        if original == desired:
            continue
        if digest(original) != old_hash:
            problems.append(f'{name}: código diferente da correção compacta; não sobrescrever')
            continue
        pending[name] = desired
    for name, replacements in TEMPLATES.items():
        target = project/name
        if not target.is_file():
            problems.append(f'{name}: arquivo ausente')
            continue
        old = target.read_text(encoding='utf-8')
        changed = old
        for before, after in replacements:
            if after in changed:
                continue
            if changed.count(before) != 1:
                problems.append(f'{name}: versão dos recursos diferente do esperado: {before}')
            else:
                changed = changed.replace(before, after, 1)
        if changed != old:
            pending[name] = changed.encode('utf-8')
    if problems:
        print('SEM ALTERAÇÕES: a versão local não corresponde ao pacote anterior.')
        for problem in problems:
            print(' •', problem)
        print('Envie o ZIP mais recente do Codespaces para adaptar sem perder o restante.')
        return 1
    print('Compatibilidade OK. Arquivos pendentes:', len(pending))
    for name in pending:
        print(' +', name)
    if args.dry_run:
        print('DRY-RUN OK — nada foi modificado.')
        return 0
    if not pending:
        print('JÁ INSTALADO — nenhuma duplicação.')
        return 0
    backup = project/('backup_layout_modelo2_'+datetime.now().strftime('%Y%m%d_%H%M%S'))
    installed: list[str] = []
    try:
        for name, new_bytes in pending.items():
            target = project/name
            previous = backup/name
            previous.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, previous)
            temp = target.with_name(target.name+'.dbm-modelo2-tmp')
            temp.write_bytes(new_bytes)
            temp.replace(target)
            installed.append(name)
    except OSError as exc:
        print('Erro na instalação; restaurando backup:', exc)
        for name in installed:
            shutil.copy2(backup/name, project/name)
        return 2
    print('LAYOUT MODELO2 INSTALADO. Backup salvo em:', backup)
    print('Conferir: python -m pytest tests/test_flight_itinerary.py -q')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
