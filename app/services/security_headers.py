"""Cabeçalhos extras com custo constante, sem alterar o comportamento das páginas.

A política é APENAS de monitoramento: o DBMILESX possui JS e CSS inline.
Uma CSP obrigatória sem eliminar esses trechos poderia quebrar telas e botões.
"""
from __future__ import annotations

# Não há endpoints de coleta ou envio de relatórios: nenhuma requisição extra.
# Política conservadora para observar violações nos navegadores, sem bloqueios.
CSP_REPORT_ONLY = "; ".join((
    "default-src 'self'",
    "base-uri 'self'",
    "object-src 'none'",
    "frame-ancestors 'self'",
    "form-action 'self'",
    "script-src 'self' 'unsafe-inline' https:",
    "style-src 'self' 'unsafe-inline' https:",
    "img-src 'self' data: blob: https:",
    "font-src 'self' data: https:",
    "connect-src 'self' https: wss:",
    "worker-src 'self' blob:",
    "frame-src 'self' https:",
))


def apply_phase2_headers(response):
    """Sem DB, I/O, requisição externa ou alteração no HTML retornado."""
    headers = response.headers
    headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")
    if (
        "text/html" in (headers.get("content-type") or "").lower()
        and "Content-Security-Policy" not in headers
        and "Content-Security-Policy-Report-Only" not in headers
    ):
        headers["Content-Security-Policy-Report-Only"] = CSP_REPORT_ONLY
    return response
