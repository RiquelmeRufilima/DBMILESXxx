from __future__ import annotations

import base64
import hashlib
import hmac
import io
import os
import secrets
import struct
import time
from datetime import datetime
from urllib.parse import quote

import qrcode
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, inspect, select, text
from sqlalchemy.orm import Session

from ..config import APP_NAME, SECRET_KEY
from ..models import AuthRecoveryCode, AuthTotpCredential, WebUser


_TOTP_SCHEMA_READY = False
RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class TotpConfigurationError(RuntimeError):
    pass


def ensure_totp_schema(db: Session) -> None:
    global _TOTP_SCHEMA_READY
    if _TOTP_SCHEMA_READY:
        return

    bind = db.get_bind()
    AuthTotpCredential.__table__.create(bind=bind, checkfirst=True)
    AuthRecoveryCode.__table__.create(bind=bind, checkfirst=True)

    # V2.16: login com Authenticator passou a ser opcional. Bancos já existentes
    # não possuem esta coluna, portanto ela é adicionada sem apagar o TOTP atual.
    # DEFAULT FALSE garante que ninguém passe a exigir 2FA automaticamente só
    # porque usava a versão antiga obrigatória.
    columns = {col["name"] for col in inspect(bind).get_columns("web_auth_totp_credentials")}
    if "login_2fa_enabled" not in columns:
        with bind.begin() as conn:
            conn.execute(
                text(
                    "ALTER TABLE web_auth_totp_credentials "
                    "ADD COLUMN login_2fa_enabled BOOLEAN NOT NULL DEFAULT FALSE"
                )
            )

    _TOTP_SCHEMA_READY = True


def _fernet() -> Fernet:
    # A chave é derivada da SECRET_KEY do servidor. Trocar SECRET_KEY em produção
    # exige reconfigurar o Authenticator dos usuários.
    digest = hashlib.sha256(SECRET_KEY.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode("ascii")).decode("ascii")


def decrypt_secret(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("ascii")
    except InvalidToken as exc:
        raise TotpConfigurationError(
            "Não foi possível ler a chave do Authenticator. A SECRET_KEY do servidor pode ter mudado."
        ) from exc


def generate_totp_secret() -> str:
    # 160 bits, padrão compatível com Google Authenticator.
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _normalized_base32(secret: str) -> bytes:
    clean = "".join(ch for ch in str(secret or "").upper() if ch.isalnum())
    padding = "=" * ((8 - len(clean) % 8) % 8)
    return base64.b32decode(clean + padding, casefold=True)


def totp_code(secret: str, *, at_time: int | None = None, step: int = 30, digits: int = 6) -> str:
    when = int(time.time() if at_time is None else at_time)
    counter = when // step
    key = _normalized_base32(secret)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = (
        ((digest[offset] & 0x7F) << 24)
        | ((digest[offset + 1] & 0xFF) << 16)
        | ((digest[offset + 2] & 0xFF) << 8)
        | (digest[offset + 3] & 0xFF)
    )
    return str(binary % (10 ** digits)).zfill(digits)


def verify_totp(secret: str, code: str, *, window: int = 1) -> bool:
    code = "".join(ch for ch in str(code or "") if ch.isdigit())
    if len(code) != 6:
        return False
    now = int(time.time())
    for offset in range(-window, window + 1):
        candidate = totp_code(secret, at_time=now + (offset * 30))
        if hmac.compare_digest(candidate, code):
            return True
    return False


def provisioning_uri(*, secret: str, email: str) -> str:
    issuer = os.getenv("TOTP_ISSUER", APP_NAME or "DBMILESX").strip() or "DBMILESX"
    account = f"{issuer}:{email}"
    return (
        f"otpauth://totp/{quote(account, safe='')}"
        f"?secret={quote(secret)}"
        f"&issuer={quote(issuer)}"
        "&algorithm=SHA1&digits=6&period=30"
    )


def qr_data_uri(uri: str) -> str:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=3,
    )
    qr.add_data(uri)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def get_credential(db: Session, user_id: int) -> AuthTotpCredential | None:
    ensure_totp_schema(db)
    return db.get(AuthTotpCredential, int(user_id))


def ensure_pending_credential(
    db: Session,
    user: WebUser,
    *,
    reset_secret: bool = False,
) -> AuthTotpCredential:
    ensure_totp_schema(db)
    credential = db.get(AuthTotpCredential, int(user.id))

    if credential is None:
        credential = AuthTotpCredential(
            user_id=int(user.id),
            secret_encrypted=encrypt_secret(generate_totp_secret()),
            enabled=False,
            login_2fa_enabled=False,
        )
        db.add(credential)
        db.flush()
        return credential

    if reset_secret or not credential.secret_encrypted:
        credential.secret_encrypted = encrypt_secret(generate_totp_secret())
        credential.enabled = False
        credential.login_2fa_enabled = False
        credential.confirmed_at = None
        credential.updated_at = datetime.utcnow()
        db.flush()

    return credential


def credential_secret(credential: AuthTotpCredential) -> str:
    return decrypt_secret(credential.secret_encrypted)


def authenticator_configured(db: Session, user_id: int) -> bool:
    credential = get_credential(db, user_id)
    return bool(credential and credential.enabled and credential.confirmed_at)


def authenticator_enabled(db: Session, user_id: int) -> bool:
    """Compatibilidade: Authenticator configurado, independente do login 2FA."""
    return authenticator_configured(db, user_id)


def login_2fa_enabled(db: Session, user_id: int) -> bool:
    credential = get_credential(db, user_id)
    return bool(
        credential
        and credential.enabled
        and credential.confirmed_at
        and credential.login_2fa_enabled
    )


def _normalize_recovery_code(code: str) -> str:
    return "".join(ch for ch in str(code or "").upper() if ch.isalnum())


def _recovery_hash(user_id: int, code: str) -> str:
    normalized = _normalize_recovery_code(code)
    return hmac.new(
        SECRET_KEY.encode("utf-8"),
        f"{int(user_id)}|{normalized}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def generate_recovery_codes(db: Session, user_id: int, *, count: int = 8) -> list[str]:
    ensure_totp_schema(db)
    db.execute(delete(AuthRecoveryCode).where(AuthRecoveryCode.user_id == int(user_id)))

    codes: list[str] = []
    for _ in range(max(6, min(count, 12))):
        raw = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(12))
        display = f"{raw[:4]}-{raw[4:8]}-{raw[8:]}"
        codes.append(display)
        db.add(
            AuthRecoveryCode(
                user_id=int(user_id),
                code_hash=_recovery_hash(user_id, display),
            )
        )
    db.flush()
    return codes


def consume_recovery_code(db: Session, user_id: int, code: str) -> bool:
    ensure_totp_schema(db)
    digest = _recovery_hash(user_id, code)
    row = db.scalar(
        select(AuthRecoveryCode).where(
            AuthRecoveryCode.user_id == int(user_id),
            AuthRecoveryCode.code_hash == digest,
            AuthRecoveryCode.used_at.is_(None),
        )
    )
    if row is None:
        return False
    row.used_at = datetime.utcnow()
    db.flush()
    return True


def verify_totp_or_recovery(
    db: Session,
    user_id: int,
    code: str,
    *,
    allow_recovery: bool = True,
) -> tuple[bool, str]:
    credential = get_credential(db, user_id)
    if credential is None or not credential.enabled:
        return False, "Authenticator ainda não configurado."

    secret = credential_secret(credential)
    if verify_totp(secret, code):
        return True, "totp"

    if allow_recovery and consume_recovery_code(db, user_id, code):
        return True, "recovery"

    return False, "invalid"
