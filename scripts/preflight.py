from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
errors = []
warnings = []

required = [
    ROOT / "app" / "main.py",
    ROOT / "requirements.txt",
    ROOT / "Dockerfile",
]
for path in required:
    if not path.exists():
        errors.append(f"Arquivo ausente: {path.relative_to(ROOT)}")

if os.getenv("APP_ENV", "").lower() in {"production", "prod"}:
    if not os.getenv("SECRET_KEY"):
        errors.append("SECRET_KEY precisa estar definida em producao.")
    if os.getenv("LOCAL_ADMIN_ENABLED", "0").lower() in {"1", "true", "yes", "sim", "on"}:
        errors.append("LOCAL_ADMIN_ENABLED deve ficar 0 em producao.")
    if os.getenv("SESSION_HTTPS_ONLY", "1").lower() not in {"1", "true", "yes", "sim", "on"}:
        warnings.append("SESSION_HTTPS_ONLY deveria ficar 1 em producao.")

if os.getenv("AMADEUS_ENABLED", "0").lower() in {"1", "true", "yes", "sim", "on"}:
    if not os.getenv("AMADEUS_CLIENT_ID") or not os.getenv("AMADEUS_CLIENT_SECRET"):
        errors.append("AMADEUS_ENABLED=1, mas CLIENT_ID/CLIENT_SECRET nao foram definidos.")

for msg in warnings:
    print("AVISO:", msg)
for msg in errors:
    print("ERRO:", msg)

if errors:
    sys.exit(1)
print("OK: preflight concluido sem erros bloqueantes.")
