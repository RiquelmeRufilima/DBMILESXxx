"""Optional RFC6238 TOTP, encrypted at rest with the application's stable SECRET_KEY."""
import base64
import hashlib
import hmac
import json
import secrets
import struct
import time
from cryptography.fernet import Fernet, InvalidToken
from ..config import SECRET_KEY


def _key():
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256((str(SECRET_KEY) + ':dbmilesx:totp:v1').encode()).digest()))


def data(user):
    try:
        return json.loads(user.preference.settings_json or '{}') if user.preference else {}
    except (ValueError, TypeError):
        return {}


def save(user, d):
    user.preference.settings_json = json.dumps(d, ensure_ascii=False)


def enabled(user):
    d = data(user)
    return bool(d.get('mfa_enabled') and d.get('mfa_secret_encrypted'))


def generate():
    return base64.b32encode(secrets.token_bytes(20)).decode('ascii').rstrip('=')


def encrypt(secret):
    return _key().encrypt(secret.encode()).decode()


def _decrypt(token):
    try:
        return _key().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return ''


def code(secret, window=None):
    window = int(time.time() // 30) if window is None else int(window)
    key = base64.b32decode(secret + '=' * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack('>Q', window), hashlib.sha1).digest()
    offset = digest[-1] & 0x0f
    value = struct.unpack('>I', digest[offset:offset+4])[0] & 0x7fffffff
    return f'{value % 1000000:06d}'


def verify(user, submitted, *, consume=False):
    d = data(user)
    secret = _decrypt(d.get('mfa_secret_encrypted') or d.get('mfa_pending_encrypted') or '')
    if not secret or len(submitted or '') != 6 or not str(submitted).isdigit():
        return False
    now = int(time.time() // 30)
    used = int(d.get('mfa_last_window', -1))
    for window in (now-1, now, now+1):
        if (not consume or window > used) and hmac.compare_digest(code(secret, window), str(submitted)):
            if consume:
                d['mfa_last_window'] = window
                save(user, d)
            return True
    return False


def recovery_codes():
    plain = [secrets.token_hex(4).upper() for _ in range(8)]
    hashed = [hashlib.sha256((str(SECRET_KEY) + ':recovery:' + value).encode()).hexdigest() for value in plain]
    return plain, hashed


def verify_recovery(user, submitted):
    raw = ''.join(c for c in (submitted or '').upper() if c in '0123456789ABCDEF')
    if len(raw) != 8:
        return False
    digest = hashlib.sha256((str(SECRET_KEY) + ':recovery:' + raw).encode()).hexdigest()
    d = data(user)
    hashes = d.get('mfa_recovery_hashes', [])
    for i, item in enumerate(hashes):
        if hmac.compare_digest(item, digest):
            del hashes[i]
            d['mfa_recovery_hashes'] = hashes
            save(user, d)
            return True
    return False


def pending_secret(user):
    return _decrypt(data(user).get('mfa_pending_encrypted',''))
