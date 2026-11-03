"""Atualização incremental de segurança: modifica apenas trechos identificados.

Execute na raiz do DBMILESX (com o ZIP extraído previamente):
    python scripts/aplicar_seguranca_fase1.py

Aborta sem salvar se a versão atual for diferente da esperada. Não modifica
cotação, companhias, lucro, design, senhas, dados ou banco.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def replace_once(text: str, before: str, after: str, label: str) -> str:
    if after and after in text:
        return text  # pode ser reaplicado sem duplicar
    if text.count(before) != 1:
        raise ValueError(f"Trecho '{label}' mudou. Não apliquei para evitar regressões.")
    return text.replace(before, after, 1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true', help='Confere compatibilidade sem alterar arquivos')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    main_file = root / 'app' / 'main.py'
    tests_file = root / 'tests' / 'test_security.py'
    service_file = root / 'app' / 'services' / 'private_uploads.py'
    route_file = root / 'patches' / 'protected_upload_route.txt'
    test_add = root / 'patches' / 'test_private_uploads_append.txt'
    for item in (main_file, tests_file, service_file, route_file, test_add):
        if not item.is_file():
            raise FileNotFoundError(f"Arquivo ausente: {item.relative_to(root)}")
    current = main_file.read_text(encoding='utf-8')
    proposed = current
    proposed = replace_once(proposed, 'from fastapi import FastAPI\n',
                            'from fastapi import FastAPI, Request, Depends, HTTPException\n', 'importações FastAPI')
    proposed = replace_once(proposed, 'from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse\n',
                            'from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse\n', 'importações FileResponse')
    proposed = replace_once(proposed, 'from sqlalchemy import select\n',
                            'from sqlalchemy import select\nfrom sqlalchemy.orm import Session\nfrom mimetypes import guess_type\n',
                            'importações tipo SQL/MIME')
    proposed = replace_once(proposed, '    STATIC_DIR,\n', '    STATIC_DIR,\n    UPLOAD_DIR,\n', 'configuração de uploads')
    proposed = replace_once(proposed, 'from .database import Base, SessionLocal, engine\n',
                            'from .database import Base, SessionLocal, engine, get_db\nfrom .dependencies import require_user\nfrom .services.private_uploads import clean_upload_path, may_read_upload\n', 'dependências autenticadas')
    route = route_file.read_text(encoding='utf-8').rstrip() + '\n'
    old_mount = 'app.mount("/uploads", StaticFiles(directory=str(AIRLINE_UPLOAD_DIR.parent)), name="uploads")\n'
    proposed = replace_once(proposed, old_mount, route, 'exposição pública de /uploads')
    proposed = replace_once(proposed, '    except Exception as exc:\n        logger.exception("Falha no teste do banco hospedado")\n',
                            '    except Exception:\n        logger.exception("Falha no teste do banco hospedado")\n', 'tratamento de health/db')
    proposed = replace_once(proposed,
                            '                "error_type": type(exc).__name__,\n                "message": str(exc)[:500],\n',
                            '', 'vazamento de detalhes no health/db') if '"error_type": type(exc).__name__' in proposed else proposed
    if '"error_type": type(exc).__name__' in proposed or '"message": str(exc)[:500]' in proposed:
        raise ValueError('A resposta detalhada do health/db não pôde ser removida com segurança.')
    if 'app.mount("/uploads"' in proposed:
        raise ValueError('Ainda existe uma montagem pública de uploads, cancelando.')

    tests_current = tests_file.read_text(encoding='utf-8')
    snippet = test_add.read_text(encoding='utf-8')
    marker = '# Atualização 1: autorização real sobre arquivos de /uploads'
    tests_new = tests_current if marker in tests_current else tests_current.rstrip() + '\n\n' + snippet

    compile(proposed, str(main_file), 'exec')
    compile(service_file.read_text(encoding='utf-8'), str(service_file), 'exec')
    compile(tests_new, str(tests_file), 'exec')
    print('Validação OK: substituição mínima, código compilável, sem apagar páginas comerciais.')
    if args.dry_run:
        print('Modo de conferência: nenhum arquivo foi alterado.')
        return 0

    # Só gravar após todos os checks. Criar um backup do main atual.
    if proposed != current:
        backup = root / 'data' / 'backups' / 'main.py.backup_seguranca_fase1'
        backup.parent.mkdir(parents=True, exist_ok=True)
        if not backup.exists():
            backup.write_text(current, encoding='utf-8')
        main_file.write_text(proposed, encoding='utf-8')
    if tests_new != tests_current:
        tests_file.write_text(tests_new, encoding='utf-8')
    print('Aplicado: app/main.py + testes de autorização em tests/test_security.py')
    print('Rode: python -m pytest tests/test_security.py -q')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, OSError, SyntaxError) as exc:
        print(f'Atualização NÃO aplicada: {exc}', file=sys.stderr)
        sys.exit(1)
