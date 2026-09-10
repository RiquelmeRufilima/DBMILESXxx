from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import UserPreference, UserProfile, WebUser


def ensure_user_defaults(db: Session, user: WebUser) -> None:
    changed = False
    if user.profile is None:
        db.add(UserProfile(user_id=user.id))
        changed = True
    if user.preference is None:
        db.add(UserPreference(user_id=user.id))
        changed = True
    if changed:
        db.commit()
        db.refresh(user)
