from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ChatMessage, ChatGroup, ChatGroupMember, ChatGroupMessage, WebCompany, QuoteActivity, QuoteGroup, WebUser
from .realtime import avatar_url, manager

# O chat comercial deve mostrar somente acontecimentos que realmente pedem a
# atenção da equipe. Cálculos, edições de tarifa e salvamentos técnicos ficam no
# histórico da cotação, sem inundar a conversa.
CHAT_ACTIVITY_EVENTS = {
    "quote_created",
    "quote_assigned",
    "quote_transferred_accepted",
    "quote_transferred_flight",
}


def _payload(
    message: ChatMessage,
    actor: WebUser,
    *,
    group: QuoteGroup | None = None,
    event: str = "quote_updated",
) -> dict[str, Any]:
    return {
        "type": "chat_message",
        "id": message.id,
        "user_id": actor.id,
        "user_name": actor.name,
        "avatar_url": avatar_url(actor),
        "message": message.message,
        "attachment_url": "",
        "attachment_name": "",
        "attachment_type": f"system/{event}",
        "attachment_size": 0,
        "created_at": message.created_at.isoformat(),
        "activity_event": event,
        "is_system_activity": True,
        "quote_group_id": getattr(group, "id", None),
        "quote_title": getattr(group, "quote_name", None),
    }


_AERIAL_SCHEMA_READY = False

def ensure_aerial_group(db: Session, company_id: int, actor_id: int, *, create_if_missing: bool = True):
    """Garante o grupo aéreo da empresa e seus participantes atuais.

    Só executado ao abrir o chat ou salvar uma atividade, não nas páginas normais.
    """
    if not company_id:
        return None
    global _AERIAL_SCHEMA_READY
    # Na Vercel cada instância verifica o esquema somente uma vez.
    if not _AERIAL_SCHEMA_READY:
        for table in (ChatGroup.__table__, ChatGroupMember.__table__, ChatGroupMessage.__table__):
            table.create(bind=db.get_bind(), checkfirst=True)
        _AERIAL_SCHEMA_READY = True
    company = db.get(WebCompany, company_id)
    if not company:
        return None
    group_name = f"Grupo aéreo da {company.name}"[:80]
    existing = db.scalar(select(ChatGroup).where(
        ChatGroup.company_id == company_id, ChatGroup.name == group_name).limit(1))
    if existing is None:
        if not create_if_missing:
            return None
        existing = ChatGroup(company_id=company_id, name=group_name, created_by=actor_id)
        db.add(existing)
        db.flush()
    member_ids = set(db.scalars(select(ChatGroupMember.user_id).where(
        ChatGroupMember.group_id == existing.id)).all())
    people = db.scalars(select(WebUser.id).where(
        WebUser.company_id == company_id, WebUser.active.is_(True))).all()
    for person_id in people:
        if person_id not in member_ids:
            db.add(ChatGroupMember(group_id=existing.id, user_id=person_id,
                                   is_admin=person_id == actor_id, last_read_id=0))
    return existing


def record_quote_activity(
    db: Session,
    actor: WebUser,
    group: QuoteGroup | None,
    message_text: str,
    *,
    event: str = "quote_updated",
    send_to_chat: bool | None = None,
    record_audit: bool = True,
) -> tuple[ChatMessage | None, dict[str, Any] | None]:
    """Registra uma alteração da cotação e, quando necessário, avisa o chat.

    O histórico detalhado fica em ``web_quote_activities``. O chat recebe apenas
    criação, troca de responsável e transferências operacionais. A função não faz
    commit, permitindo que a alteração e seu registro sejam salvos juntos.
    """
    text = " ".join(str(message_text or "").split()).strip()[:2000]
    if not text:
        return None, None

    if record_audit and group is not None:
        db.add(
            QuoteActivity(
                company_id=actor.company_id,
                group_id=group.id,
                actor_user_id=actor.id,
                event=str(event or "quote_updated")[:80],
                message=text,
                created_at=datetime.utcnow(),
            )
        )
        db.flush()

    # Todas as ações de cotações com auditoria vão para o grupo AÉREO.
    # O grupo tradicional da empresa recebe somente conversa humana.
    if actor.company_id and record_audit and group is not None:
        aerial = ensure_aerial_group(db, actor.company_id, actor.id)
        if aerial:
            db.add(ChatGroupMessage(group_id=aerial.id, user_id=actor.id, message=text))
            db.flush()
    return None, None  # JS atual já consulta novos grupos incrementalmente.

async def publish_quote_activity(company_id: int | None, payload: dict[str, Any] | None) -> None:
    if company_id and payload:
        await manager.broadcast(company_id, payload)

# DBM-MELHORIAS-20261101
