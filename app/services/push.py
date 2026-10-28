"""Entrega Web Push para dispositivos que optaram por receber notificações."""
from __future__ import annotations

import json
import logging
import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import PushSubscription

logger = logging.getLogger(__name__)


def send_push(db: Session, user_id: int, title: str, body: str, url: str) -> int:
    key = os.getenv("VAPID_PRIVATE_KEY", "").strip().replace("\\n", "\n")
    subject = os.getenv("VAPID_SUBJECT", "").strip()
    if not key or not subject:
        return 0
    try:
        from pywebpush import WebPushException, webpush
        from py_vapid import Vapid
    except ImportError:
        logger.warning("pywebpush não instalado: push do sistema indisponível")
        return 0

    try:
        vapid_key = Vapid.from_pem(key.encode("utf-8")) if key.startswith("-----BEGIN") else key
    except Exception:
        logger.error("VAPID_PRIVATE_KEY inválida")
        return 0
    subscriptions = db.scalars(select(PushSubscription).where(PushSubscription.user_id == user_id)).all()
    sent = 0
    data = json.dumps({"title": title, "body": body, "url": url}, ensure_ascii=False)
    for subscription in subscriptions:
        try:
            webpush(
                subscription_info={"endpoint": subscription.endpoint,
                                   "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth}},
                data=data, vapid_private_key=vapid_key,
                vapid_claims={"sub": subject}, ttl=86400,
            )
            sent += 1
        except WebPushException as exc:
            if getattr(getattr(exc, "response", None), "status_code", None) in (404, 410):
                db.delete(subscription)
            else:
                logger.warning("Falha ao enviar push para usuário %s: %s", user_id, type(exc).__name__)
        except Exception as exc:
            logger.warning("Falha no push para usuário %s: %s", user_id, type(exc).__name__)
    db.commit()
    return sent
