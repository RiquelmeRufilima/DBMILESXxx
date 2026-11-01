#!/usr/bin/env python3
"""Instala dependências corrigidas das Fases 3/4 SEM tocar em telas, MFA ou banco.

A instalação do Node é transacional: instala e audita em pasta temporária;
só publica package.json e package-lock.json se tudo passar. Requer internet npm
no Codespaces. Em caso de erro, mantém os arquivos originais de Node.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PY_OLD = ('cryptography>=44,<47', 'pywebpush>=2.0,<3')
PY_NEW = ('cryptography>=50.0.2,<51', 'pywebpush>=2.5.0,<3')
NODE_VERSION = '2.8.2'


def prepare_python(root: Path) -> tuple[Path, str, bool]:
    target = root / 'requirements.txt'
    original = target.read_text(encoding='utf-8')
    lines = original.splitlines(keepends=True)
    output, changed = [], False
    for old, new in zip(PY_OLD, PY_NEW):
        matches = [i for i, line in enumerate(lines) if line.strip() in (old, new)]
        if len(matches) != 1:
            raise ValueError(f'Requisitos de {old.split(">=")[0]} diferentes do esperado; não aplicar automaticamente.')
        i = matches[0]
        if lines[i].strip() == old:
            lines[i] = new + ('\n' if lines[i].endswith('\n') else '')
            changed = True
    return target, ''.join(lines), changed


def validate_project(root: Path) -> None:
    required = ('app/main.py', 'app/services/private_uploads.py', 'app/services/security_headers.py',
                'tests/test_security_phase2.py', 'api/avatar-presign.js', 'requirements.txt',
                'package.json', 'package-lock.json')
    absent = [item for item in required if not (root / item).is_file()]
    if absent:
        raise ValueError('Instale antes as Fases 1 e 2. Ausentes: ' + ', '.join(absent))
    main = (root / 'app/main.py').read_text(encoding='utf-8')
    if 'apply_phase2_headers' not in main or 'private_uploads' not in main:
        raise ValueError('Proteções das Fases 1/2 não detectadas em app/main.py. Não aplicar.')
    node = json.loads((root / 'package.json').read_text(encoding='utf-8'))
    if '@vercel/blob' not in node.get('dependencies', {}):
        raise ValueError('Dependência @vercel/blob não detectada no projeto.')
    if 'issueSignedToken' not in (root / 'api/avatar-presign.js').read_text(encoding='utf-8'):
        raise ValueError('API Blob do aplicativo mudou; exige revisão antes do upgrade.')


def run(command: list[str], cwd: Path, timeout: int = 150) -> None:
    try:
        proc = subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f'Falha ao executar {command[0]}: {exc}') from exc
    if proc.returncode != 0:
        # Resultados npm não deveriam incluir tokens, mas evite exibir logs extensos.
        raise RuntimeError(f'Comando {command[0]} falhou; saída resumida:\n{proc.stdout[-1800:]}')


def stage_node(root: Path) -> tuple[str, str]:
    """Não altera nenhum arquivo do projeto enquanto testa o novo Node."""
    if not shutil.which('npm') or not shutil.which('node'):
        raise RuntimeError('Node.js/npm não encontrados. Instale Node >=20 no Codespaces.')
    manifest = json.loads((root / 'package.json').read_text(encoding='utf-8'))
    locked = json.loads((root / 'package-lock.json').read_text(encoding='utf-8'))
    current = locked.get('packages', {}).get('node_modules/zod', {}).get('version', '')
    # O problema observado é zod 4.x. Não force migração entre versões major.
    if current and not current.startswith('4.'):
        raise RuntimeError(f'Versão zod {current} inesperada; revisão manual necessária.')
    manifest.setdefault('dependencies', {})['@vercel/blob'] = NODE_VERSION
    manifest.setdefault('overrides', {})['zod'] = '^4.6.6'
    with tempfile.TemporaryDirectory(prefix='dbmilesx-node-audit-') as tmp:
        folder = Path(tmp)
        (folder / 'package.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        shutil.copy2(root / 'package-lock.json', folder / 'package-lock.json')
        run(['npm', 'install', '--ignore-scripts', '--no-audit', '--no-fund', '--package-lock-only'], folder)
        run(['npm', 'ci', '--ignore-scripts', '--no-audit', '--no-fund'], folder)
        run(['npm', 'audit', '--omit=dev', '--audit-level=high'], folder)
        run(['node', '--input-type=module', '-e',
             "import {issueSignedToken,presignUrl} from '@vercel/blob'; if(typeof issueSignedToken !== 'function'||typeof presignUrl !== 'function') process.exit(2);"], folder)
        lock_new = json.loads((folder / 'package-lock.json').read_text(encoding='utf-8'))
        blob_version = lock_new.get('packages', {}).get('node_modules/@vercel/blob', {}).get('version')
        zod_version = lock_new.get('packages', {}).get('node_modules/zod', {}).get('version')
        if blob_version != NODE_VERSION or not zod_version or tuple(map(int, zod_version.split('.')[:3])) < (4, 6, 6):
            raise RuntimeError(f'Lock inesperado: Blob={blob_version}, zod={zod_version}')
        return ((folder / 'package.json').read_text(encoding='utf-8'),
                (folder / 'package-lock.json').read_text(encoding='utf-8'))


def backup_files(root: Path, paths: list[Path]) -> None:
    backup = root / 'data' / 'backups' / 'security_phase34'
    for p in paths:
        dest = backup / p.relative_to(root)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dest)


def main() -> int:
    parser = argparse.ArgumentParser(description='DBMILESX Fases 3 e 4: atualização transacional de dependências')
    parser.add_argument('--dry-run', action='store_true', help='Verifica pré-requisitos, não altera arquivos nem baixa dependências')
    parser.add_argument('--skip-node', action='store_true', help='Atualiza apenas requisitos Python (Node permanece pendente)')
    args = parser.parse_args()
    validate_project(ROOT)
    py_path, py_data, py_change = prepare_python(ROOT)
    print('Fases 1 e 2: detectadas; MFA não será alterado.')
    print('Python:', 'cryptography e pywebpush atualizáveis em conjunto' if py_change else 'versões-alvo já declaradas')
    if args.dry_run:
        print('DRY-RUN aprovado. Nenhum arquivo foi alterado.')
        print('Node:', 'ignorado por opção' if args.skip_node else 'será validado em pasta isolada com npm install + audit + teste da API Blob')
        return 0

    # Prepara o Node ANTES de qualquer gravação no projeto. Se o npm falhar,
    # não publica nem parcialmente o upgrade de Python.
    node_files = None
    if not args.skip_node:
        print('Validando Node em ambiente temporário (sem alterar o projeto)...', flush=True)
        node_files = stage_node(ROOT)
        print('Node: npm audit + imports da API Blob aprovados.')
    changes = {}
    if py_change:
        changes[py_path] = py_data
    if node_files:
        for path, content in zip(('package.json', 'package-lock.json'), node_files):
            target = ROOT / path
            if target.read_text(encoding='utf-8') != content:
                changes[target] = content
    ignore_path = ROOT / '.vercelignore'
    if ignore_path.is_file():
        original_ignore = ignore_path.read_text(encoding='utf-8')
        additions = [name for name in ('tests/', '.pytest_cache/') if name not in original_ignore.splitlines()]
        if additions:
            changes[ignore_path] = original_ignore.rstrip('\n') + '\n' + '\n'.join(additions) + '\n'
    if not changes:
        print('Nenhuma alteração de dependência ou deploy necessária.')
        return 0
    backup_files(ROOT, list(changes))
    written = []
    try:
        for path, content in changes.items():
            path.write_text(content, encoding='utf-8')
            written.append(path)
    except Exception:
        for path in written:
            shutil.copy2(ROOT / 'data' / 'backups' / 'security_phase34' / path.relative_to(ROOT), path)
        raise
    print('Atualizado:')
    for path in changes:
        print(' -', path.relative_to(ROOT))
    print('Próximo: teste as notificações push e uploads em homologação antes do deploy.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print('NÃO APLICADO:', error, file=sys.stderr)
        raise SystemExit(1)
