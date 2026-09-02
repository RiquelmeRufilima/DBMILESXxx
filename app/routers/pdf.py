from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..config import GROUP_UPLOAD_DIR
from ..database import get_db
from ..dependencies import current_user
from ..models import QuoteCommercial, QuotePdfSetting, WebQuote, WebUser
from ..security import validate_csrf_token
from ..services.pdf_service import group_pdf_context, quote_context, render_group_pdf, render_pdf
from ..services.uploads import delete_relative_upload, save_upload_image
from ..web import context, flash, templates

router = APIRouter(prefix="/quotes", tags=["pdf"])


def _quote_options():
    return (
        selectinload(WebQuote.airline),
        selectinload(WebQuote.calculation_type),
        selectinload(WebQuote.user).selectinload(WebUser.company),
        selectinload(WebQuote.trip),
        selectinload(WebQuote.commercial),
        selectinload(WebQuote.pdf_settings),
    )


def _get_quote(db: Session, quote_id: int):
    return db.scalar(select(WebQuote).where(WebQuote.id == quote_id).options(*_quote_options()))


def _allowed(user, quote: WebQuote | None) -> bool:
    return bool(quote and (quote.user_id == user.id or (user.company_id and quote.company_id == user.company_id)))


def _load_group_quotes(db: Session, user, quote_ids: list[int]) -> list[WebQuote]:
    if not quote_ids:
        return []
    access_filter = WebQuote.company_id == user.company_id if user.company_id else WebQuote.user_id == user.id
    found = db.scalars(
        select(WebQuote)
        .where(WebQuote.id.in_(quote_ids), access_filter)
        .options(*_quote_options())
    ).all()
    by_id = {item.id: item for item in found}
    return [by_id[item_id] for item_id in quote_ids if item_id in by_id]


@router.post("/group/prepare")
async def prepare_group_pdf(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/calculations/history", status_code=303)

    quote_ids: list[int] = []
    for raw in form.getlist("quote_ids"):
        try:
            quote_ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    quote_ids = list(dict.fromkeys(quote_ids))[:100]
    quotes = _load_group_quotes(db, user, quote_ids)
    if not quotes:
        flash(request, "Selecione ao menos uma cotação para o PDF em grupo.", "error")
        return RedirectResponse("/calculations/history", status_code=303)

    request.session["group_pdf_draft"] = {
        "quote_ids": [item.id for item in quotes],
        "sale_values": {
            str(item.id): float(item.commercial.sale_value if item.commercial and item.commercial.sale_value is not None else item.total)
            for item in quotes
        },
        "title": "Cotação em grupo",
        "subtitle": "",
        "notes": "",
        "group_image_path": None,
        "show_group_image": True,
        "show_company_logo": True,
        "show_system_brand": True,
    }
    return RedirectResponse("/quotes/group/preview", status_code=303)


@router.get("/group/preview", response_class=HTMLResponse)
def group_preview(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    draft = request.session.get("group_pdf_draft") or {}
    quote_ids = [int(item) for item in draft.get("quote_ids", []) if str(item).isdigit()]
    quotes = _load_group_quotes(db, user, quote_ids)
    if not quotes:
        flash(request, "O rascunho do PDF em grupo expirou. Selecione as cotações novamente.", "error")
        return RedirectResponse("/calculations/history", status_code=303)

    pdf_data = group_pdf_context(
        quotes,
        sale_values=draft.get("sale_values") or {},
        title=draft.get("title") or "Cotação em grupo",
        subtitle=draft.get("subtitle") or "",
        notes=draft.get("notes") or "",
        group_image_path=draft.get("group_image_path"),
        show_group_image=bool(draft.get("show_group_image", True)),
        show_company_logo=bool(draft.get("show_company_logo", True)),
        show_system_brand=bool(draft.get("show_system_brand", True)),
    )
    return templates.TemplateResponse(
        request,
        "pdf/group_preview.html",
        context(request, user=user, draft=draft, **pdf_data),
    )


@router.post("/group/update")
async def update_group_preview(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/quotes/group/preview", status_code=303)

    draft = dict(request.session.get("group_pdf_draft") or {})
    quote_ids = [int(item) for item in draft.get("quote_ids", []) if str(item).isdigit()]
    quotes = _load_group_quotes(db, user, quote_ids)
    if not quotes:
        flash(request, "Selecione as cotações novamente.", "error")
        return RedirectResponse("/calculations/history", status_code=303)

    sale_values: dict[str, float] = {}
    for quote in quotes:
        try:
            sale_values[str(quote.id)] = max(0.0, float(form.get(f"sale_{quote.id}") or quote.total))
        except (TypeError, ValueError):
            sale_values[str(quote.id)] = quote.total

    old_image = draft.get("group_image_path")
    upload = form.get("group_image")
    try:
        new_image = await save_upload_image(
            upload if getattr(upload, "filename", None) else None,
            GROUP_UPLOAD_DIR,
            max_bytes=8 * 1024 * 1024,
            filename_prefix=f"group-user-{user.id}",
        )
    except ValueError as exc:
        flash(request, str(exc), "error")
        return RedirectResponse("/quotes/group/preview", status_code=303)

    if new_image:
        draft["group_image_path"] = new_image
        if old_image and old_image != new_image:
            delete_relative_upload(old_image)

    if str(form.get("remove_group_image") or "") == "1":
        delete_relative_upload(draft.get("group_image_path"))
        draft["group_image_path"] = None

    draft.update(
        {
            "sale_values": sale_values,
            "title": str(form.get("title") or "Cotação em grupo").strip()[:220] or "Cotação em grupo",
            "subtitle": str(form.get("subtitle") or "").strip()[:500],
            "notes": str(form.get("notes") or "").strip()[:4000],
            "show_group_image": form.get("show_group_image") is not None,
            "show_company_logo": form.get("show_company_logo") is not None,
            "show_system_brand": form.get("show_system_brand") is not None,
        }
    )
    request.session["group_pdf_draft"] = draft
    flash(request, "Prévia em grupo atualizada.", "success")
    return RedirectResponse("/quotes/group/preview", status_code=303)


@router.get("/group/pdf")
async def group_pdf(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    draft = request.session.get("group_pdf_draft") or {}
    quote_ids = [int(item) for item in draft.get("quote_ids", []) if str(item).isdigit()]
    quotes = _load_group_quotes(db, user, quote_ids)
    if not quotes:
        flash(request, "O rascunho expirou. Selecione as cotações novamente.", "error")
        return RedirectResponse("/calculations/history", status_code=303)

    pdf_data = group_pdf_context(
        quotes,
        sale_values=draft.get("sale_values") or {},
        title=draft.get("title") or "Cotação em grupo",
        subtitle=draft.get("subtitle") or "",
        notes=draft.get("notes") or "",
        group_image_path=draft.get("group_image_path"),
        show_group_image=bool(draft.get("show_group_image", True)),
        show_company_logo=bool(draft.get("show_company_logo", True)),
        show_system_brand=bool(draft.get("show_system_brand", True)),
    )
    try:
        pdf = await render_group_pdf(templates, pdf_data)
    except Exception as exc:
        flash(request, f"Não foi possível gerar o PDF em grupo: {exc}", "error")
        return RedirectResponse("/quotes/group/preview", status_code=303)
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="cotacao-em-grupo.pdf"'},
    )


@router.post("/{quote_id}/commercial")
def save_commercial(
    quote_id: int,
    request: Request,
    sale_value: float = Form(...),
    observations: str = Form(""),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    quote = _get_quote(db, quote_id)
    if not _allowed(user, quote):
        flash(request, "Cotação não encontrada.", "error")
        return RedirectResponse("/calculations/history", status_code=303)
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse(f"/calculations/result/{quote_id}", status_code=303)
    item = quote.commercial or QuoteCommercial(quote_id=quote.id)
    if quote.commercial is None:
        db.add(item)
    item.sale_value = max(0, sale_value)
    item.observations = observations.strip()[:4000] or None
    db.commit()
    flash(request, "Valor de venda e observações salvos.", "success")
    return RedirectResponse(f"/calculations/result/{quote_id}", status_code=303)


@router.post("/{quote_id}/preview-settings")
async def save_preview_settings(quote_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    quote = _get_quote(db, quote_id)
    if not _allowed(user, quote):
        flash(request, "Cotação não encontrada.", "error")
        return RedirectResponse("/calculations/history", status_code=303)

    form = await request.form()
    kind = str(form.get("kind") or "quote")
    kind = kind if kind in {"quote", "cost", "profit"} else "quote"
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse(f"/quotes/{quote_id}/preview/{kind}", status_code=303)

    settings = quote.pdf_settings or QuotePdfSetting(quote_id=quote.id)
    if quote.pdf_settings is None:
        db.add(settings)
    settings.show_company_logo = form.get("show_company_logo") is not None
    settings.show_system_brand = form.get("show_system_brand") is not None
    settings.custom_title = str(form.get("custom_title") or "").strip()[:220] or None
    settings.custom_client_name = str(form.get("custom_client_name") or "").strip()[:180] or None
    settings.custom_notes = str(form.get("custom_notes") or "").strip()[:4000] or None

    try:
        sale_value = max(0.0, float(form.get("sale_value") or quote.total))
    except (TypeError, ValueError):
        sale_value = quote.total
    commercial = quote.commercial or QuoteCommercial(quote_id=quote.id)
    if quote.commercial is None:
        db.add(commercial)
    commercial.sale_value = sale_value
    if settings.custom_notes:
        commercial.observations = settings.custom_notes

    db.commit()
    flash(request, "Prévia e opções do PDF salvas.", "success")
    return RedirectResponse(f"/quotes/{quote_id}/preview/{kind}", status_code=303)


@router.get("/{quote_id}/preview", response_class=HTMLResponse)
def legacy_preview(quote_id: int):
    return RedirectResponse(f"/quotes/{quote_id}/preview/quote", status_code=303)


@router.get("/{quote_id}/preview/{kind}", response_class=HTMLResponse)
def quote_preview(quote_id: int, kind: str, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    quote = _get_quote(db, quote_id)
    if not _allowed(user, quote):
        flash(request, "Cotação não encontrada.", "error")
        return RedirectResponse("/calculations/history", status_code=303)
    kind = kind if kind in {"quote", "cost", "profit"} else "quote"
    return templates.TemplateResponse(
        request,
        "pdf/preview.html",
        context(request, user=user, kind=kind, **quote_context(quote)),
    )


@router.get("/{quote_id}/pdf")
async def legacy_pdf(quote_id: int):
    return RedirectResponse(f"/quotes/{quote_id}/pdf/quote", status_code=303)


@router.get("/{quote_id}/pdf/{kind}")
async def quote_pdf(quote_id: int, kind: str, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    quote = _get_quote(db, quote_id)
    if not _allowed(user, quote):
        flash(request, "Cotação não encontrada.", "error")
        return RedirectResponse("/calculations/history", status_code=303)
    kind = kind if kind in {"quote", "cost", "profit"} else "quote"
    try:
        pdf = await render_pdf(templates, quote, kind)
    except Exception as exc:
        flash(request, f"O gerador de PDF ainda não está pronto neste computador: {exc}. Execute instalar_pdf.bat uma vez.", "error")
        return RedirectResponse(f"/quotes/{quote.id}/preview/{kind}", status_code=303)
    names = {"quote": "cotacao", "cost": "custo", "profit": "lucro"}
    filename = f"{names[kind]}-{quote.id}.pdf"
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{filename}"'})
