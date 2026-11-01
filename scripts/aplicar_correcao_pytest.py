#!/usr/bin/env python3
"""Corrige colisões de SQLite no pytest sem editar código de produção.

python scripts/aplicar_correcao_pytest.py --dry-run
python scripts/aplicar_correcao_pytest.py
"""
from __future__ import annotations
import argparse
import datetime
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
START_SECURITY = "# --- Ambiente isolado:"
END_SECURITY = "from fastapi.testclient import TestClient"
START_PROGRESSIVE = '_test_dir = tempfile.mkdtemp('
END_PROGRESSIVE = 'from app.models import '
SECURITY_NEW = '''# O conftest configura SQLite antes da coleta de qualquer módulo.
_TMP = os.environ["PERSISTENT_ROOT"]
assert os.environ["DATABASE_URL"].startswith("sqlite:///"), "SQLite de testes obrigatório"

'''
PROGRESSIVE_NEW = '''# Este módulo possui um banco próprio, sem mudar DATABASE_URL global.
from starlette.requests import Request
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.main import app
_test_dir = tempfile.TemporaryDirectory(prefix="dbm-progressive-")
engine = create_engine(f"sqlite:///{_test_dir.name}/db.sqlite", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

'''

def replace_block(source: str, start: str, end: str, replacement: str, label: str) -> tuple[str, bool]:
    if replacement.strip() in source:
        return source, False
    if source.count(start) != 1 or source.count(end) != 1:
        raise ValueError(f"{label}: estrutura diferente da versão prevista. Nenhum arquivo será alterado.")
    i = source.index(start)
    j = source.index(end, i)
    if j <= i:
        raise ValueError(f"{label}: limites de bloco incorretos")
    return source[:i] + replacement + source[j:], True

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true', help='apenas verifica; não modifica arquivos')
    args = parser.parse_args()
    files = [TESTS/'test_security.py', TESTS/'test_progressive_features.py', TESTS/'conftest.py']
    if not all(p.is_file() for p in files):
        print('ERRO: faltam arquivos de testes ou tests/conftest.py. Extraia o ZIP na raiz do projeto.', file=sys.stderr)
        return 2
    sec, prog, conf = files
    updates = {}
    try:
        sec_before = sec.read_text(encoding='utf-8')
        prog_before = prog.read_text(encoding='utf-8')
        conftest = conf.read_text(encoding='utf-8')
        if 'dbmilesx-pytest-' not in conftest or 'sqlite:///' not in conftest:
            raise ValueError('tests/conftest.py não corresponde ao fornecido no pacote; revisar antes de continuar')
        sec_after, changed = replace_block(sec_before, START_SECURITY, END_SECURITY, SECURITY_NEW, sec.name)
        if changed: updates[sec] = (sec_before,sec_after)
        prog_after, changed = replace_block(prog_before, START_PROGRESSIVE, END_PROGRESSIVE, PROGRESSIVE_NEW, prog.name)
        if changed: updates[prog] = (prog_before,prog_after)
        # Prevenção contra configuração legada residual no módulo progressivo.
        if 'os.environ["DATABASE_URL"]' in prog_after or 'os.environ["PERSISTENT_ROOT"]' in prog_after:
            raise ValueError('test_progressive_features.py ainda altera DATABASE_URL/PERSISTENT_ROOT; revisar manualmente')
        for p, (_, new) in updates.items():
            compile(new, str(p), 'exec')
        compile(conftest, str(conf), 'exec')
    except (ValueError, UnicodeError, OSError, SyntaxError) as error:
        print(f'ERRO (nenhum arquivo modificado): {error}', file=sys.stderr)
        return 2
    if not updates:
        print('OK: correção já aplicada. Execute: python -m pytest tests/ -q')
        return 0
    print('Arquivos a modificar:', ', '.join(str(p.relative_to(ROOT)) for p in updates))
    if args.dry_run:
        print('DRY-RUN OK. Nenhum arquivo alterado.')
        return 0
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    backup = ROOT / f'backup_correcao_pytest_{stamp}'
    backup.mkdir(parents=True,exist_ok=False)
    for p,(old,_) in updates.items():
        target=backup/p.relative_to(ROOT)
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(old, encoding='utf-8')
    try:
        for p,(_,new) in updates.items():
            tmp = p.with_name(p.name + '.tmp-pytest-fix')
            tmp.write_text(new,encoding='utf-8')
            tmp.replace(p)
    except OSError as error:
        print(f'ERRO ao gravar: {error}. Restaurando backup.',file=sys.stderr)
        for p in updates:
            saved=backup/p.relative_to(ROOT)
            if saved.exists(): shutil.copy2(saved,p)
        return 2
    print(f'Aplicado. Backup: {backup.name}/')
    print('Teste completo: python -m pytest tests/ -q')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
