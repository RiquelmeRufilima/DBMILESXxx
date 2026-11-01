#!/usr/bin/env python3
"""Executa testes DBMILESX em processos separados para isolar SQLite.

Uso: python scripts/testar_suite_isolada.py
Não altera arquivos de produção, não executa migrações e não acessa Neon.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEST_DIR = ROOT / 'tests'

def main() -> int:
    if not TEST_DIR.is_dir():
        print('ERRO: pasta tests/ nao encontrada.', file=sys.stderr)
        return 2

    all_tests = sorted(TEST_DIR.glob('test_*.py'))
    if not all_tests:
        print('ERRO: nenhum teste encontrado.', file=sys.stderr)
        return 2

    security = [p for p in all_tests if p.name == 'test_security.py']
    security += [p for p in all_tests if p.name.startswith('test_security_phase')]
    progressive = [p for p in all_tests if p.name == 'test_progressive_features.py']
    reserved = {p.resolve() for p in security + progressive}
    remaining = [p for p in all_tests if p.resolve() not in reserved]
    groups = [('Seguranca e MFA', security), ('Recursos progressivos', progressive),
              ('Demais recursos', remaining)]

    count = 0
    failures = []
    with tempfile.TemporaryDirectory(prefix='dbmilesx-suite-isolada-') as tmp:
        for index, (label, files) in enumerate(groups, start=1):
            if not files:
                continue
            # Um SQLite distinto por processo; sobrescreve possivel URL Neon.
            persistent = Path(tmp) / f'processo-{index}'
            persistent.mkdir(parents=True, exist_ok=True)
            env = os.environ.copy()
            env['DATABASE_URL'] = f"sqlite:///{persistent / 'pytest.sqlite3'}"
            env['PERSISTENT_ROOT'] = str(persistent)
            env['APP_ENV'] = 'test'
            env['RUN_FULL_STARTUP_MAINTENANCE'] = '0'
            env['SESSION_HTTPS_ONLY'] = '0'
            env['SECRET_KEY'] = 'test-runner-isolado-apenas-para-testes-2026'
            for key in ('VERCEL', 'BOOTSTRAP_ADMIN_EMAIL', 'BOOTSTRAP_ADMIN_PASSWORD'):
                env.pop(key, None)

            args = [sys.executable, '-m', 'pytest', '-q', '--disable-warnings'] + [str(p.relative_to(ROOT)) for p in files]
            print(f'\n[{index}/3] {label} ({len(files)} arquivos)', flush=True)
            print('Executando:', ' '.join(args), flush=True)
            result = subprocess.run(args, cwd=ROOT, env=env, check=False)
            count += len(files)
            if result.returncode != 0:
                failures.append((label, result.returncode))

    print(f'\nArquivos testados: {count}/{len(all_tests)}', flush=True)
    if failures:
        print('FALHA:', ', '.join(f'{name} (codigo {code})' for name, code in failures))
        return 1
    print('SUCESSO: todas as etapas isoladas passaram. Nenhum banco de producao foi acessado pelo runner.')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
