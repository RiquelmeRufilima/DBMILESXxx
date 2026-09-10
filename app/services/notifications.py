from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import Notification


def create_notification(
    db: Session,
    user_id: int,
    title: str,
    message: str,
    *,
    kind: str = "info",
    link: str | None = None,
    commit: bool = True,
) -> Notification:
    notification = Notification(
        user_id=user_id,
        title=title[:180],
        message=message[:4000],
        kind=kind if kind in {"info", "success", "warning", "error", "chat", "request", "task"} else "info",
        link=link,
    )
    db.add(notification)
    if commit:
        db.commit()
        db.refresh(notification)
    return notification
