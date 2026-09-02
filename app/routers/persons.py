from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, UploadFile, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy import delete, desc, func, or_, select, update
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..dependencies import require_user
from ..models import Person, PersonAttachment, PersonFamily, QuoteGroupTripDetail, QuoteTripDetail, WebUser
from ..security import validate_csrf_token
from ..services.uploads import save_upload_image, delete_relative_upload
from ..web import context, flash, templates

router = APIRouter(prefix="/persons", tags=["persons"])

# ===== CONSTANTES =====
PERSON_TYPES = ["passageiro", "cliente", "fornecedor", "representante"]

MARITAL_STATUS = ["Solteiro(a)", "Casado(a)", "Divorciado(a)", "Viúvo(a)", "União Estável", "Separado(a)"]

NATIONALITIES = ["Brasileira", "Americana", "Portuguesa", "Espanhola", "Francesa", "Italiana", "Alemã", "Inglesa", "Japonesa", "Chinesa", "Argentina", "Uruguaia", "Paraguaia", "Boliviana", "Peruana", "Chilena", "Venezuelana", "Colombiana", "Equatoriana", "Canadense", "Mexicana", "Outra"]

PROFESSIONS = ["Médico(a)", "Advogado(a)", "Engenheiro(a)", "Arquiteto(a)", "Professor(a)", "Empresário(a)", "Autônomo(a)", "Funcionário Público", "Aposentado(a)", "Estudante", "Desenvolvedor(a)", "Designer", "Consultor(a)", "Vendedor(a)", "Administrador(a)", "Contador(a)", "Enfermeiro(a)", "Dentista", "Psicólogo(a)", "Farmacêutico(a)", "Jornalista", "Publicitário(a)", "Músico", "Artista", "Atleta", "Outro"]

SALES_CHANNELS = ["Online", "Loja Física", "Telemarketing", "WhatsApp", "E-mail", "Parceiro", "Indicação", "Evento", "Redes Sociais", "Outro"]

COUNTRIES = ["Brasil", "Estados Unidos", "Portugal", "Espanha", "França", "Itália", "Alemanha", "Inglaterra", "Japão", "China", "Argentina", "Uruguai", "Paraguai", "Bolívia", "Peru", "Chile", "Venezuela", "Colômbia", "Equador", "Canadá", "México", "Outro"]

GENDER_OPTIONS = ["Masculino", "Feminino", "Outro", "Prefiro não informar"]


# ===== FUNÇÕES AUXILIARES =====

def _visibility_filter(user):
    """Filtro de visibilidade: empresa ou usuário individual"""
    if user.company_id:
        return Person.company_id == user.company_id
    return Person.user_id == user.id


def _can_manage(user, person: Person) -> bool:
    """Verifica se o usuário pode gerenciar esta pessoa"""
    if user.company_id:
        return person.company_id == user.company_id
    return person.user_id == user.id


def _person_context(user, person: Person | None = None) -> dict:
    """Contexto para templates de pessoa"""
    return {
        "person": person,
        "person_types": PERSON_TYPES,
        "marital_status": MARITAL_STATUS,
        "nationalities": NATIONALITIES,
        "professions": PROFESSIONS,
        "gender_options": GENDER_OPTIONS,
        "countries": COUNTRIES,
        "sales_channels": SALES_CHANNELS,
    }


# ===== ROTAS =====

@router.get("")
@router.get("/")
def person_list(request: Request, q: str = "", db: Session = Depends(get_db)):
    """Lista de pessoas cadastradas"""
    user = require_user(request, db)
    
    statement = select(Person).where(_visibility_filter(user), Person.active.is_(True))
    if q.strip():
        pattern = f"%{q.strip()}%"
        statement = statement.where(
            or_(
                Person.name.ilike(pattern),
                Person.cpf_cnpj.ilike(pattern),
                Person.rg.ilike(pattern),
                Person.email.ilike(pattern),
                Person.phone.ilike(pattern),
                Person.mobile.ilike(pattern),
            )
        )
    
    persons = db.scalars(
        statement.order_by(desc(Person.is_complete), desc(Person.created_at))
        .limit(500)
    ).all()
    
    pending = [p for p in persons if not p.is_complete]
    complete = [p for p in persons if p.is_complete]
    
    return templates.TemplateResponse(
        request,
        "persons/list.html",
        context(request, user=user, pending=pending, complete=complete, search_query=q)
    )


@router.get("/pending")
def pending_persons(request: Request, db: Session = Depends(get_db)):
    """Lista de cadastros pendentes (para o dashboard)"""
    user = require_user(request, db)
    
    pending = db.scalars(
        select(Person)
        .where(_visibility_filter(user), Person.is_complete.is_(False))
        .order_by(desc(Person.created_at))
        .limit(50)
    ).all()
    
    return JSONResponse({
        "count": len(pending),
        "persons": [
            {
                "id": p.id,
                "name": p.name,
                "cpf_cnpj": p.cpf_cnpj,
                "phone": p.phone,
                "person_type": p.person_type,
                "created_at": p.created_at.isoformat()
            }
            for p in pending
        ]
    })


@router.get("/new")
def new_person(request: Request, quick: bool = False, person_type: str = "", db: Session = Depends(get_db)):
    """Formulário de nova pessoa (rápido ou completo)."""
    user = require_user(request, db)
    default_person_type = person_type.strip().lower() if person_type.strip().lower() in PERSON_TYPES else ""
    return templates.TemplateResponse(
        request,
        "persons/form.html",
        context(
            request,
            user=user,
            **_person_context(user),
            quick_mode=quick,
            default_person_type=default_person_type,
            family=[],
            attachments=[],
        ),
    )


@router.post("/new")
async def create_person(request: Request, db: Session = Depends(get_db)):
    """Criar nova pessoa (rápido ou completo)"""
    user = require_user(request, db)
    
    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/persons/new", status_code=303)
    
    name = str(form.get("name") or "").strip()
    if len(name) < 2:
        flash(request, "Informe o nome da pessoa.", "error")
        return RedirectResponse("/persons/new", status_code=303)
    
    quick_mode = str(form.get("quick_mode") or "false").lower() == "true"
    
    cpf_cnpj = str(form.get("cpf_cnpj") or "").strip() or None
    birth_date = str(form.get("birth_date") or "").strip() or None
    person_type = str(form.get("person_type") or "passageiro").strip()
    
    # Verifica duplicidade de CPF
    if cpf_cnpj:
        existing = db.scalar(select(Person).where(Person.cpf_cnpj == cpf_cnpj))
        if existing:
            flash(request, "Já existe uma pessoa cadastrada com este CPF/CNPJ.", "error")
            return RedirectResponse("/persons/new", status_code=303)
    
    person = Person(
        company_id=user.company_id,
        user_id=None if user.company_id else user.id,
        name=name,
        cpf_cnpj=cpf_cnpj,
        birth_date=birth_date,
        person_type=person_type if person_type in PERSON_TYPES else "passageiro",
        is_complete=bool(cpf_cnpj and birth_date),
        active=True,
    )
    
    if quick_mode:
        person.is_complete = False
    
    db.add(person)
    db.flush()
    
    # Se não for rápido, preenche os demais campos
    if not quick_mode:
        person.phone = str(form.get("phone") or "").strip() or None
        person.mobile = str(form.get("mobile") or "").strip() or None
        person.email = str(form.get("email") or "").strip()[:180] or None
        person.website = str(form.get("website") or "").strip()[:200] or None
        person.pix_key = str(form.get("pix_key") or "").strip()[:100] or None
        person.accepts_communication = form.get("accepts_communication") == "on"
        
        person.rg = str(form.get("rg") or "").strip() or None
        person.foreign_id = str(form.get("foreign_id") or "").strip() or None
        person.passport = str(form.get("passport") or "").strip() or None
        person.passport_issue_date = str(form.get("passport_issue_date") or "").strip() or None
        person.passport_expiry_date = str(form.get("passport_expiry_date") or "").strip() or None
        person.passport_nationality = str(form.get("passport_nationality") or "").strip() or None
        person.visa = str(form.get("visa") or "").strip() or None
        person.visa_expiry_date = str(form.get("visa_expiry_date") or "").strip() or None
        person.issuing_agency = str(form.get("issuing_agency") or "").strip() or None
        person.nationality = str(form.get("nationality") or "").strip() or None
        person.marital_status = str(form.get("marital_status") or "").strip() or None
        
        person.gender = str(form.get("gender") or "").strip() or None
        person.profession = str(form.get("profession") or "").strip() or None
        person.sales_channel = str(form.get("sales_channel") or "").strip() or None
        person.emergency_contact_name = str(form.get("emergency_contact_name") or "").strip() or None
        person.emergency_contact_phone = str(form.get("emergency_contact_phone") or "").strip() or None
        try:
            person.income = float(form.get("income") or 0)
        except ValueError:
            person.income = 0.0
        
        person.country = str(form.get("country") or "").strip() or None
        person.postal_code = str(form.get("postal_code") or "").strip() or None
        person.state = str(form.get("state") or "").strip() or None
        person.city = str(form.get("city") or "").strip() or None
        person.neighborhood = str(form.get("neighborhood") or "").strip() or None
        person.street = str(form.get("street") or "").strip() or None
        person.number = str(form.get("number") or "").strip() or None
        person.complement = str(form.get("complement") or "").strip() or None
        
        person.notes = str(form.get("notes") or "").strip() or None
    
    db.commit()
    
    flash(request, f"{person.name} cadastrado(a) com sucesso!", "success")
    
    if form.get("save_and_new"):
        return RedirectResponse("/persons/new", status_code=303)
    if form.get("save_and_close") or quick_mode or not person.is_complete:
        return RedirectResponse(f"/persons/{person.id}", status_code=303)
    return RedirectResponse("/persons", status_code=303)



# ===== API para autocomplete =====
@router.get("/search")
def search_persons(
    request: Request,
    q: str = "",
    person_type: str = "",
    limit: int = 20,
    db: Session = Depends(get_db)
):
    """Busca por nome/documento/contato para campos com autocomplete.

    Sem texto, retorna os cadastros mais recentes para que alguns nomes já
    apareçam ao abrir o campo. ``person_type`` aceita um ou vários tipos
    separados por vírgula.
    """
    user = require_user(request, db)
    safe_limit = min(max(int(limit or 20), 5), 50)
    query = str(q or "").strip()
    statement = select(Person).where(_visibility_filter(user), Person.active.is_(True))

    requested_types = [item.strip().lower() for item in str(person_type or "").split(",") if item.strip().lower() in PERSON_TYPES]
    if requested_types:
        statement = statement.where(Person.person_type.in_(requested_types))

    if query:
        pattern = f"%{query}%"
        statement = statement.where(
            or_(
                Person.name.ilike(pattern),
                Person.cpf_cnpj.ilike(pattern),
                Person.rg.ilike(pattern),
                Person.email.ilike(pattern),
                Person.phone.ilike(pattern),
                Person.mobile.ilike(pattern),
            )
        )
        order_by = (Person.is_complete.desc(), Person.name)
    else:
        order_by = (desc(Person.updated_at), Person.name)

    results = db.scalars(statement.order_by(*order_by).limit(safe_limit)).all()

    return JSONResponse({
        "results": [
            {
                "id": p.id,
                "name": p.name,
                "cpf_cnpj": p.cpf_cnpj,
                "rg": p.rg,
                "birth_date": p.birth_date,
                "phone": p.phone or p.mobile,
                "mobile": p.mobile,
                "email": p.email,
                "passport": p.passport,
                "person_type": p.person_type,
                "is_complete": p.is_complete,
                "display": f"{p.name} ({p.cpf_cnpj or p.rg or 'sem documento'})"
            }
            for p in results
        ]
    })


@router.get("/{person_id}/edit")
def edit_person(person_id: int, request: Request, db: Session = Depends(get_db)):
    """Formulário para completar/editar cadastro de pessoa."""
    user = require_user(request, db)
    person = db.scalar(
        select(Person)
        .where(Person.id == person_id, _visibility_filter(user))
    )
    if person is None:
        flash(request, "Pessoa não encontrada.", "error")
        return RedirectResponse("/persons", status_code=303)

    family = db.scalars(
        select(PersonFamily)
        .where(PersonFamily.person_id == person_id)
        .options(selectinload(PersonFamily.relative))
    ).all()

    attachments = db.scalars(
        select(PersonAttachment)
        .where(PersonAttachment.person_id == person_id)
        .order_by(desc(PersonAttachment.created_at))
    ).all()

    return templates.TemplateResponse(
        request,
        "persons/form.html",
        context(request, user=user, **_person_context(user, person), quick_mode=False, family=family, attachments=attachments)
    )


@router.get("/{person_id}")
def person_detail(person_id: int, request: Request, db: Session = Depends(get_db)):
    """Detalhe da pessoa (completo)"""
    user = require_user(request, db)
    
    person = db.scalar(
        select(Person)
        .where(Person.id == person_id, _visibility_filter(user))
    )
    
    if person is None:
        flash(request, "Pessoa não encontrada.", "error")
        return RedirectResponse("/persons", status_code=303)
    
    family = db.scalars(
        select(PersonFamily)
        .where(PersonFamily.person_id == person_id)
        .options(selectinload(PersonFamily.relative))
    ).all()
    
    attachments = db.scalars(
        select(PersonAttachment)
        .where(PersonAttachment.person_id == person_id)
        .order_by(desc(PersonAttachment.created_at))
    ).all()
    
    return templates.TemplateResponse(
        request,
        "persons/detail.html",
        context(request, user=user, **_person_context(user, person), family=family, attachments=attachments)
    )


@router.post("/{person_id}")
async def update_person(person_id: int, request: Request, db: Session = Depends(get_db)):
    """Atualizar pessoa"""
    user = require_user(request, db)
    
    person = db.get(Person, person_id)
    if person is None or not _can_manage(user, person):
        flash(request, "Pessoa não encontrada.", "error")
        return RedirectResponse("/persons", status_code=303)
    
    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse(f"/persons/{person_id}", status_code=303)
    
    name = str(form.get("name") or "").strip()
    if len(name) < 2:
        flash(request, "Informe o nome da pessoa.", "error")
        return RedirectResponse(f"/persons/{person_id}", status_code=303)
    
    new_cpf_cnpj = str(form.get("cpf_cnpj") or "").strip() or None
    if new_cpf_cnpj:
        existing = db.scalar(select(Person).where(Person.cpf_cnpj == new_cpf_cnpj, Person.id != person.id))
        if existing:
            flash(request, "Já existe outra pessoa cadastrada com este CPF/CNPJ.", "error")
            return RedirectResponse(f"/persons/{person_id}/edit", status_code=303)

    person.name = name
    person.cpf_cnpj = new_cpf_cnpj
    person.birth_date = str(form.get("birth_date") or "").strip() or None
    person.person_type = str(form.get("person_type") or "passageiro").strip()
    person.active = form.get("active") == "on"
    
    person.phone = str(form.get("phone") or "").strip() or None
    person.mobile = str(form.get("mobile") or "").strip() or None
    person.email = str(form.get("email") or "").strip()[:180] or None
    person.website = str(form.get("website") or "").strip()[:200] or None
    person.pix_key = str(form.get("pix_key") or "").strip()[:100] or None
    person.accepts_communication = form.get("accepts_communication") == "on"
    
    person.rg = str(form.get("rg") or "").strip() or None
    person.foreign_id = str(form.get("foreign_id") or "").strip() or None
    person.passport = str(form.get("passport") or "").strip() or None
    person.passport_issue_date = str(form.get("passport_issue_date") or "").strip() or None
    person.passport_expiry_date = str(form.get("passport_expiry_date") or "").strip() or None
    person.passport_nationality = str(form.get("passport_nationality") or "").strip() or None
    person.visa = str(form.get("visa") or "").strip() or None
    person.visa_expiry_date = str(form.get("visa_expiry_date") or "").strip() or None
    person.issuing_agency = str(form.get("issuing_agency") or "").strip() or None
    person.nationality = str(form.get("nationality") or "").strip() or None
    person.marital_status = str(form.get("marital_status") or "").strip() or None
    
    person.gender = str(form.get("gender") or "").strip() or None
    person.profession = str(form.get("profession") or "").strip() or None
    person.sales_channel = str(form.get("sales_channel") or "").strip() or None
    person.emergency_contact_name = str(form.get("emergency_contact_name") or "").strip() or None
    person.emergency_contact_phone = str(form.get("emergency_contact_phone") or "").strip() or None
    try:
        person.income = float(form.get("income") or 0)
    except ValueError:
        person.income = 0.0
    
    person.country = str(form.get("country") or "").strip() or None
    person.postal_code = str(form.get("postal_code") or "").strip() or None
    person.state = str(form.get("state") or "").strip() or None
    person.city = str(form.get("city") or "").strip() or None
    person.neighborhood = str(form.get("neighborhood") or "").strip() or None
    person.street = str(form.get("street") or "").strip() or None
    person.number = str(form.get("number") or "").strip() or None
    person.complement = str(form.get("complement") or "").strip() or None
    
    person.notes = str(form.get("notes") or "").strip() or None
    
    person.is_complete = bool(person.cpf_cnpj and person.birth_date)
    person.updated_at = datetime.utcnow()
    
    db.commit()
    
    flash(request, f"{person.name} atualizado(a) com sucesso!", "success")
    
    if form.get("save_and_close"):
        return RedirectResponse(f"/persons/{person_id}", status_code=303)
    if form.get("save_and_new"):
        return RedirectResponse("/persons/new", status_code=303)
    return RedirectResponse(f"/persons/{person_id}", status_code=303)


@router.post("/{person_id}/delete")
async def delete_person(person_id: int, request: Request, db: Session = Depends(get_db)):
    """Excluir pessoa"""
    user = require_user(request, db)
    
    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse("/persons", status_code=303)
    
    person = db.get(Person, person_id)
    if person is None or not _can_manage(user, person):
        flash(request, "Pessoa não encontrada.", "error")
        return RedirectResponse("/persons", status_code=303)
    
    name = person.name
    attachment_paths = db.scalars(
        select(PersonAttachment.file_path).where(PersonAttachment.person_id == person.id)
    ).all()

    # Remove referências antes do cadastro para funcionar tanto em SQLite
    # quanto no PostgreSQL/Render, inclusive em bancos antigos sem cascata.
    db.execute(delete(PersonFamily).where(or_(PersonFamily.person_id == person.id, PersonFamily.relative_id == person.id)))
    db.execute(update(QuoteGroupTripDetail).where(QuoteGroupTripDetail.client_person_id == person.id).values(client_person_id=None))
    db.execute(update(QuoteTripDetail).where(QuoteTripDetail.client_person_id == person.id).values(client_person_id=None))
    db.execute(delete(PersonAttachment).where(PersonAttachment.person_id == person.id))
    db.execute(delete(Person).where(Person.id == person.id))
    db.commit()
    for path in attachment_paths:
        delete_relative_upload(path)

    flash(request, f"{name} excluído(a) definitivamente.", "success")
    return RedirectResponse("/persons", status_code=303)


@router.post("/{person_id}/family")
async def add_family_member(
    person_id: int,
    request: Request,
    relative_id: int = Form(...),
    relationship: str = Form(...),
    db: Session = Depends(get_db)
):
    """Adicionar membro da família"""
    user = require_user(request, db)
    
    person = db.get(Person, person_id)
    if person is None or not _can_manage(user, person):
        flash(request, "Pessoa não encontrada.", "error")
        return RedirectResponse(f"/persons/{person_id}", status_code=303)
    
    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse(f"/persons/{person_id}", status_code=303)
    
    relative = db.get(Person, relative_id)
    if relative is None or not _can_manage(user, relative):
        flash(request, "Familiar não encontrado.", "error")
        return RedirectResponse(f"/persons/{person_id}", status_code=303)
    
    if relative_id == person_id:
        flash(request, "Não é possível adicionar a própria pessoa.", "error")
        return RedirectResponse(f"/persons/{person_id}", status_code=303)
    
    existing = db.scalar(
        select(PersonFamily)
        .where(PersonFamily.person_id == person_id, PersonFamily.relative_id == relative_id)
    )
    if existing:
        flash(request, "Este familiar já está vinculado.", "error")
        return RedirectResponse(f"/persons/{person_id}", status_code=303)
    
    family = PersonFamily(
        person_id=person_id,
        relative_id=relative_id,
        relationship=relationship
    )
    db.add(family)
    db.commit()
    
    flash(request, f"{relative.name} adicionado(a) como {relationship}.", "success")
    return RedirectResponse(f"/persons/{person_id}", status_code=303)


@router.post("/{person_id}/family/{family_id}/delete")
async def remove_family_member(
    person_id: int,
    family_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Remover membro da família"""
    user = require_user(request, db)
    
    family = db.scalar(
        select(PersonFamily)
        .where(PersonFamily.id == family_id, PersonFamily.person_id == person_id)
    )
    
    if family is None:
        flash(request, "Vínculo familiar não encontrado.", "error")
        return RedirectResponse(f"/persons/{person_id}", status_code=303)
    
    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse(f"/persons/{person_id}", status_code=303)
    
    db.delete(family)
    db.commit()
    
    flash(request, "Membro da família removido.", "success")
    return RedirectResponse(f"/persons/{person_id}", status_code=303)


@router.post("/{person_id}/attachment")
async def add_attachment(
    person_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Adicionar anexo"""
    user = require_user(request, db)
    
    person = db.get(Person, person_id)
    if person is None or not _can_manage(user, person):
        flash(request, "Pessoa não encontrada.", "error")
        return RedirectResponse(f"/persons/{person_id}", status_code=303)
    
    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse(f"/persons/{person_id}", status_code=303)
    
    upload = form.get("file")
    if not upload or not upload.filename:
        flash(request, "Selecione um arquivo.", "error")
        return RedirectResponse(f"/persons/{person_id}", status_code=303)
    
    from ..config import UPLOAD_DIR
    person_upload_dir = UPLOAD_DIR / "persons"
    person_upload_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        file_path = await save_upload_image(
            upload,
            person_upload_dir,
            max_bytes=10 * 1024 * 1024,
            allowed_extensions={".png", ".jpg", ".jpeg", ".webp", ".pdf", ".doc", ".docx", ".xls", ".xlsx"},
            filename_prefix=f"person-{person.id}"
        )
    except ValueError as exc:
        flash(request, str(exc), "error")
        return RedirectResponse(f"/persons/{person_id}", status_code=303)
    
    if file_path:
        attachment = PersonAttachment(
            person_id=person.id,
            file_path=file_path,
            file_name=upload.filename[:200],
            file_type=Path(upload.filename).suffix.lower().lstrip(".") or None,
            description=str(form.get("description") or "").strip() or None
        )
        db.add(attachment)
        db.commit()
        flash(request, "Anexo adicionado com sucesso.", "success")
    
    return RedirectResponse(f"/persons/{person_id}", status_code=303)


@router.post("/attachment/{attachment_id}/delete")
async def delete_attachment(
    attachment_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Remover anexo"""
    user = require_user(request, db)
    
    attachment = db.scalar(
        select(PersonAttachment)
        .where(PersonAttachment.id == attachment_id)
        .options(selectinload(PersonAttachment.person))
    )
    
    if attachment is None:
        flash(request, "Anexo não encontrado.", "error")
        return RedirectResponse("/persons", status_code=303)
    
    if not _can_manage(user, attachment.person):
        flash(request, "Acesso negado.", "error")
        return RedirectResponse("/persons", status_code=303)
    
    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada.", "error")
        return RedirectResponse(f"/persons/{attachment.person_id}", status_code=303)
    
    file_path = attachment.file_path
    db.delete(attachment)
    db.commit()
    delete_relative_upload(file_path)
    
    flash(request, "Anexo removido.", "success")
    return RedirectResponse(f"/persons/{attachment.person_id}", status_code=303)




@router.get("/{person_id}/json")
def person_json(person_id: int, request: Request, db: Session = Depends(get_db)):
    """Retorna dados da pessoa em JSON (para preencher formulários)"""
    user = require_user(request, db)
    
    person = db.scalar(
        select(Person)
        .where(Person.id == person_id, _visibility_filter(user))
    )
    
    if person is None:
        raise HTTPException(status_code=404, detail="Pessoa não encontrada")
    
    return JSONResponse({
        "id": person.id,
        "name": person.name,
        "cpf_cnpj": person.cpf_cnpj,
        "birth_date": person.birth_date,
        "person_type": person.person_type,
        "phone": person.phone,
        "mobile": person.mobile,
        "email": person.email,
        "website": person.website,
        "pix_key": person.pix_key,
        "accepts_communication": person.accepts_communication,
        "rg": person.rg,
        "foreign_id": person.foreign_id,
        "passport": person.passport,
        "passport_issue_date": person.passport_issue_date,
        "passport_expiry_date": person.passport_expiry_date,
        "passport_nationality": person.passport_nationality,
        "visa": person.visa,
        "visa_expiry_date": person.visa_expiry_date,
        "issuing_agency": person.issuing_agency,
        "nationality": person.nationality,
        "marital_status": person.marital_status,
        "gender": person.gender,
        "profession": person.profession,
        "income": person.income,
        "sales_channel": person.sales_channel,
        "emergency_contact_name": person.emergency_contact_name,
        "emergency_contact_phone": person.emergency_contact_phone,
        "country": person.country,
        "postal_code": person.postal_code,
        "state": person.state,
        "city": person.city,
        "neighborhood": person.neighborhood,
        "street": person.street,
        "number": person.number,
        "complement": person.complement,
        "notes": person.notes,
        "is_complete": person.is_complete
    })