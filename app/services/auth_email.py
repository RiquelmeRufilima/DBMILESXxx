from __future__ import annotations

import hashlib
import json
import os
import secrets
import smtplib
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from email.message import EmailMessage
from html import escape

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import APP_NAME, SECRET_KEY
from ..models import AuthEmailCode


class EmailDeliveryError(RuntimeError):
    pass


_AUTH_SCHEMA_READY = False


def ensure_auth_schema(db: Session) -> None:
    """Cria somente a tabela de códigos quando ela ainda não existir.

    Isso é propositalmente lazy para funcionar no Neon/Vercel sem voltar a
    executar todas as migrações pesadas durante o cold start.
    """
    global _AUTH_SCHEMA_READY
    if _AUTH_SCHEMA_READY:
        return
    bind = db.get_bind()
    AuthEmailCode.__table__.create(bind=bind, checkfirst=True)
    _AUTH_SCHEMA_READY = True


def _normalized_email(email: str) -> str:
    return str(email or "").strip().lower()[:180]


def _code_digest(email: str, purpose: str, code: str) -> str:
    raw = f"{SECRET_KEY}|{_normalized_email(email)}|{purpose}|{code}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def issue_email_code(
    db: Session,
    *,
    email: str,
    purpose: str,
    ttl_minutes: int = 15,
    min_interval_seconds: int = 45,
) -> str:
    ensure_auth_schema(db)
    email = _normalized_email(email)
    now = datetime.utcnow()

    latest = db.scalar(
        select(AuthEmailCode)
        .where(AuthEmailCode.email == email, AuthEmailCode.purpose == purpose)
        .order_by(AuthEmailCode.id.desc())
        .limit(1)
    )
    if latest and latest.created_at and (now - latest.created_at).total_seconds() < min_interval_seconds:
        wait = max(1, min_interval_seconds - int((now - latest.created_at).total_seconds()))
        raise ValueError(f"Aguarde {wait} segundo(s) antes de solicitar outro código.")

    # Invalida códigos anteriores do mesmo fluxo.
    previous = db.scalars(
        select(AuthEmailCode).where(
            AuthEmailCode.email == email,
            AuthEmailCode.purpose == purpose,
            AuthEmailCode.consumed_at.is_(None),
        )
    ).all()
    for item in previous:
        item.consumed_at = now

    code = f"{secrets.randbelow(1_000_000):06d}"
    db.add(
        AuthEmailCode(
            email=email,
            purpose=purpose,
            code_hash=_code_digest(email, purpose, code),
            expires_at=now + timedelta(minutes=max(5, ttl_minutes)),
            attempts=0,
            created_at=now,
        )
    )
    return code


def verify_email_code(db: Session, *, email: str, purpose: str, code: str) -> tuple[bool, str]:
    ensure_auth_schema(db)
    email = _normalized_email(email)
    code = "".join(ch for ch in str(code or "") if ch.isdigit())[:6]
    now = datetime.utcnow()

    item = db.scalar(
        select(AuthEmailCode)
        .where(
            AuthEmailCode.email == email,
            AuthEmailCode.purpose == purpose,
            AuthEmailCode.consumed_at.is_(None),
        )
        .order_by(AuthEmailCode.id.desc())
        .limit(1)
    )
    if item is None:
        return False, "Código não encontrado. Solicite um novo código."
    if item.expires_at <= now:
        item.consumed_at = now
        return False, "Este código expirou. Solicite um novo código."
    if int(item.attempts or 0) >= 5:
        item.consumed_at = now
        return False, "Muitas tentativas. Solicite um novo código."

    item.attempts = int(item.attempts or 0) + 1
    if not secrets.compare_digest(item.code_hash, _code_digest(email, purpose, code)):
        if item.attempts >= 5:
            item.consumed_at = now
        return False, "Código incorreto. Confira o e-mail e tente novamente."

    item.consumed_at = now
    return True, "OK"


def _email_copy(*, code: str, purpose: str, recipient_name: str = "") -> tuple[str, str, str]:
    name = escape(str(recipient_name or "").strip())
    greeting = f"Olá, {name}." if name else "Olá."
    if purpose == "register":
        subject = f"{code} é seu código de confirmação | {APP_NAME}"
        headline = "Confirme sua conta"
        description = "Use o código abaixo para confirmar seu e-mail e concluir a criação da sua conta."
    else:
        subject = f"{code} é seu código para redefinir a senha | {APP_NAME}"
        headline = "Redefinição de senha"
        description = "Use o código abaixo para criar uma nova senha da sua conta."

    text = (
        f"{greeting}\n\n{description}\n\n"
        f"Código: {code}\n\n"
        "O código expira em 15 minutos. Se você não solicitou esta ação, ignore esta mensagem."
    )
    html = f"""<!doctype html>
<html><body style="margin:0;background:#07111f;font-family:Arial,sans-serif;color:#eaf7ff">
  <div style="max-width:560px;margin:0 auto;padding:30px 18px">
    <div style="border:1px solid #1d4560;border-radius:22px;background:#0d1c2f;padding:30px">
      <div style="font-size:12px;letter-spacing:.16em;color:#58d8f2;font-weight:800">DBMILESX</div>
      <h1 style="font-size:26px;margin:12px 0 8px">{headline}</h1>
      <p style="color:#a9c0d3;line-height:1.6">{greeting} {description}</p>
      <div style="font-size:38px;letter-spacing:.22em;font-weight:900;text-align:center;padding:22px 12px;margin:24px 0;border-radius:16px;background:#07182a;border:1px solid #23516c;color:#8bedff">{escape(code)}</div>
      <p style="color:#8ba6bb;font-size:13px;line-height:1.6">Este código expira em 15 minutos. Nunca compartilhe este código com terceiros.</p>
    </div>
  </div>
</body></html>"""
    return subject, text, html


def _send_resend(*, to_email: str, subject: str, text: str, html: str) -> bool:
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    if not api_key:
        return False
    sender = os.getenv("AUTH_EMAIL_FROM", "").strip()
    if not sender:
        raise EmailDeliveryError("Configure AUTH_EMAIL_FROM no Vercel para usar o Resend.")
    payload = json.dumps({"from": sender, "to": [to_email], "subject": subject, "text": text, "html": html}).encode("utf-8")
    request = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        method="POST",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            if not 200 <= int(response.status) < 300:
                raise EmailDeliveryError(f"Resend respondeu HTTP {response.status}.")
        return True
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:500]
        raise EmailDeliveryError(f"Falha no Resend (HTTP {exc.code}): {detail}") from exc
    except Exception as exc:
        raise EmailDeliveryError(f"Não foi possível enviar o e-mail pelo Resend: {exc}") from exc


def _send_smtp(*, to_email: str, subject: str, text: str, html: str) -> bool:
    user = os.getenv("SMTP_USER", os.getenv("SMTP_USERNAME", "")).strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()
    host = os.getenv("SMTP_HOST", "smtp.gmail.com").strip()
    port = int(os.getenv("SMTP_PORT", "587"))
    sender = os.getenv("AUTH_EMAIL_FROM", os.getenv("SMTP_FROM", user)).strip()
    if not user or not password:
        return False
    if not sender:
        sender = user

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = to_email
    message.set_content(text)
    message.add_alternative(html, subtype="html")

    use_ssl = os.getenv("SMTP_SSL", "false").strip().lower() in {"1", "true", "yes", "sim", "on"}
    use_starttls = os.getenv("SMTP_STARTTLS", "true").strip().lower() in {"1", "true", "yes", "sim", "on"}
    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=15) as smtp:
                smtp.login(user, password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=15) as smtp:
                smtp.ehlo()
                if use_starttls:
                    smtp.starttls()
                    smtp.ehlo()
                smtp.login(user, password)
                smtp.send_message(message)
        return True
    except Exception as exc:
        raise EmailDeliveryError(f"Não foi possível enviar o e-mail por SMTP: {exc}") from exc


def send_auth_code(*, to_email: str, code: str, purpose: str, recipient_name: str = "") -> None:
    subject, text, html = _email_copy(code=code, purpose=purpose, recipient_name=recipient_name)
    if _send_resend(to_email=to_email, subject=subject, text=text, html=html):
        return
    if _send_smtp(to_email=to_email, subject=subject, text=text, html=html):
        return
    raise EmailDeliveryError(
        "Envio de e-mail não configurado. Configure RESEND_API_KEY + AUTH_EMAIL_FROM "
        "ou SMTP_USER + SMTP_PASSWORD no Vercel."
    )
