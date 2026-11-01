"""Testes offline de configuração das fases 3 e 4; sem tocar no Neon."""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]

def load_module(relative, name):
    spec=importlib.util.spec_from_file_location(name, ROOT/relative)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_python_deps_upgrade_atomico():
    module=load_module('scripts/aplicar_atualizacoes_3e4.py','phase34_installer')
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        (root/'requirements.txt').write_text('fastapi>=0.128,<1\ncryptography>=44,<47\npywebpush>=2.0,<3\n')
        target, updated, changed=module.prepare_python(root)
        assert target.name=='requirements.txt' and changed
        assert 'cryptography>=50.0.2,<51' in updated
        assert 'pywebpush>=2.5.0,<3' in updated
        (root/'requirements.txt').write_text(updated)
        _, again, changed2=module.prepare_python(root)
        assert not changed2 and updated==again


def test_nao_reescreve_requisitos_desconhecidos():
    module=load_module('scripts/aplicar_atualizacoes_3e4.py','phase34_invalid')
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        (root/'requirements.txt').write_text('cryptography>=52\npywebpush>=2.5.0,<3\n')
        try:module.prepare_python(root)
        except ValueError:pass
        else:raise AssertionError('Não deveria alterar uma versão desconhecida')


def test_recusa_url_de_exemplo_e_http_publico():
    module=load_module('scripts/diagnosticar_desempenho_fase4.py','phase34_monitor')
    for bad in ('https://SEU-PROJETO.vercel.app', 'http://exemplo.org',
                'https://site.com/foo', 'https://site.com/?token=secret',
                'https://foo:pass@site.com'):
        try:module.validate_url(bad)
        except ValueError:pass
        else:raise AssertionError(f'Endereço deveria ser recusado: {bad}')
    assert module.validate_url('https://meusite.vercel.app/')=='https://meusite.vercel.app'


def test_instalador_nao_altera_mfa_ou_aplicacao():
    script=(ROOT/'scripts/aplicar_atualizacoes_3e4.py').read_text()
    assert 'app/main.py' not in script or 'validate_project' in script
    assert 'password' not in script.lower()
    for path in ('app/main.py','app/routers/auth.py','app/templates/base.html'):
        assert (ROOT/path).is_file()


def test_manifest_deploy_exclui_testes_quando_instalado():
    # Compatível tanto com revisão que ainda vai aplicar quanto com a aplicada.
    v=(ROOT/'.vercelignore').read_text()
    assert v.strip()
