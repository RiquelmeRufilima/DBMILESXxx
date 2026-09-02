from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import current_user
from ..web import context, templates

router = APIRouter(tags=["aliases"])


def _go(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


# ---- Cadastros / Cotações ----
@router.get("/cotacoes")
def a_cotacoes():
    return _go("/cadastros/cotacoes")

@router.get("/cotacoes-feitas")
@router.get("/cotas-feitas")
@router.get("/historico-cotacoes")
@router.get("/historico-de-cotacoes")
def a_cotacoes_feitas():
    return _go("/cadastros/cotacoes-feitas")

@router.get("/fluxo-calculo")
@router.get("/fluxo-de-calculo")
@router.get("/calculos")
@router.get("/controle-calculos")
def a_fluxo_calculo():
    return _go("/cadastros/fluxo-calculo")

@router.get("/voos")
@router.get("/agenda-voos")
def a_voos():
    return _go("/cadastros/voos")


# ---- Financeiro ----
@router.get("/financeiro")
@router.get("/financeiro/dashboard")
def a_financeiro():
    return _go("/cadastros/financeiro/dashboard")

@router.get("/vendas")
@router.get("/vendas-lancadas")
@router.get("/financeiro/vendas")
@router.get("/financeiro/vendas-lancadas")
@router.get("/cadastros/vendas")
@router.get("/cadastros/vendas-lancadas")
def a_vendas():
    return _go("/cadastros/financeiro/vendas")

@router.get("/fluxo-caixa")
@router.get("/fluxo-de-caixa")
@router.get("/financeiro/fluxo-caixa")
@router.get("/financeiro/fluxo-de-caixa")
@router.get("/cadastros/fluxo-caixa")
@router.get("/cadastros/fluxo-de-caixa")
def a_fluxo_caixa():
    return _go("/cadastros/financeiro/fluxo-caixa")

@router.get("/formas-pagamento")
@router.get("/formas-de-pagamento")
@router.get("/meios-pagamento")
@router.get("/meios-de-pagamento")
@router.get("/financeiro/formas-pagamento")
@router.get("/financeiro/formas-de-pagamento")
@router.get("/financeiro/meios-pagamento")
@router.get("/financeiro/meios-de-pagamento")
@router.get("/financeiro/pagamentos")
@router.get("/cadastros/formas-pagamento")
@router.get("/cadastros/formas-de-pagamento")
def a_formas_pagamento():
    return _go("/cadastros/financeiro/formas-pagamento")


# ---- Configurações / aparência ----
@router.get("/configuracoes")
@router.get("/configurações")
@router.get("/configuracoes/estilos")
@router.get("/configuracoes/formatacao")
@router.get("/configuracoes/formatacao-estilos")
@router.get("/configuracoes/estilos-formatacao")
@router.get("/configuracoes/estilos-de-formatacao")
@router.get("/configurações/estilos")
@router.get("/configurações/formatacao")
@router.get("/configurações/estilos-formatacao")
@router.get("/configurações/estilos-de-formatacao")
@router.get("/settings/appearance")
@router.get("/settings/aparencia")
@router.get("/settings/tema")
@router.get("/settings/theme")
@router.get("/settings/styles")
@router.get("/settings/formatting")
@router.get("/settings/estilos")
@router.get("/settings/formatacao")
@router.get("/settings/estilos-formatacao")
@router.get("/settings/estilos-de-formatacao")
@router.get("/estilos")
@router.get("/estilos-formatacao")
@router.get("/estilos-de-formatacao")
@router.get("/aparencia")
@router.get("/aparência")
@router.get("/tema")
def a_settings():
    return _go("/settings")


# Página de diagnóstico simples para conferir se o menu instalado está correto.
@router.get("/verificar-menus")
def verificar_menus(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return _go("/login")
    checks = [
        ("Cotações", "/cadastros/cotacoes"),
        ("Cotações feitas", "/cadastros/cotacoes-feitas"),
        ("Fluxo de cálculo", "/cadastros/fluxo-calculo"),
        ("Voos", "/cadastros/voos"),
        ("Vendas lançadas", "/cadastros/financeiro/vendas"),
        ("Fluxo de caixa", "/cadastros/financeiro/fluxo-caixa"),
        ("Formas de pagamento", "/cadastros/financeiro/formas-pagamento"),
        ("Configurações", "/settings"),
    ]
    return templates.TemplateResponse(request, "diagnostics/menu_check.html", context(request, user=user, checks=checks))
