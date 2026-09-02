from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from base64 import urlsafe_b64decode, urlsafe_b64encode

try:
    import bcrypt  # type: ignore
except Exception:  # pragma: no cover - fallback só é usado sem dependência instalada
    bcrypt = None

PBKDF2_ITERATIONS = 390_000


def hash_password(password: str) -> str:
    if bcrypt is not None:
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")

    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        PBKDF2_ITERATIONS,
        urlsafe_b64encode(salt).decode("ascii"),
        urlsafe_b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, stored_hash: str) -> bool:
    if stored_hash.startswith(("$2a$", "$2b$", "$2y$")):
        if bcrypt is None:
            return False
        try:
            return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))
        except Exception:
            return False

    if stored_hash.startswith("pbkdf2_sha256$"):
        try:
            _, iterations, salt_b64, digest_b64 = stored_hash.split("$", 3)
            salt = urlsafe_b64decode(salt_b64.encode("ascii"))
            expected = urlsafe_b64decode(digest_b64.encode("ascii"))
            actual = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"), salt, int(iterations)
            )
            return hmac.compare_digest(actual, expected)
        except Exception:
            return False

    return False


def validate_password(password: str) -> tuple[bool, str]:
    if len(password) < 8:
        return False, "A senha precisa ter pelo menos 8 caracteres."
    if not any(char.isupper() for char in password):
        return False, "Inclua ao menos uma letra maiúscula."
    if not any(char.islower() for char in password):
        return False, "Inclua ao menos uma letra minúscula."
    if not any(char.isdigit() for char in password):
        return False, "Inclua ao menos um número."
    return True, "OK"


def ensure_csrf_token(session: dict) -> str:
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def validate_csrf_token(session: dict, received: str | None) -> bool:
    expected = session.get("csrf_token")
    return bool(expected and received and hmac.compare_digest(str(expected), str(received)))
