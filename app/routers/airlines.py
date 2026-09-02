from __future__ import annotations

import json
import re
import secrets

from fastapi import APIRouter, Depends, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from ..config import AIRLINE_UPLOAD_DIR
from ..database import get_db
from ..dependencies import current_user
from ..models import Airline, CalculationField, CalculationType
from ..security import validate_csrf_token
from ..services.formula_engine import validate_formula
from ..services.uploads import AIRLINE_IMAGE_EXTENSIONS, delete_relative_upload, save_upload_image
from ..web import context, flash, templates

router = APIRouter(prefix="/airlines", tags=["airlines"])

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


_LEGACY_EDIT_FORMULAS = {
    "latam_milhas": "(milhas * milheiro * passageiros) + (taxa * passageiros) + (bagagens * bagagem_unitaria)",
    "gol_smiles": "(milhas * milheiro) + taxa + (bagagens * bagagem_unitaria)",
    "gol_desagio": "valor_gol - (valor_gol * desagio / 100) + (bagagens * bagagem_unitaria)",
    "azul_pontos": "(milhas * milheiro) + taxa + (bagagens * bagagem_unitaria)",
    "azul_pontos_dinheiro": "(milhas * milheiro) + (valor_dinheiro * (1 - desconto_taxa / 100)) + taxas_impostos + (taxa_resgate_por_pax_trecho * passageiros * numero_trechos) + (bagagens * bagagem_unitaria)",
    "american_milhas": "(milhas * milheiro) + taxa + (bagagens * bagagem_unitaria)",
    "azulpelomundo_pontos": "(milhas * milheiro) + taxa + (bagagens * bagagem_unitaria)",
    "azulpelomundo_pontos_dinheiro": "(milhas * milheiro) + (valor_dinheiro * (1 - desconto_taxa / 100)) + taxas_impostos + (taxa_resgate_por_pax_trecho * passageiros * numero_trechos) + (bagagens * bagagem_unitaria)",
}

def _editable_formula(calc_type: CalculationType) -> str:
    return _LEGACY_EDIT_FORMULAS.get(str(calc_type.legacy_key or ""), str(calc_type.formula or ""))



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
    # As companhias originais também podem ter logo e lógica ajustadas para
    # futuras melhorias. A exclusão da companhia original continua bloqueada.
    if airline.builtin:
        return bool(getattr(user, "is_owner", False) or getattr(user, "role", "") in {"admin", "gerente"})
    if user.company_id:
        return airline.owner_company_id == user.company_id and user.role in {"admin", "gerente"}
    return airline.owner_user_id == user.id


def _market_scope(value: object) -> str:
    raw = str(value or "").strip().lower()
    return raw if raw in {"national", "international", "both"} else "both"


def _airline_partner_names(airline: Airline | None) -> list[str]:
    if airline is None:
        return []
    try:
        raw = json.loads(str(getattr(airline, "partner_airlines_json", "[]") or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        raw = []
    if not isinstance(raw, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in raw:
        name = " ".join(str(item or "").split()).strip()[:180]
        key = name.casefold()
        if name and key not in seen:
            seen.add(key)
            result.append(name)
    return result[:100]


def _clean_partner_names(values: list[object], extra_text: object = "") -> list[str]:
    raw_items = list(values or [])
    extra = str(extra_text or "").replace(";", "\n").replace(",", "\n")
    raw_items.extend(extra.splitlines())
    result: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        name = " ".join(str(item or "").split()).strip()[:180]
        key = name.casefold()
        if len(name) < 2 or key in seen:
            continue
        seen.add(key)
        result.append(name)
        if len(result) >= 100:
            break
    return result


def _available_partner_airlines(db: Session, user, *, exclude_id: int | None = None) -> list[Airline]:
    items = list(
        db.scalars(
            select(Airline)
            .where(Airline.active.is_(True), _visibility(user))
            .order_by(Airline.name)
        ).all()
    )
    if exclude_id is not None:
        items = [item for item in items if item.id != exclude_id]
    return items


async def _save_logo(upload: UploadFile | None, *, prefix: str = "airline") -> str | None:
    return await save_upload_image(
        upload,
        AIRLINE_UPLOAD_DIR,
        max_bytes=4 * 1024 * 1024,
        allowed_extensions=AIRLINE_IMAGE_EXTENSIONS,
        filename_prefix=prefix,
    )


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
    return templates.TemplateResponse(request, "airlines/list.html", context(request, user=user, airlines=airlines, manageable_airline_ids={item.id for item in airlines if _can_manage(user, item)}))


@router.get("/new")
def new_airline_page(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if user.company_id and user.role not in {"admin", "gerente"}:
        flash(request, "Somente administradores e gerentes podem criar companhias para a empresa.", "error")
        return RedirectResponse("/airlines", status_code=303)
    partner_airlines = _available_partner_airlines(db, user)
    return templates.TemplateResponse(
        request,
        "airlines/form.html",
        context(request, user=user, partner_airlines=partner_airlines),
    )


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
    formula = str(form.get("formula") or "tarifa - (tarifa * desconto_percentual / 100)").strip()
    apply_mode = str(form.get("apply_mode") or "total")
    color = str(form.get("color") or "#24b7d3")
    market_scope = _market_scope(form.get("market_scope"))
    partner_names = _clean_partner_names(
        list(form.getlist("partner_airlines")),
        form.get("partner_airlines_extra"),
    )
    if len(name) < 2:
        flash(request, "O nome da companhia é obrigatório.", "error")
        return RedirectResponse("/airlines/new", status_code=303)

    try:
        fields = _parse_fields(str(form.get("fields_json") or "[]"))
    except ValueError as exc:
        flash(request, str(exc), "error")
        return RedirectResponse("/airlines/new", status_code=303)

    # Modelo padrão das companhias personalizadas: tarifa menos X% de desconto.
    if not fields:
        fields = [
            {"key": "tarifa", "label": "Tarifa informada", "field_type": "number", "default_value": "0", "required": True, "min_value": 0, "max_value": None, "step": 0.01, "help_text": "Valor bruto da tarifa antes do desconto.", "options": None, "order_index": 0},
            {"key": "desconto_percentual", "label": "Desconto da tarifa (%)", "field_type": "percent", "default_value": "0", "required": False, "min_value": 0, "max_value": 100, "step": 0.01, "help_text": "Percentual retirado diretamente da tarifa informada.", "options": None, "order_index": 1},
        ]

    allowed_variables = {item["key"] for item in fields} | {"passageiros", "bebes", "bagagens"}
    valid, message = validate_formula(formula, allowed_variables)
    if not valid:
        flash(request, f"Fórmula inválida: {message}", "error")
        return RedirectResponse("/airlines/new", status_code=303)

    upload = form.get("logo")
    try:
        logo_path = await _save_logo(upload if getattr(upload, "filename", None) else None)
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
        market_scope=market_scope,
        partner_airlines_json=json.dumps(partner_names, ensure_ascii=False),
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
    partner_airlines = _available_partner_airlines(db, user, exclude_id=airline.id)
    selected_partner_names = _airline_partner_names(airline)
    available_partner_tokens = {item.name.casefold() for item in partner_airlines}
    manual_partner_names = [
        name for name in selected_partner_names
        if name.casefold() not in available_partner_tokens
    ]
    return templates.TemplateResponse(
        request,
        "airlines/manage.html",
        context(
            request,
            user=user,
            airline=airline,
            can_manage=_can_manage(user, airline),
            partner_airlines=partner_airlines,
            selected_partner_names=selected_partner_names,
            manual_partner_names=manual_partner_names,
        ),
    )


@router.post("/{airline_id}/profile")
async def update_airline_profile(airline_id: int, request: Request, db: Session = Depends(get_db)):
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

    airline.market_scope = _market_scope(form.get("market_scope"))
    partner_names = _clean_partner_names(
        list(form.getlist("partner_airlines")),
        form.get("partner_airlines_extra"),
    )
    # Nunca deixa a própria companhia cadastrada como parceira dela mesma.
    partner_names = [name for name in partner_names if name.casefold() != str(airline.name or "").casefold()]
    airline.partner_airlines_json = json.dumps(partner_names, ensure_ascii=False)
    db.commit()

    scope_label = {
        "national": "Nacional",
        "international": "Internacional",
        "both": "Nacional + internacional",
    }.get(airline.market_scope, "Nacional + internacional")
    flash(
        request,
        f"Perfil atualizado: {scope_label} • {len(partner_names)} parceria(s) habitual(is).",
        "success",
    )
    return RedirectResponse(f"/airlines/{airline_id}", status_code=303)


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
        logo_path = await _save_logo(upload if getattr(upload, "filename", None) else None, prefix=f"airline-{airline.id}")
    except ValueError as exc:
        flash(request, str(exc), "error")
        return RedirectResponse(f"/airlines/{airline_id}", status_code=303)
    if not logo_path:
        flash(request, "Selecione uma imagem.", "error")
        return RedirectResponse(f"/airlines/{airline_id}", status_code=303)

    old_path = airline.logo_path
    airline.logo_path = logo_path
    db.commit()
    delete_relative_upload(old_path)
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
    delete_relative_upload(old_path)
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

def _field_to_payload(field: CalculationField) -> dict:
    options = None
    if field.options_json:
        try:
            parsed = json.loads(field.options_json)
            if isinstance(parsed, list):
                options = parsed
        except Exception:
            options = None
    return {
        "key": field.key,
        "label": field.label,
        "field_type": field.field_type,
        "default_value": field.default_value or "0",
        "required": bool(field.required),
        "min_value": field.min_value,
        "max_value": field.max_value,
        "step": field.step,
        "help_text": field.help_text or "",
        "options": options,
    }



@router.get("/{airline_id}/edit")
def edit_custom_airline_redirect(airline_id: int, request: Request, db: Session = Depends(get_db)):
    """Compatibilidade: abre diretamente a primeira lógica editável da companhia."""
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
    if not _can_manage(user, airline):
        flash(request, "Você não pode editar essa companhia.", "error")
        return RedirectResponse(f"/airlines/{airline_id}", status_code=303)

    calc_type = next(
        (item for item in airline.calculation_types if item.active),
        None,
    )
    if calc_type is None:
        flash(request, "Essa companhia ainda não possui uma lógica ativa editável.", "error")
        return RedirectResponse(f"/airlines/{airline_id}", status_code=303)

    return RedirectResponse(
        f"/airlines/{airline_id}/types/{calc_type.id}/edit",
        status_code=303,
    )


@router.get("/{airline_id}/delete")
def delete_custom_airline_page(airline_id: int, request: Request, db: Session = Depends(get_db)):
    """Página de confirmação para links antigos que abrem /delete por GET."""
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)

    airline = db.scalar(
        select(Airline)
        .where(Airline.id == airline_id, _visibility(user))
        .options(selectinload(Airline.calculation_types))
    )
    if airline is None:
        flash(request, "Companhia não encontrada.", "error")
        return RedirectResponse("/airlines", status_code=303)
    if not _can_manage(user, airline) or airline.builtin:
        flash(request, "As companhias originais podem ser editadas, mas não excluídas.", "error")
        return RedirectResponse(f"/airlines/{airline_id}", status_code=303)

    return templates.TemplateResponse(
        request,
        "airlines/delete_confirm.html",
        context(request, user=user, airline=airline),
    )


@router.get("/{airline_id}/types/{type_id}/edit")
def edit_calculation_type_page(airline_id: int, type_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)

    airline = db.scalar(
        select(Airline)
        .where(Airline.id == airline_id, _visibility(user))
        .options(selectinload(Airline.calculation_types).selectinload(CalculationType.fields))
    )
    if airline is None or not _can_manage(user, airline):
        flash(request, "Você não pode alterar essa companhia.", "error")
        return RedirectResponse("/airlines", status_code=303)

    calc_type = next((item for item in airline.calculation_types if item.id == type_id and item.active), None)
    if calc_type is None:
        flash(request, "Essa lógica não foi encontrada.", "error")
        return RedirectResponse(f"/airlines/{airline_id}", status_code=303)

    initial_fields = [_field_to_payload(field) for field in calc_type.fields]
    return templates.TemplateResponse(
        request,
        "airlines/type_edit.html",
        context(
            request,
            user=user,
            airline=airline,
            calc_type=calc_type,
            initial_fields=initial_fields,
            formula_value=_editable_formula(calc_type),
            converting_legacy=bool(calc_type.legacy_key),
        ),
    )


@router.post("/{airline_id}/types/{type_id}/edit")
async def update_calculation_type(airline_id: int, type_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)

    airline = db.scalar(
        select(Airline)
        .where(Airline.id == airline_id, _visibility(user))
        .options(selectinload(Airline.calculation_types).selectinload(CalculationType.fields))
    )
    if airline is None or not _can_manage(user, airline):
        flash(request, "Você não pode alterar essa companhia.", "error")
        return RedirectResponse("/airlines", status_code=303)

    calc_type = next((item for item in airline.calculation_types if item.id == type_id and item.active), None)
    if calc_type is None:
        flash(request, "Essa lógica não foi encontrada.", "error")
        return RedirectResponse(f"/airlines/{airline_id}", status_code=303)

    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada. Tente novamente.", "error")
        return RedirectResponse(f"/airlines/{airline_id}/types/{type_id}/edit", status_code=303)

    name = str(form.get("calculation_name") or "").strip()
    formula = str(form.get("formula") or "").strip()
    apply_mode = str(form.get("apply_mode") or "total")
    description = str(form.get("description") or "").strip() or None

    try:
        fields = _parse_fields(str(form.get("fields_json") or "[]"))
    except ValueError as exc:
        flash(request, str(exc), "error")
        return RedirectResponse(f"/airlines/{airline_id}/types/{type_id}/edit", status_code=303)

    if not name or not formula or not fields:
        flash(request, "Informe o nome, a fórmula e ao menos um campo.", "error")
        return RedirectResponse(f"/airlines/{airline_id}/types/{type_id}/edit", status_code=303)

    allowed_variables = {item["key"] for item in fields} | {"passageiros", "bebes", "bagagens"}
    if airline.slug == "american":
        allowed_variables.add("bagagem_unitaria")
    valid, message = validate_formula(formula, allowed_variables)
    if not valid:
        flash(request, f"Fórmula inválida: {message}", "error")
        return RedirectResponse(f"/airlines/{airline_id}/types/{type_id}/edit", status_code=303)

    # Ao salvar pela primeira vez uma regra original, ela passa a usar a
    # fórmula editável mantendo o MESMO id. Assim o histórico não é recalculado.
    if calc_type.legacy_key:
        calc_type.legacy_key = None
    calc_type.name = name
    calc_type.description = description
    calc_type.formula = formula
    calc_type.apply_mode = "per_passenger" if apply_mode == "per_passenger" else "total"

    for old_field in list(calc_type.fields):
        db.delete(old_field)
    db.flush()
    _add_fields(db, calc_type, fields)
    db.commit()

    flash(request, "Lógica de cálculo atualizada com sucesso.", "success")
    return RedirectResponse(f"/airlines/{airline_id}", status_code=303)



@router.post("/{airline_id}/types/{type_id}/delete")
async def delete_calculation_type(
    airline_id: int,
    type_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Exclusão segura de uma lógica personalizada, preservando o histórico."""
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)

    airline = db.scalar(
        select(Airline)
        .where(Airline.id == airline_id, _visibility(user))
        .options(selectinload(Airline.calculation_types).selectinload(CalculationType.fields))
    )
    if airline is None or not _can_manage(user, airline):
        flash(request, "Você não pode excluir lógicas dessa companhia.", "error")
        return RedirectResponse("/airlines", status_code=303)

    calc_type = next(
        (item for item in airline.calculation_types if item.id == type_id and item.active),
        None,
    )
    if calc_type is None:
        flash(request, "Lógica de cálculo não encontrada ou já excluída.", "error")
        return RedirectResponse(f"/airlines/{airline_id}", status_code=303)

    if airline.builtin or calc_type.legacy_key:
        flash(request, "As lógicas das companhias originais podem ser editadas, mas não excluídas.", "error")
        return RedirectResponse(f"/airlines/{airline_id}", status_code=303)

    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada. Tente novamente.", "error")
        return RedirectResponse(f"/airlines/{airline_id}", status_code=303)

    was_default = bool(calc_type.is_default)

    # Não apaga o registro nem os campos fisicamente.
    # Assim cotações antigas continuam apontando para a mesma lógica.
    calc_type.active = False
    calc_type.is_default = False

    # Se era a lógica padrão, promove outra lógica personalizada ativa.
    if was_default:
        replacement = next(
            (
                item
                for item in airline.calculation_types
                if item.id != calc_type.id and item.active and not item.legacy_key
            ),
            None,
        )
        if replacement is not None:
            replacement.is_default = True

    db.commit()

    remaining = [
        item
        for item in airline.calculation_types
        if item.id != calc_type.id and item.active
    ]
    if remaining:
        flash(
            request,
            f"Lógica '{calc_type.name}' excluída. O histórico foi preservado.",
            "success",
        )
    else:
        flash(
            request,
            f"Lógica '{calc_type.name}' excluída. A companhia ficou sem lógica ativa; "
            "crie uma nova lógica antes de calcular novamente.",
            "success",
        )
    return RedirectResponse(f"/airlines/{airline_id}", status_code=303)


@router.post("/{airline_id}/delete")
async def delete_custom_airline(airline_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)

    airline = db.scalar(
        select(Airline)
        .where(Airline.id == airline_id, _visibility(user))
        .options(selectinload(Airline.calculation_types))
    )
    if airline is None or not _can_manage(user, airline) or airline.builtin:
        flash(request, "As companhias originais podem ser editadas, mas não excluídas.", "error")
        return RedirectResponse("/airlines", status_code=303)

    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse(f"/airlines/{airline_id}", status_code=303)

    # Exclusão segura: a companhia some das telas e novos cálculos,
    # mas os vínculos históricos continuam intactos.
    airline.active = False
    for calc_type in airline.calculation_types:
        calc_type.active = False
    db.commit()

    flash(request, f"Companhia '{airline.name}' excluída. O histórico foi preservado.", "success")
    return RedirectResponse("/airlines", status_code=303)

