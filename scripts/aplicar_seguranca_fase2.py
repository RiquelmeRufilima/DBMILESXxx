"""Instalador mínimo da Fase 2 para o Codespaces DBMILESX.

Uso:
    python scripts/aplicar_seguranca_fase2.py --dry-run
    python scripts/aplicar_seguranca_fase2.py
    python scripts/aplicar_seguranca_fase2.py --dry-run --upgrade-python-deps
    python scripts/aplicar_seguranca_fase2.py --upgrade-python-deps

A instalação normal adiciona CSP Report-Only e o cabeçalho anti-crossdomain.
O MFA NÃO É ALTERADO. As versões Python só são alteradas por opção explícita.
"""
from __future__ import annotations

import argparse
import ast
from pathlib import Path
import shutil
import sys

IMPORT_MARKER = 'from .services.hosted_bootstrap import ensure_hosted_admin\n'
IMPORT_ADD = 'from .services.security_headers import apply_phase2_headers\n'
RETURN_MARKER = '    return response\n\n\napp.mount("/static"'
RETURN_UPDATED = '    return apply_phase2_headers(response)\n\n\napp.mount("/static"'


def replace_once_or_already(source: str, before: str, after: str, label: str) -> str:
    if after in source:
        return source
    if source.count(before) != 1:
        raise ValueError(f"Código incompatível em {label}; nenhum arquivo foi alterado.")
    return source.replace(before, after, 1)


def prepare_changes(root: Path, upgrade_deps: bool) -> tuple[dict[Path, str], list[Path]]:
    main = root / 'app/main.py'
    helper = root / 'app/services/security_headers.py'
    requirements = root / 'requirements.txt'
    if not main.is_file() or not helper.is_file():
        raise ValueError('Pacote incompleto: app/main.py ou app/services/security_headers.py ausente.')
    original = main.read_text(encoding='utf-8')
    if 'from .services.private_uploads import' not in original or 'app.mount("/uploads"' in original:
        raise ValueError('Fase 1 não detectada. Proteja os uploads antes de aplicar a Fase 2.')
    updated = replace_once_or_already(original, IMPORT_MARKER, IMPORT_MARKER + IMPORT_ADD, 'importação')
    updated = replace_once_or_already(updated, RETURN_MARKER, RETURN_UPDATED, 'middleware HTTP')
    ast.parse(updated, filename=str(main))
    ast.parse(helper.read_text(encoding='utf-8'), filename=str(helper))
    changes = {main: updated}
    if upgrade_deps:
        if not requirements.is_file():
            raise ValueError('requirements.txt não encontrado.')
        content = requirements.read_text(encoding='utf-8')
        content = replace_once_or_already(content, 'cryptography>=44,<47\n', 'cryptography>=50.0.2,<51\n', 'cryptography')
        content = replace_once_or_already(content, 'pywebpush>=2.0,<3\n', 'pywebpush>=2.5.0,<3\n', 'pywebpush')
        changes[requirements] = content
    changed = [path for path, new in changes.items() if path.read_text(encoding='utf-8') != new]
    return changes, changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true', help='Apenas verificar compatibilidade.')
    parser.add_argument('--upgrade-python-deps', action='store_true', help='Atualizar restrições de cryptography/pywebpush (opcional, testar em homologação).')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    changes, changed = prepare_changes(root, args.upgrade_python_deps)
    for path in changed:
        print('ALTERAR:', path.relative_to(root))
    if not changed:
        print('Já está atualizado: nenhuma mudança necessária.')
        return 0
    if args.dry_run:
        print('DRY-RUN aprovado: nenhum arquivo modificado.')
        return 0
    backup_dir = root / 'data' / 'backups' / 'security_phase2'
    # Backup de todos os arquivos ANTES de qualquer alteração.
    for path in changed:
        backup = backup_dir / path.relative_to(root)
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup)
    try:
        for path in changed:
            path.write_text(changes[path], encoding='utf-8')
    except Exception:
        for path in changed:
            backup = backup_dir / path.relative_to(root)
            if backup.exists():
                shutil.copy2(backup, path)
        raise
    print('Fase 2 aplicada. MFA continua opcional. CSP em modo Report-Only.')
    if args.upgrade_python_deps:
        print('ATENÇÃO: requisitos atualizados; valide o deploy e as notificações push em homologação.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, SyntaxError) as error:
        print('NÃO aplicado:', error, file=sys.stderr)
        raise SystemExit(1)
