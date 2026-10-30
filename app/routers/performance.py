"""Diagnóstico de latência de leitura para usuários autenticados.

Nenhuma requisição do laboratório grava dados; medições acontecem no navegador,
com a sessão do próprio usuário e sem expor conteúdo de cotação no relatório.
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import require_user
from ..web import context, templates

router = APIRouter(tags=["performance"])


@router.get("/diagnostics/performance")
def performance_page(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    return templates.TemplateResponse(
        request, "diagnostics/performance.html", context(request, user=user)
    )
