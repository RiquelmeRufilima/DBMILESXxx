from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import smtplib
import socket
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from email.message import EmailMessage
from html import escape

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import APP_NAME, SECRET_KEY
from ..models import AuthEmailCode


logger = logging.getLogger(__name__)


class EmailDeliveryError(RuntimeError):
    pass


_AUTH_SCHEMA_READY = False


def ensure_auth_schema(db: Session) -> None:
    """Cria somente a tabela de códigos quando ela ainda não existir.

    A tabela é criada sob demanda para funcionar no Neon/Vercel sem executar
    todas as migrações durante o cold start.
    """
    global _AUTH_SCHEMA_READY
    if _AUTH_SCHEMA_READY:
        return
    bind = db.get_bind()
    AuthEmailCode.__table__.create(bind=bind, checkfirst=True)
    _AUTH_SCHEMA_READY = True


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "sim", "on"}


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
<html>
<body style="margin:0;background:#07111f;font-family:Arial,sans-serif;color:#eaf7ff">
  <div style="max-width:560px;margin:0 auto;padding:30px 18px">
    <div style="border:1px solid #1d4560;border-radius:22px;background:#0d1c2f;padding:30px">
      <div style="font-size:12px;letter-spacing:.16em;color:#58d8f2;font-weight:800">DBMILESX</div>
      <h1 style="font-size:26px;margin:12px 0 8px">{headline}</h1>
      <p style="color:#a9c0d3;line-height:1.6">{greeting} {description}</p>
      <div style="font-size:38px;letter-spacing:.22em;font-weight:900;text-align:center;padding:22px 12px;margin:24px 0;border-radius:16px;background:#07182a;border:1px solid #23516c;color:#8bedff">{escape(code)}</div>
      <p style="color:#8ba6bb;font-size:13px;line-height:1.6">
        Este código expira em 15 minutos. Nunca compartilhe este código com terceiros.
      </p>
    </div>
  </div>
</body>
</html>"""
    return subject, text, html


def email_provider_status() -> dict[str, object]:
    """Retorna somente status; nunca retorna senha/chave."""
    provider = os.getenv("EMAIL_PROVIDER", "auto").strip().lower() or "auto"
    return {
        "provider": provider,
        "resend_configured": bool(
            os.getenv("RESEND_API_KEY", "").strip()
            and os.getenv("AUTH_EMAIL_FROM", "").strip()
        ),
        "smtp_configured": bool(
            os.getenv("SMTP_USER", os.getenv("SMTP_USERNAME", "")).strip()
            and os.getenv("SMTP_PASSWORD", "").strip()
        ),
    }


def _sender_address(default_email: str = "") -> str:
    explicit = os.getenv("AUTH_EMAIL_FROM", os.getenv("SMTP_FROM", "")).strip()
    if explicit:
        return explicit

    email = default_email.strip()
    if not email:
        return ""

    name = os.getenv("SMTP_FROM_NAME", APP_NAME).strip() or APP_NAME
    return f"{name} <{email}>"


def _send_resend(*, to_email: str, subject: str, text: str, html: str) -> bool:
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    if not api_key:
        return False

    sender = _sender_address()
    if not sender:
        raise EmailDeliveryError(
            "Resend configurado sem remetente. Defina AUTH_EMAIL_FROM no Vercel."
        )

    payload = json.dumps(
        {
            "from": sender,
            "to": [to_email],
            "subject": subject,
            "text": text,
            "html": html,
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "DBMILESX/2.13",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read().decode("utf-8", errors="ignore")
            if not 200 <= int(response.status) < 300:
                raise EmailDeliveryError(f"Resend respondeu HTTP {response.status}.")
            logger.info(
                "Código de autenticação enviado via Resend para domínio %s",
                to_email.rsplit("@", 1)[-1],
            )
            return True
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:700]
        raise EmailDeliveryError(f"Falha no Resend (HTTP {exc.code}): {detail}") from exc
    except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
        raise EmailDeliveryError(f"Resend indisponível ou demorou para responder: {exc}") from exc
    except EmailDeliveryError:
        raise
    except Exception as exc:
        raise EmailDeliveryError(f"Não foi possível enviar o e-mail pelo Resend: {exc}") from exc


def _smtp_connection():
    user = os.getenv("SMTP_USER", os.getenv("SMTP_USERNAME", "")).strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()
    host = os.getenv("SMTP_HOST", "smtp.gmail.com").strip() or "smtp.gmail.com"

    if not user or not password:
        return None

    use_ssl = _env_bool("SMTP_SSL", False)
    use_starttls = _env_bool("SMTP_STARTTLS", not use_ssl)
    default_port = "465" if use_ssl else "587"
    port = int(os.getenv("SMTP_PORT", default_port))
    timeout = max(5, min(int(os.getenv("SMTP_TIMEOUT", "15")), 30))
    context = ssl.create_default_context()

    if use_ssl:
        smtp = smtplib.SMTP_SSL(host, port, timeout=timeout, context=context)
    else:
        smtp = smtplib.SMTP(host, port, timeout=timeout)
        smtp.ehlo()
        if use_starttls:
            smtp.starttls(context=context)
            smtp.ehlo()

    smtp.login(user, password)
    return smtp


def _send_smtp(*, to_email: str, subject: str, text: str, html: str) -> bool:
    user = os.getenv("SMTP_USER", os.getenv("SMTP_USERNAME", "")).strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()

    if not user or not password:
        return False

    sender = _sender_address(user)
    if not sender:
        sender = user

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = to_email
    message.set_content(text)
    message.add_alternative(html, subtype="html")

    attempts = max(1, min(int(os.getenv("SMTP_SEND_ATTEMPTS", "2")), 2))
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        smtp = None
        try:
            smtp = _smtp_connection()
            if smtp is None:
                return False
            smtp.send_message(message)
            logger.info(
                "Código de autenticação enviado via SMTP para domínio %s",
                to_email.rsplit("@", 1)[-1],
            )
            return True
        except smtplib.SMTPAuthenticationError as exc:
            raise EmailDeliveryError(
                "Falha de autenticação SMTP. No Gmail, use uma Senha de app, "
                "não a senha normal da conta."
            ) from exc
        except (smtplib.SMTPException, OSError, socket.timeout) as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(0.35)
        finally:
            if smtp is not None:
                try:
                    smtp.quit()
                except Exception:
                    pass

    raise EmailDeliveryError(f"Não foi possível enviar o e-mail por SMTP: {last_error}")


def send_auth_code(*, to_email: str, code: str, purpose: str, recipient_name: str = "") -> None:
    """Envia o código REAL antes de a rota devolver sucesso ao navegador.

    EMAIL_PROVIDER:
      auto   -> usa Resend se configurado e, se falhar/ausente, tenta SMTP.
      resend -> exige Resend.
      smtp   -> exige SMTP/Gmail.
    """
    subject, text, html = _email_copy(
        code=code,
        purpose=purpose,
        recipient_name=recipient_name,
    )

    provider = os.getenv("EMAIL_PROVIDER", "auto").strip().lower() or "auto"
    if provider not in {"auto", "resend", "smtp"}:
        raise EmailDeliveryError(
            "EMAIL_PROVIDER inválido. Use auto, resend ou smtp."
        )

    errors: list[str] = []

    if provider in {"auto", "resend"}:
        try:
            if _send_resend(
                to_email=to_email,
                subject=subject,
                text=text,
                html=html,
            ):
                return
        except EmailDeliveryError as exc:
            errors.append(str(exc))
            if provider == "resend":
                raise

    if provider in {"auto", "smtp"}:
        try:
            if _send_smtp(
                to_email=to_email,
                subject=subject,
                text=text,
                html=html,
            ):
                return
        except EmailDeliveryError as exc:
            errors.append(str(exc))
            if provider == "smtp":
                raise

    if errors:
        raise EmailDeliveryError(" | ".join(errors))

    raise EmailDeliveryError(
        "Envio de e-mail não configurado no Vercel. "
        "Para Gmail, configure EMAIL_PROVIDER=smtp, SMTP_USER e SMTP_PASSWORD "
        "(Senha de app). Para Resend, configure RESEND_API_KEY e AUTH_EMAIL_FROM."
    )
