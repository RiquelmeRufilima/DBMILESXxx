from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ChatMessage, QuoteActivity, QuoteGroup, WebUser
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

    should_chat = event in CHAT_ACTIVITY_EVENTS if send_to_chat is None else bool(send_to_chat)
    if not should_chat or not actor.company_id:
        return None, None

    message = ChatMessage(
        company_id=actor.company_id,
        user_id=actor.id,
        message=text,
        attachment_type=f"system/{event}",
        created_at=datetime.utcnow(),
    )
    db.add(message)
    db.flush()

    # Atualizações operacionais continuam aparecendo no chat como avisos
    # centralizados, porém NÃO entram no sininho e NÃO geram som.
    return message, _payload(message, actor, group=group, event=event)


async def publish_quote_activity(company_id: int | None, payload: dict[str, Any] | None) -> None:
    if company_id and payload:
        await manager.broadcast(company_id, payload)
