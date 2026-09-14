from __future__ import annotations

import base64
import json
import re
import secrets
import time
import uuid
from urllib.parse import unquote, urlparse

from fastapi import APIRouter, Depends, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from ..config import AIRLINE_UPLOAD_DIR
from ..database import get_db
from ..dependencies import current_user
from ..models import Airline, CalculationField, CalculationType
from ..security import validate_csrf_token
from ..services.formula_engine import validate_formula
from ..services.storage import blob_delete, blob_get, blob_put, blob_ready
from ..services.uploads import AIRLINE_IMAGE_EXTENSIONS, delete_relative_upload, save_upload_image
from ..web import context, flash, templates

router = APIRouter(prefix="/airlines", tags=["airlines"])

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def slugify(value: str) -> str:
    text = value.strip().lower()
    replacements = {
        "á": "a", "à": "a", "ã": "a", "â": "a",
        "é": "e", "ê": "e", "í": "i", "ó": "o", "ô": "o", "õ": "o",
        "ú": "u", "ç": "c",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or secrets.token_hex(4)


def _visibility(user):
    if user.company_id:
        return or_(Airline.builtin.is_(True), Airline.owner_company_id == user.company_id)
    return or_(Airline.builtin.is_(True), Airline.owner_user_id == user.id)


def _can_manage(user, airline: Airline) -> bool:
    if airline.builtin:
        return False
    if user.company_id:
        return airline.owner_company_id == user.company_id and user.role in {"admin", "gerente"}
    return airline.owner_user_id == user.id


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    value = str(value or "")
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _blob_logo_route(blob_url: str) -> str:
    return f"airlines/logo-file/{_b64url_encode(blob_url.encode('utf-8'))}"


def _blob_url_from_logo_path(path: str | None) -> str | None:
    value = str(path or "").strip()
    marker = "airlines/logo-file/"
    if not value.startswith(marker):
        return None
    try:
        return _b64url_decode(value[len(marker):]).decode("utf-8")
    except Exception:
        return None


def _valid_blob_logo_url(blob_url: str) -> bool:
    try:
        parsed = urlparse(str(blob_url or "").strip())
    except Exception:
        return False
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    return host.endswith(".private.blob.vercel-storage.com") or host.endswith(".blob.vercel-storage.com")


def _delete_airline_logo(path: str | None) -> None:
    blob_url = _blob_url_from_logo_path(path)
    if blob_url:
        try:
            blob_delete(blob_url)
        except Exception:
            # A troca/remoção da logo não deve falhar só porque o arquivo antigo
            # já não existe no Blob.
            pass
        return
    delete_relative_upload(path)


async def _save_logo(upload: UploadFile | None, user, *, prefix: str = "airline") -> str | None:
    if upload is None or not getattr(upload, "filename", None):
        return None

    # Em localhost continuamos usando uploads/airlines. No Vercel, se o Blob
    # estiver conectado, a imagem vai para armazenamento persistente.
    if not blob_ready():
        return await save_upload_image(
            upload,
            AIRLINE_UPLOAD_DIR,
            max_bytes=4 * 1024 * 1024,
            allowed_extensions=AIRLINE_IMAGE_EXTENSIONS,
            filename_prefix=prefix,
        )

    filename = str(upload.filename or "").strip()
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if ext not in AIRLINE_IMAGE_EXTENSIONS:
        allowed = ", ".join(sorted(AIRLINE_IMAGE_EXTENSIONS))
        raise ValueError(f"Formato de imagem não permitido. Use: {allowed}.")

    content = await upload.read()
    if not content:
        raise ValueError("A imagem enviada está vazia.")
    if len(content) > 4 * 1024 * 1024:
        raise ValueError("A imagem deve ter no máximo 4 MB.")

    content_type = str(getattr(upload, "content_type", "") or "").strip().lower()
    if not content_type.startswith("image/"):
        content_type = {
            ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
            ".webp": "image/webp", ".svg": "image/svg+xml",
        }.get(ext, "application/octet-stream")

    if getattr(user, "company_id", None):
        root = f"companies/{int(user.company_id)}/logos/airlines"
    else:
        root = f"users/{int(user.id)}/logos/airlines"
    pathname = f"{root}/{prefix}-{int(time.time())}-{uuid.uuid4().hex[:10]}{ext}"

    try:
        result = blob_put(pathname, content, content_type)
    except Exception as exc:
        raise ValueError(f"Não foi possível salvar a logo no Vercel Blob: {exc}") from exc

    blob_url = str(result.get("url") or result.get("downloadUrl") or "").strip()
    if not blob_url or not _valid_blob_logo_url(blob_url):
        raise ValueError("O Vercel Blob não devolveu uma URL válida para a logo.")
    return _blob_logo_route(blob_url)


def _parse_fields(raw: str) -> list[dict]:
    try:
        fields = json.loads(raw or "[]")
    except json.JSONDecodeError as exc:
        raise ValueError("A lista de campos está inválida.") from exc
    if not isinstance(fields, list):
        raise ValueError("Os campos enviados são inválidos.")

    clean: list[dict] = []
    seen: set[str] = set()
    for index, item in enumerate(fields):
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        label = str(item.get("label") or "").strip()
        field_type = str(item.get("field_type") or "number").strip()
        if not key or not label:
            continue
        if not _IDENTIFIER.match(key):
            raise ValueError(f"A chave '{key}' não é válida. Use letras, números e _; não comece com número.")
        if key in seen:
            raise ValueError(f"A chave '{key}' foi repetida.")
        if key in {"passageiros", "bebes", "bagagens"}:
            raise ValueError(f"A chave '{key}' é reservada pelo sistema.")
        seen.add(key)
        clean.append(
            {
                "key": key,
                "label": label,
                "field_type": field_type if field_type in {"number", "integer", "percent", "text", "select"} else "number",
                "default_value": str(item.get("default_value") or "0"),
                "required": bool(item.get("required")),
                "min_value": item.get("min_value"),
                "max_value": item.get("max_value"),
                "step": item.get("step"),
                "help_text": str(item.get("help_text") or "").strip() or None,
                "options": item.get("options") if isinstance(item.get("options"), list) else None,
                "order_index": index,
            }
        )
    return clean


def _add_fields(db: Session, calc_type: CalculationType, fields: list[dict]) -> None:
    for item in fields:
        db.add(
            CalculationField(
                calculation_type_id=calc_type.id,
                key=item["key"],
                label=item["label"],
                field_type=item["field_type"],
                default_value=item["default_value"],
                required=item["required"],
                min_value=float(item["min_value"]) if item["min_value"] not in {None, ""} else None,
                max_value=float(item["max_value"]) if item["max_value"] not in {None, ""} else None,
                step=float(item["step"]) if item["step"] not in {None, ""} else None,
                help_text=item["help_text"],
                options_json=json.dumps(item["options"], ensure_ascii=False) if item["options"] else None,
                order_index=item["order_index"],
            )
        )


@router.get("")
def airline_list(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    airlines = db.scalars(
        select(Airline)
        .where(Airline.active.is_(True), _visibility(user))
        .options(selectinload(Airline.calculation_types))
        .order_by(Airline.builtin.desc(), Airline.name)
    ).all()
    return templates.TemplateResponse(request, "airlines/list.html", context(request, user=user, airlines=airlines))


@router.get("/new")
def new_airline_page(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if user.company_id and user.role not in {"admin", "gerente"}:
        flash(request, "Somente administradores e gerentes podem criar companhias para a empresa.", "error")
        return RedirectResponse("/airlines", status_code=303)
    return templates.TemplateResponse(request, "airlines/form.html", context(request, user=user))


@router.post("/new")
async def create_airline(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if user.company_id and user.role not in {"admin", "gerente"}:
        flash(request, "Você não tem permissão para criar companhias.", "error")
        return RedirectResponse("/airlines", status_code=303)

    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada. Tente novamente.", "error")
        return RedirectResponse("/airlines/new", status_code=303)

    name = str(form.get("name") or "").strip()
    calc_name = str(form.get("calculation_name") or "Cálculo padrão").strip() or "Cálculo padrão"
    formula = str(form.get("formula") or "(milhas * milheiro) + taxa").strip()
    apply_mode = str(form.get("apply_mode") or "total")
    color = str(form.get("color") or "#24b7d3")
    if len(name) < 2:
        flash(request, "O nome da companhia é obrigatório.", "error")
        return RedirectResponse("/airlines/new", status_code=303)

    try:
        fields = _parse_fields(str(form.get("fields_json") or "[]"))
    except ValueError as exc:
        flash(request, str(exc), "error")
        return RedirectResponse("/airlines/new", status_code=303)

    # O cálculo padrão solicitado sempre nasce com milhas, milheiro e taxa.
    if not fields:
        fields = [
            {"key": "milhas", "label": "Milhas", "field_type": "number", "default_value": "0", "required": False, "min_value": 0, "max_value": None, "step": 0.001, "help_text": None, "options": None, "order_index": 0},
            {"key": "milheiro", "label": "Valor do milheiro", "field_type": "number", "default_value": "0", "required": False, "min_value": 0, "max_value": None, "step": 0.01, "help_text": None, "options": None, "order_index": 1},
            {"key": "taxa", "label": "Taxa", "field_type": "number", "default_value": "0", "required": False, "min_value": 0, "max_value": None, "step": 0.01, "help_text": None, "options": None, "order_index": 2},
        ]

    allowed_variables = {item["key"] for item in fields} | {"passageiros", "bebes", "bagagens"}
    valid, message = validate_formula(formula, allowed_variables)
    if not valid:
        flash(request, f"Fórmula inválida: {message}", "error")
        return RedirectResponse("/airlines/new", status_code=303)

    upload = form.get("logo")
    try:
        logo_path = await _save_logo(upload if getattr(upload, "filename", None) else None, user)
    except ValueError as exc:
        flash(request, str(exc), "error")
        return RedirectResponse("/airlines/new", status_code=303)

    airline = Airline(
        owner_company_id=user.company_id,
        owner_user_id=None if user.company_id else user.id,
        name=name,
        slug=f"{slugify(name)}-{secrets.token_hex(3)}",
        logo_path=logo_path,
        color=color if re.match(r"^#[0-9A-Fa-f]{6}$", color) else "#24b7d3",
        engine_type="formula",
        active=True,
        builtin=False,
    )
    db.add(airline)
    db.flush()

    calc_type = CalculationType(
        airline_id=airline.id,
        name=calc_name,
        slug=f"{slugify(calc_name)}-{secrets.token_hex(2)}",
        description=str(form.get("description") or "").strip() or None,
        formula=formula,
        apply_mode="per_passenger" if apply_mode == "per_passenger" else "total",
        active=True,
        is_default=True,
    )
    db.add(calc_type)
    db.flush()
    _add_fields(db, calc_type, fields)
    db.commit()

    flash(request, f"Companhia '{name}' criada com sucesso.", "success")
    return RedirectResponse(f"/airlines/{airline.id}", status_code=303)


@router.get("/logo-file/{blob_ref}")
def serve_private_airline_logo(blob_ref: str, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return Response(status_code=401)

    try:
        blob_url = _b64url_decode(blob_ref).decode("utf-8")
    except Exception:
        return Response(status_code=404)
    if not _valid_blob_logo_url(blob_url):
        return Response(status_code=404)

    stored_path = _blob_logo_route(blob_url)
    airline = db.scalar(select(Airline).where(Airline.logo_path == stored_path, _visibility(user)))
    if airline is None:
        return Response(status_code=404)

    try:
        content, content_type = blob_get(blob_url)
    except Exception:
        return Response(status_code=404)

    return Response(
        content=content,
        media_type=content_type or "image/png",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.get("/{airline_id}")
def manage_airline(airline_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    airline = db.scalar(
        select(Airline)
        .where(Airline.id == airline_id, _visibility(user))
        .options(selectinload(Airline.calculation_types).selectinload(CalculationType.fields))
    )
    if airline is None:
        flash(request, "Companhia não encontrada.", "error")
        return RedirectResponse("/airlines", status_code=303)
    return templates.TemplateResponse(request, "airlines/manage.html",
        context(request, user=user, airline=airline, can_manage=_can_manage(user, airline)),
    )


@router.post("/{airline_id}/logo")
async def update_airline_logo(airline_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    airline = db.get(Airline, airline_id)
    if airline is None or not _can_manage(user, airline):
        flash(request, "Você não pode alterar essa companhia.", "error")
        return RedirectResponse("/airlines", status_code=303)

    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse(f"/airlines/{airline_id}", status_code=303)

    upload = form.get("logo")
    try:
        logo_path = await _save_logo(upload if getattr(upload, "filename", None) else None, user, prefix=f"airline-{airline.id}")
    except ValueError as exc:
        flash(request, str(exc), "error")
        return RedirectResponse(f"/airlines/{airline_id}", status_code=303)
    if not logo_path:
        flash(request, "Selecione uma imagem.", "error")
        return RedirectResponse(f"/airlines/{airline_id}", status_code=303)

    old_path = airline.logo_path
    airline.logo_path = logo_path
    db.commit()
    _delete_airline_logo(old_path)
    flash(request, "Logo da companhia atualizada e salva.", "success")
    return RedirectResponse(f"/airlines/{airline_id}", status_code=303)


@router.post("/{airline_id}/logo/remove")
async def remove_airline_logo(airline_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    airline = db.get(Airline, airline_id)
    if airline is None or not _can_manage(user, airline):
        flash(request, "Você não pode alterar essa companhia.", "error")
        return RedirectResponse("/airlines", status_code=303)

    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse(f"/airlines/{airline_id}", status_code=303)

    old_path = airline.logo_path
    airline.logo_path = None
    db.commit()
    _delete_airline_logo(old_path)
    flash(request, "Logo removida.", "success")
    return RedirectResponse(f"/airlines/{airline_id}", status_code=303)


@router.post("/{airline_id}/types")
async def add_calculation_type(airline_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    airline = db.get(Airline, airline_id)
    if airline is None or not _can_manage(user, airline):
        flash(request, "Você não pode alterar essa companhia.", "error")
        return RedirectResponse("/airlines", status_code=303)

    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse(f"/airlines/{airline_id}", status_code=303)

    name = str(form.get("calculation_name") or "").strip()
    formula = str(form.get("formula") or "").strip()
    apply_mode = str(form.get("apply_mode") or "total")
    try:
        fields = _parse_fields(str(form.get("fields_json") or "[]"))
    except ValueError as exc:
        flash(request, str(exc), "error")
        return RedirectResponse(f"/airlines/{airline_id}", status_code=303)

    if not name or not formula or not fields:
        flash(request, "Informe o nome, a fórmula e ao menos um campo.", "error")
        return RedirectResponse(f"/airlines/{airline_id}", status_code=303)

    allowed_variables = {item["key"] for item in fields} | {"passageiros", "bebes", "bagagens"}
    valid, message = validate_formula(formula, allowed_variables)
    if not valid:
        flash(request, f"Fórmula inválida: {message}", "error")
        return RedirectResponse(f"/airlines/{airline_id}", status_code=303)

    calc_type = CalculationType(
        airline_id=airline.id,
        name=name,
        slug=f"{slugify(name)}-{secrets.token_hex(2)}",
        description=str(form.get("description") or "").strip() or None,
        formula=formula,
        apply_mode="per_passenger" if apply_mode == "per_passenger" else "total",
        active=True,
        is_default=False,
    )
    db.add(calc_type)
    db.flush()
    _add_fields(db, calc_type, fields)
    db.commit()
    flash(request, "Novo tipo de cálculo criado.", "success")
    return RedirectResponse(f"/airlines/{airline_id}", status_code=303)
