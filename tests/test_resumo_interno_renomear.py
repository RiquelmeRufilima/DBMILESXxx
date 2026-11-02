"""Testes de regressão sem alterar banco para o patch de resumo/renomeação."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "aplicar_resumo_interno_renomear.py"


def _load_patch():
    spec = importlib.util.spec_from_file_location("patch_resumo", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_renomear_respeita_acesso_csrf_e_nao_muda_slug():
    src = (Path('app/routers/airlines.py')).read_text(encoding='utf-8')
    assert 'async def rename_catalog_item(' in src
    assert '_can_manage(user, airline)' in src
    assert 'validate_csrf_token(' in src
    route = src.split('async def rename_catalog_item(',1)[1].split('@router.post(',1)[0]
    assert 'airline.name = name' in route
    assert 'airline.slug =' not in route
    assert 'db.commit()' in route


def test_resumo_nao_confunde_custo_com_venda():
    template = Path('app/templates/calculations/result.html').read_text(encoding='utf-8')
    assert 'Valor cobrado: não definido' in template
    assert 'let profitDefined = {{' in template
    assert 'if(profitDefined){' in template
    assert 'Custo total: ${formatMoney(cost)}' in template
    assert 'Tipo de cálculo: ${method}' in template


def test_detalhes_so_quando_presentes():
    template = Path('app/templates/calculations/result.html').read_text(encoding='utf-8')
    assert "if(skipRecord){" in template
    assert "row.status==='flown'" in template
    assert "if(Array.isArray(row.schedules)&&row.schedules.length)" in template
    assert "if(Number(baggage)>0)" in template
    assert "if(maxBag!==null)" in template
    assert "['systems','consolidators'].includes(catalogCategory)" in template


def test_templates_compilam():
    jinja2=pytest.importorskip('jinja2')
    for f in ('app/templates/calculations/result.html','app/templates/airlines/manage.html'):
        jinja2.Environment().parse(Path(f).read_text(encoding='utf-8'))


def test_instalador_idempotente_e_protege_versoes_incompativeis():
    mod=_load_patch()
    s=Path('app/templates/calculations/result.html').read_text(encoding='utf-8')
    assert mod.patch_result(s)==s
    with pytest.raises(RuntimeError):mod.patch_result('pagina sem os pontos de integracao esperados')
