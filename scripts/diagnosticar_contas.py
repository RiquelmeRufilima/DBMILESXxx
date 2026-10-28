"""Uso administrativo: python scripts/diagnosticar_contas.py email@exemplo.com"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import WebUser


def main():
    if len(sys.argv) != 2 or "@" not in sys.argv[1]:
        print("Uso: python scripts/diagnosticar_contas.py email@exemplo.com")
        return 2
    email = sys.argv[1].strip().lower()
    with SessionLocal() as db:
        rows = db.scalars(select(WebUser).where(func.lower(func.trim(WebUser.email)) == email)
                          .order_by(WebUser.id)).all()
        print(f"Contas encontradas no banco configurado: {len(rows)}")
        for user in rows:
            print(f"ID={user.id} | nome={user.name} | email={user.email} | empresa={user.company_id} | contato={user.contact_id} | ativa={user.active}")
    print("Se os dois aparelhos mostrarem contas diferentes e aqui existir só uma, verifique domínio/deploy e DATABASE_URL de cada ambiente.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
