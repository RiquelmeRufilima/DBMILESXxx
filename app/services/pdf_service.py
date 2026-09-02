from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from fastapi.templating import Jinja2Templates

from ..config import BASE_DIR, STATIC_DIR
from ..models import WebQuote


def file_to_data_uri(relative_path: str | None) -> str | None:
    if not relative_path:
        return None
    path = (BASE_DIR / relative_path).resolve()
    try:
        path.relative_to(BASE_DIR.resolve())
    except ValueError:
        return None
    return path_to_data_uri(path)


def path_to_data_uri(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    suffix = path.suffix.lower()
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
    }.get(suffix, "application/octet-stream")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _json(raw: str | None, default):
    try:
        return json.loads(raw or "")
    except Exception:
        return default


def _company_for_quote(quote: WebQuote):
    user = getattr(quote, "user", None)
    return getattr(user, "company", None) if user else None


def quote_context(quote: WebQuote, overrides: dict[str, Any] | None = None) -> dict:
    overrides = overrides or {}
    inputs = _json(quote.input_json, {})
    breakdown = _json(quote.breakdown_json, {})
    trip = quote.trip
    segments = _json(trip.segments_json, []) if trip else []
    sale_value = quote.commercial.sale_value if quote.commercial and quote.commercial.sale_value is not None else quote.total
    observations = quote.commercial.observations if quote.commercial else None
    profit = sale_value - quote.total
    margin = (profit / quote.total * 100) if quote.total else 0

    settings = getattr(quote, "pdf_settings", None)
    show_company_logo = bool(getattr(settings, "show_company_logo", True))
    show_system_brand = bool(getattr(settings, "show_system_brand", True))
    display_title = getattr(settings, "custom_title", None) or quote.quote_name
    display_client_name = getattr(settings, "custom_client_name", None) or (trip.client_name if trip else None)
    display_notes = getattr(settings, "custom_notes", None) or observations or (trip.notes if trip else None)

    if "show_company_logo" in overrides:
        show_company_logo = bool(overrides["show_company_logo"])
    if "show_system_brand" in overrides:
        show_system_brand = bool(overrides["show_system_brand"])
    display_title = str(overrides.get("display_title") or display_title)
    display_client_name = str(overrides.get("display_client_name") or display_client_name or "").strip() or None
    display_notes = str(overrides.get("display_notes") or display_notes or "").strip() or None
    if overrides.get("sale_value") is not None:
        sale_value = float(overrides["sale_value"])
        profit = sale_value - quote.total
        margin = (profit / quote.total * 100) if quote.total else 0

    company = _company_for_quote(quote)
    company_logo = file_to_data_uri(company.logo_path if company else None)

    return {
        "quote": quote,
        "trip": trip,
        "segments": segments,
        "inputs": inputs,
        "breakdown": breakdown,
        "airline_logo": file_to_data_uri(quote.airline.logo_path if quote.airline else None),
        "company_logo": company_logo,
        "company_name": company.name if company else None,
        "brand_logo": path_to_data_uri(STATIC_DIR / "brand" / "dbmilesx-light.png"),
        "brand_mark": path_to_data_uri(STATIC_DIR / "brand" / "marca.png"),
        "show_company_logo": show_company_logo,
        "show_system_brand": show_system_brand,
        "display_title": display_title,
        "display_client_name": display_client_name,
        "display_notes": display_notes,
        "sale_value": sale_value,
        "observations": observations,
        "profit": profit,
        "margin": margin,
    }


def _browser_pdf_sync(html: str) -> bytes:
    """Fallback sem greenlet/Playwright: usa Edge/Chrome já instalado no computador."""
    candidates = [
        shutil.which("msedge"), shutil.which("msedge.exe"),
        shutil.which("chrome"), shutil.which("chrome.exe"),
        shutil.which("chromium"), shutil.which("chromium.exe"),
    ]
    if os.name == "nt":
        for root in filter(None, [os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"), os.environ.get("LOCALAPPDATA")]):
            candidates.extend([
                os.path.join(root, "Microsoft", "Edge", "Application", "msedge.exe"),
                os.path.join(root, "Google", "Chrome", "Application", "chrome.exe"),
            ])
    browser = next((path for path in candidates if path and os.path.isfile(path)), None)
    if not browser:
        raise RuntimeError("Edge/Chrome não encontrado para gerar o PDF.")

    with tempfile.TemporaryDirectory(prefix="dbmilesx_pdf_") as tmp:
        tmp_path = Path(tmp)
        html_path = tmp_path / "documento.html"
        pdf_path = tmp_path / "documento.pdf"
        html_path.write_text(html, encoding="utf-8")
        cmd = [
            browser, "--headless=new", "--disable-gpu", "--no-sandbox",
            "--disable-extensions", "--disable-software-rasterizer",
            "--no-pdf-header-footer", f"--print-to-pdf={pdf_path}",
            html_path.resolve().as_uri(),
        ]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60, check=False)
        if proc.returncode != 0 or not pdf_path.exists():
            # Compatibilidade com versões mais antigas do Chrome/Edge.
            cmd[1] = "--headless"
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60, check=False)
        if proc.returncode != 0 or not pdf_path.exists():
            detail = (proc.stderr or proc.stdout or b"").decode("utf-8", errors="ignore").strip()
            raise RuntimeError(detail[-500:] or "O navegador não conseguiu gerar o PDF.")
        return pdf_path.read_bytes()


async def _html_to_pdf(html: str) -> bytes:
    """Gera PDF pelo Playwright e cai automaticamente para Edge/Chrome se houver erro de DLL/greenlet."""
    playwright_error = None
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch()
            page = await browser.new_page(viewport={"width": 1240, "height": 1754})
            await page.set_content(html, wait_until="networkidle")
            await page.emulate_media(media="screen")
            pdf = await page.pdf(
                format="A4",
                print_background=True,
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            )
            await browser.close()
            return pdf
    except Exception as exc:
        playwright_error = exc

    try:
        return await asyncio.to_thread(_browser_pdf_sync, html)
    except Exception as browser_exc:
        raise RuntimeError(f"Playwright: {playwright_error}. Fallback Edge/Chrome: {browser_exc}") from browser_exc


async def render_pdf(
    templates: Jinja2Templates,
    quote: WebQuote,
    kind: str = "quote",
    overrides: dict[str, Any] | None = None,
) -> bytes:
    template_name = {
        "quote": "pdf/quote.html",
        "cost": "pdf/cost.html",
        "profit": "pdf/profit.html",
    }.get(kind, "pdf/quote.html")
    css = (STATIC_DIR / "css" / "pdf.css").read_text(encoding="utf-8")
    template = templates.get_template(template_name)
    html = template.render(**quote_context(quote, overrides), pdf_css=css, pdf_mode=True, document_kind=kind)
    return await _html_to_pdf(html)


def group_pdf_context(
    quotes: list[WebQuote],
    *,
    sale_values: dict[str, float] | None = None,
    title: str = "Cotação em grupo",
    subtitle: str = "",
    notes: str = "",
    group_image_path: str | None = None,
    show_group_image: bool = True,
    show_company_logo: bool = True,
    show_system_brand: bool = True,
) -> dict:
    sale_values = sale_values or {}
    items: list[dict] = []
    grand_total = 0.0
    for quote in quotes:
        sale_value = float(sale_values.get(str(quote.id), quote.commercial.sale_value if quote.commercial and quote.commercial.sale_value is not None else quote.total))
        grand_total += sale_value
        items.append({**quote_context(quote, {"sale_value": sale_value, "show_company_logo": show_company_logo, "show_system_brand": show_system_brand}), "sale_value": sale_value})

    company = _company_for_quote(quotes[0]) if quotes else None
    return {
        "items": items,
        "quotes": quotes,
        "group_title": title.strip() or "Cotação em grupo",
        "group_subtitle": subtitle.strip(),
        "group_notes": notes.strip(),
        "group_image": file_to_data_uri(group_image_path) if show_group_image else None,
        "show_group_image": show_group_image,
        "company_logo": file_to_data_uri(company.logo_path if company else None),
        "company_name": company.name if company else None,
        "brand_logo": path_to_data_uri(STATIC_DIR / "brand" / "dbmilesx-light.png"),
        "brand_mark": path_to_data_uri(STATIC_DIR / "brand" / "marca.png"),
        "show_company_logo": show_company_logo,
        "show_system_brand": show_system_brand,
        "grand_total": grand_total,
    }


async def render_group_pdf(templates: Jinja2Templates, context_data: dict) -> bytes:
    css = (STATIC_DIR / "css" / "pdf.css").read_text(encoding="utf-8")
    template = templates.get_template("pdf/group.html")
    html = template.render(**context_data, pdf_css=css, pdf_mode=True, document_kind="group")
    return await _html_to_pdf(html)
