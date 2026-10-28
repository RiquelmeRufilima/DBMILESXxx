"""Gera um par Web Push VAPID; execute localmente e guarde a chave privada em segredo."""
from __future__ import annotations

import base64
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


key = ec.generate_private_key(ec.SECP256R1())
private = key.private_numbers().private_value.to_bytes(32, "big")
public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
print("VAPID_PUBLIC_KEY=" + b64url(public))
print("VAPID_PRIVATE_KEY=" + b64url(private))
print("VAPID_SUBJECT=mailto:contato@seu-dominio.com  # substitua por seu contato real")
