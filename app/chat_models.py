from __future__ import annotations
from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship as orm_relationship
from .database import Base
from .models import WebUser

class ChatIdentity(Base):
    __tablename__ = "web_chat_identities"
    user_id: Mapped[int] = mapped_column(ForeignKey("web_users.id", ondelete="CASCADE"), primary_key=True)
    contact_id: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    user: Mapped[WebUser] = orm_relationship(foreign_keys=[user_id])

class UserChatContact(Base):
    __tablename__ = "web_user_chat_contacts"
    __table_args__ = (UniqueConstraint("owner_user_id", "contact_user_id", name="uq_web_user_chat_contact"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("web_users.id", ondelete="CASCADE"), index=True)
    contact_user_id: Mapped[int] = mapped_column(ForeignKey("web_users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    owner: Mapped[WebUser] = orm_relationship(foreign_keys=[owner_user_id])
    contact: Mapped[WebUser] = orm_relationship(foreign_keys=[contact_user_id])

class PrivateChatMessage(Base):
    __tablename__ = "web_private_chat_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("web_users.id", ondelete="CASCADE"), index=True)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("web_users.id", ondelete="CASCADE"), index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    sender: Mapped[WebUser] = orm_relationship(foreign_keys=[sender_id])
    recipient: Mapped[WebUser] = orm_relationship(foreign_keys=[recipient_id])
