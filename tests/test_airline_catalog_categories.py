"""Permissões e validação das três categorias do catálogo de cálculos."""
from types import SimpleNamespace
import pytest
from app.routers.airlines import _catalog_category, _can_manage

@pytest.mark.parametrize('value', ['airlines', 'systems', 'consolidators'])
def test_valid_catalog_categories(value):
    assert _catalog_category(value) == value

def test_empty_category_defaults_to_airlines():
    assert _catalog_category('') == 'airlines'

def test_unsupported_category_is_rejected():
    with pytest.raises(ValueError):
        _catalog_category('anything-else')

def test_builtin_protected_even_for_administrator():
    user = SimpleNamespace(id=7, company_id=3, role='admin')
    builtin = SimpleNamespace(builtin=True, owner_company_id=3, owner_user_id=None)
    assert not _can_manage(user, builtin)

def test_custom_category_can_be_edited_only_by_company_manager():
    airline = SimpleNamespace(builtin=False, owner_company_id=3, owner_user_id=None)
    assert _can_manage(SimpleNamespace(id=7, company_id=3, role='admin'), airline)
    assert not _can_manage(SimpleNamespace(id=7, company_id=4, role='admin'), airline)
    assert not _can_manage(SimpleNamespace(id=7, company_id=3, role='agente'), airline)
