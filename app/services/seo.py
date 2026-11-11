"""SEO do DBMILESX: páginas públicas, robots.txt, sitemap.xml e llms.txt.

Só as telas abertas (login, cadastro, termos e privacidade) entram no Google.
Todo o resto exige login e fica fora da busca (noindex + Disallow).

Variáveis de ambiente (todas opcionais):
- SITE_URL: endereço oficial, ex.: https://dbmilesx.com.br (sem barra no fim).
  Sem ela, usa o domínio de produção que o Vercel informa.
- GA_MEASUREMENT_ID: ID do Google Analytics 4, ex.: G-ABC123XYZ.
- GOOGLE_SITE_VERIFICATION: código da meta tag do Google Search Console.
"""
from __future__ import annotations

import os
import re
from datetime import date

from ..config import APP_URL

SITE_NAME = "DBMILESX"
# Data da última mudança de conteúdo das páginas públicas (vai no sitemap).
CONTENT_UPDATED = date(2026, 11, 11)

KEYWORDS = (
    "sistema para agência de viagens",
    "cotação de passagens aéreas",
    "calculadora de milhas",
    "cotação com milhas",
    "emissão com milhas",
    "gestão de cotações",
    "consolidadora",
)

# Páginas públicas que podem aparecer no Google: caminho -> (título, descrição, prioridade).
PUBLIC_PAGES: dict[str, tuple[str, str, str]] = {
    "/login": (
        "DBMILESX | Sistema de cotação de passagens aéreas e milhas para agências",
        "Calcule passagens com milhas, deságio ou consolidadora, compare companhias, "
        "adicione seu lucro e envie a cotação pronta pelo WhatsApp. Sistema para agências de viagens.",
        "1.0",
    ),
    "/register": (
        "Criar conta | DBMILESX, sistema para agências de viagens",
        "Crie a conta da sua agência no DBMILESX e organize cotações de passagens aéreas, "
        "cálculo em milhas, vendas e acompanhamentos da equipe.",
        "0.8",
    ),
    "/terms": (
        "Termos de Serviço | DBMILESX",
        "Termos de Serviço do DBMILESX, sistema de cotação de passagens aéreas e milhas para agências de viagens.",
        "0.3",
    ),
    "/privacy": (
        "Política de Privacidade | DBMILESX",
        "Como o DBMILESX trata os dados das agências, das equipes e dos clientes, conforme a LGPD.",
        "0.3",
    ),
}

_GA_RE = re.compile(r"^G-[A-Z0-9]{4,16}$")
_VERIFY_RE = re.compile(r"^[A-Za-z0-9_\-]{10,100}$")


def site_url() -> str:
    raw = (os.getenv("SITE_URL") or APP_URL or "").strip().rstrip("/")
    if raw and not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    return raw


def is_preview() -> bool:
    """Deploys de teste do Vercel nunca devem ir para o Google."""
    return os.getenv("VERCEL_ENV", "").strip().lower() == "preview"


def ga_measurement_id() -> str:
    value = os.getenv("GA_MEASUREMENT_ID", "").strip().upper()
    return value if _GA_RE.match(value) and not is_preview() else ""


def google_site_verification() -> str:
    value = os.getenv("GOOGLE_SITE_VERIFICATION", "").strip()
    return value if _VERIFY_RE.match(value) else ""


def page_seo(path: str) -> dict:
    """Título/descrição/indexação da página. Telas internas: noindex."""
    title, description, _priority = PUBLIC_PAGES.get(path, ("", "", ""))
    public = bool(title) and not is_preview()
    base = site_url()
    return {
        "indexable": public,
        "title": title,
        "description": description or "DBMILESX: sistema de cotação de passagens aéreas e milhas para agências de viagens.",
        "canonical": f"{base}{path}" if public and base else "",
        "image": f"{base}/static/icons/icon-512.png" if base else "/static/icons/icon-512.png",
        "keywords": ", ".join(KEYWORDS),
    }


def robots_txt() -> str:
    if is_preview():
        return "# Deploy de teste: fora da busca.\nUser-agent: *\nDisallow: /\n"
    lines = [
        "# DBMILESX: só as páginas públicas entram na busca.",
        "# As telas do sistema exigem login.",
        "User-agent: *",
        "Allow: /$",
        *[f"Allow: {path}$" for path in PUBLIC_PAGES],
        "Allow: /static/",
        "Allow: /llms.txt",
        "Disallow: /",
        "",
        f"Sitemap: {site_url()}/sitemap.xml",
        "",
    ]
    return "\n".join(lines)


def sitemap_xml() -> str:
    base = site_url()
    items = []
    for path, (_title, _desc, priority) in PUBLIC_PAGES.items():
        items.append(
            "  <url>\n"
            f"    <loc>{base}{path}</loc>\n"
            f"    <lastmod>{CONTENT_UPDATED.isoformat()}</lastmod>\n"
            f"    <priority>{priority}</priority>\n"
            "  </url>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(items)
        + "\n</urlset>\n"
    )


def llms_txt() -> str:
    base = site_url()
    return f"""# DBMILESX

> Sistema web em português para agências de viagens fazerem cotações de passagens aéreas: cálculo em milhas, deságio, tarifa de companhia ou consolidadora, lucro, mensagem e arte prontas para o cliente, e o acompanhamento da venda pela equipe.

O DBMILESX é usado por agências e emissores de passagens no Brasil. O acesso às telas do sistema exige login; as páginas abaixo são públicas.

## O que o sistema faz

- Calculadora de passagens em milhas (milhas por passageiro, valor do milheiro e taxas), deságio sobre o valor do site e tarifas de consolidadoras ou sistemas.
- Comparação de opções de várias companhias numa mesma cotação, da mais barata para a mais cara.
- Lucro e margem por opção, com parcelamento no cartão com ou sem juros e cálculo do lucro real.
- Mensagem pronta para o WhatsApp, arte da cotação em imagem e PDF para o cliente. Em voo operado por outra companhia, a arte mostra quem opera.
- Quadro de cotações por etapa da venda, responsáveis, acompanhamentos (hospedagem, transporte, seguros) e tutoriais em vídeo para a equipe.

## Páginas públicas

- [Entrar no DBMILESX]({base}/login): acesso das agências cadastradas.
- [Criar conta]({base}/register): cadastro de uma nova agência.
- [Termos de Serviço]({base}/terms)
- [Política de Privacidade]({base}/privacy)
"""
