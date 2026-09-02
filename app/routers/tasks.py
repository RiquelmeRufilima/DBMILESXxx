from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import case, desc, func, select
from sqlalchemy.orm import Session, selectinload

from ..config import TASK_UPLOAD_DIR
from ..database import get_db
from ..dependencies import current_user
from ..models import CompanyTask, QuoteGroup, WebUser
from ..security import validate_csrf_token
from ..services.notifications import create_notification
from ..services.realtime import manager
from ..services.uploads import delete_relative_upload, save_upload_image
from ..web import context, flash, templates

router = APIRouter(prefix="/tasks", tags=["tasks"])

ALLOWED_PRIORITIES = {"normal", "alta", "urgente"}


def _task_scope(user):
    if user.company_id:
        return CompanyTask.company_id == user.company_id
    return CompanyTask.created_by_user_id == user.id


def _quote_scope(user):
    if user.company_id:
        return QuoteGroup.company_id == user.company_id
    return QuoteGroup.user_id == user.id


def _get_task_or_none(db: Session, user, task_id: int) -> CompanyTask | None:
    return db.scalar(
        select(CompanyTask)
        .where(CompanyTask.id == task_id, _task_scope(user))
        .options(
            selectinload(CompanyTask.created_by),
            selectinload(CompanyTask.assigned_user),
            selectinload(CompanyTask.quote_group),
        )
    )


def _parse_due_at(raw: str) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    return datetime.fromisoformat(text)


def _safe_return_to(raw: str | None, fallback: str = "/tasks") -> str:
    value = str(raw or "").strip()
    if value.startswith("/") and not value.startswith("//"):
        return value
    return fallback


def _quote_id_for_user(db: Session, user, raw: str) -> tuple[int | None, str | None]:
    text = str(raw or "").strip()
    if not text:
        return None, None
    try:
        quote_id = int(text)
    except ValueError:
        return None, "O número da cotação é inválido."

    quote = db.scalar(
        select(QuoteGroup.id).where(QuoteGroup.id == quote_id, _quote_scope(user))
    )
    if quote is None:
        return None, "Cotação não encontrada na sua empresa."
    return quote_id, None


def _quotes_for_form(db: Session, user) -> list[QuoteGroup]:
    return list(
        db.scalars(
            select(QuoteGroup)
            .where(_quote_scope(user))
            .order_by(desc(QuoteGroup.updated_at), desc(QuoteGroup.created_at))
            .limit(80)
        ).all()
    )


async def _notify_task_event(
    db: Session,
    actor,
    *,
    task_id: int,
    title: str,
    action: str,
    priority: str = "normal",
    status: str = "pendente",
    link: str | None = None,
) -> None:
    """Tarefas são alertas reais: entram no sininho e fazem som.

    O evento é enviado à empresa inteira, exceto para o usuário que executou
    a ação. Isso evita que criar/editar a própria tarefa toque no mesmo PC.
    """
    if not getattr(actor, "company_id", None):
        return

    action_labels = {
        "created": "Nova tarefa",
        "updated": "Tarefa atualizada",
        "completed": "Tarefa concluída",
        "reopened": "Tarefa reaberta",
        "deleted": "Tarefa removida",
    }
    label = action_labels.get(action, "Tarefa atualizada")
    target_link = link or (f"/tasks/{task_id}" if action != "deleted" else "/tasks")

    recipients = list(
        db.scalars(
            select(WebUser).where(
                WebUser.company_id == actor.company_id,
                WebUser.id != actor.id,
                WebUser.active.is_(True),
            )
        ).all()
    )
    for recipient in recipients:
        create_notification(
            db,
            recipient.id,
            f"{label}: {title}"[:180],
            f"{actor.name} • prioridade {priority} • status {status}"[:300],
            kind="task",
            link=target_link,
            commit=False,
        )
    if recipients:
        db.commit()

    await manager.broadcast(
        actor.company_id,
        {
            "type": "task_event",
            "action": action,
            "task_id": task_id,
            "title": title,
            "priority": priority,
            "status": status,
            "actor_user_id": actor.id,
            "actor_user_name": actor.name,
            "link": target_link,
        },
    )


@router.get("")
def tasks_page(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)

    tasks = list(
        db.scalars(
            select(CompanyTask)
            .where(_task_scope(user))
            .options(
                selectinload(CompanyTask.created_by),
                selectinload(CompanyTask.assigned_user),
                selectinload(CompanyTask.quote_group),
            )
            .order_by(
                case((CompanyTask.status == "pendente", 0), else_=1),
                CompanyTask.due_at.is_(None),
                CompanyTask.due_at.asc(),
                desc(CompanyTask.created_at),
            )
        ).all()
    )
    pending_tasks = [task for task in tasks if task.status == "pendente"]
    completed_tasks = [task for task in tasks if task.status == "concluida"]

    return templates.TemplateResponse(
        request,
        "tasks/index.html",
        context(
            request,
            user=user,
            tasks=tasks,
            pending_tasks=pending_tasks,
            completed_tasks=completed_tasks,
        ),
    )


@router.get("/new")
def new_task_page(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)

    return templates.TemplateResponse(
        request,
        "tasks/form.html",
        context(
            request,
            user=user,
            task=None,
            form_action="/tasks/new",
            quotes=_quotes_for_form(db, user),
        ),
    )


@router.post("/new")
async def create_task(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)

    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada. Tente novamente.", "error")
        return RedirectResponse("/tasks/new", status_code=303)

    title = str(form.get("title") or "").strip()
    description = str(form.get("description") or "").strip()
    priority = str(form.get("priority") or "normal").strip().lower()
    if not title:
        flash(request, "Informe o título da tarefa.", "error")
        return RedirectResponse("/tasks/new", status_code=303)
    if priority not in ALLOWED_PRIORITIES:
        priority = "normal"

    try:
        due_at = _parse_due_at(str(form.get("due_at") or ""))
    except ValueError:
        flash(request, "A data ou o horário informado é inválido.", "error")
        return RedirectResponse("/tasks/new", status_code=303)

    quote_group_id, quote_error = _quote_id_for_user(
        db, user, str(form.get("quote_group_id") or "")
    )
    if quote_error:
        flash(request, quote_error, "error")
        return RedirectResponse("/tasks/new", status_code=303)

    try:
        photo_path = await save_upload_image(
            form.get("photo"),
            TASK_UPLOAD_DIR,
            max_bytes=8 * 1024 * 1024,
            filename_prefix="task",
        )
    except ValueError as exc:
        flash(request, str(exc), "error")
        return RedirectResponse("/tasks/new", status_code=303)

    task = CompanyTask(
        company_id=user.company_id,
        created_by_user_id=user.id,
        assigned_user_id=user.id,
        quote_group_id=quote_group_id,
        title=title[:180],
        description=description or None,
        priority=priority,
        status="pendente",
        due_at=due_at,
        photo_path=photo_path,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    await _notify_task_event(
        db,
        user,
        task_id=task.id,
        title=task.title,
        action="created",
        priority=task.priority,
        status=task.status,
    )
    flash(request, "Tarefa criada com sucesso.", "success")
    return RedirectResponse(f"/tasks/{task.id}", status_code=303)


@router.get("/{task_id}")
def task_detail(task_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)

    task = _get_task_or_none(db, user, task_id)
    if task is None:
        flash(request, "Tarefa não encontrada.", "error")
        return RedirectResponse("/tasks", status_code=303)

    return templates.TemplateResponse(
        request,
        "tasks/form.html",
        context(
            request,
            user=user,
            task=task,
            form_action=f"/tasks/{task.id}",
            quotes=_quotes_for_form(db, user),
        ),
    )


@router.post("/{task_id}")
async def update_task(task_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)

    task = _get_task_or_none(db, user, task_id)
    if task is None:
        flash(request, "Tarefa não encontrada.", "error")
        return RedirectResponse("/tasks", status_code=303)

    form = await request.form()
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada. Tente novamente.", "error")
        return RedirectResponse(f"/tasks/{task.id}", status_code=303)

    title = str(form.get("title") or "").strip()
    description = str(form.get("description") or "").strip()
    priority = str(form.get("priority") or "normal").strip().lower()
    if not title:
        flash(request, "Informe o título da tarefa.", "error")
        return RedirectResponse(f"/tasks/{task.id}", status_code=303)
    if priority not in ALLOWED_PRIORITIES:
        priority = "normal"

    try:
        due_at = _parse_due_at(str(form.get("due_at") or ""))
    except ValueError:
        flash(request, "A data ou o horário informado é inválido.", "error")
        return RedirectResponse(f"/tasks/{task.id}", status_code=303)

    quote_group_id, quote_error = _quote_id_for_user(
        db, user, str(form.get("quote_group_id") or "")
    )
    if quote_error:
        flash(request, quote_error, "error")
        return RedirectResponse(f"/tasks/{task.id}", status_code=303)

    remove_photo = str(form.get("remove_photo") or "") == "1"
    old_photo = task.photo_path
    try:
        new_photo = await save_upload_image(
            form.get("photo"),
            TASK_UPLOAD_DIR,
            max_bytes=8 * 1024 * 1024,
            filename_prefix="task",
        )
    except ValueError as exc:
        flash(request, str(exc), "error")
        return RedirectResponse(f"/tasks/{task.id}", status_code=303)

    task.title = title[:180]
    task.description = description or None
    task.priority = priority
    task.due_at = due_at
    task.quote_group_id = quote_group_id
    if new_photo:
        task.photo_path = new_photo
    elif remove_photo:
        task.photo_path = None
    task.updated_at = datetime.utcnow()
    db.commit()

    if old_photo and old_photo != task.photo_path:
        delete_relative_upload(old_photo)

    await _notify_task_event(
        db,
        user,
        task_id=task.id,
        title=task.title,
        action="updated",
        priority=task.priority,
        status=task.status,
    )
    flash(request, "Tarefa atualizada com sucesso.", "success")
    return RedirectResponse(f"/tasks/{task.id}", status_code=303)


@router.post("/{task_id}/toggle")
async def toggle_task(task_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)

    task = _get_task_or_none(db, user, task_id)
    if task is None:
        flash(request, "Tarefa não encontrada.", "error")
        return RedirectResponse("/tasks", status_code=303)

    form = await request.form()
    return_to = _safe_return_to(str(form.get("return_to") or ""))
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada. Tente novamente.", "error")
        return RedirectResponse(return_to, status_code=303)

    if task.status == "concluida":
        task.status = "pendente"
        task.completed_at = None
        message = "Tarefa reaberta."
    else:
        task.status = "concluida"
        task.completed_at = datetime.utcnow()
        message = "Tarefa marcada como feita."
    task.updated_at = datetime.utcnow()
    db.commit()

    await _notify_task_event(
        db,
        user,
        task_id=task.id,
        title=task.title,
        action="reopened" if task.status == "pendente" else "completed",
        priority=task.priority,
        status=task.status,
    )
    flash(request, message, "success")
    return RedirectResponse(return_to, status_code=303)


@router.post("/{task_id}/delete")
async def delete_task(task_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)

    task = _get_task_or_none(db, user, task_id)
    if task is None:
        flash(request, "Tarefa não encontrada.", "error")
        return RedirectResponse("/tasks", status_code=303)

    form = await request.form()
    return_to = _safe_return_to(str(form.get("return_to") or ""))
    if not validate_csrf_token(request.session, str(form.get("csrf_token") or "")):
        flash(request, "Sessão expirada. Tente novamente.", "error")
        return RedirectResponse(return_to, status_code=303)

    photo_path = task.photo_path
    deleted_task_id = task.id
    deleted_title = task.title
    deleted_priority = task.priority
    db.delete(task)
    db.commit()
    delete_relative_upload(photo_path)

    await _notify_task_event(
        db,
        user,
        task_id=deleted_task_id,
        title=deleted_title,
        action="deleted",
        priority=deleted_priority,
        status="excluida",
        link="/tasks",
    )
    flash(request, "Tarefa excluída.", "success")
    return RedirectResponse(return_to, status_code=303)
