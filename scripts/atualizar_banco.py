"""Mostra e aplica as atualizações do banco (tabelas/colunas novas).

Uso (no terminal do Codespaces):
    DATABASE_URL="postgresql://..." python scripts/atualizar_banco.py            # só mostra
    DATABASE_URL="postgresql://..." python scripts/atualizar_banco.py --aplicar  # aplica

Nunca apaga nem altera dados: apenas cria o que o código precisa e ainda não
existe. O deploy no Vercel já faz isso sozinho; use este script para conferir.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    if not os.getenv("DATABASE_URL"):
        print("Defina DATABASE_URL com o endereço do Neon antes de rodar.")
        return 2
    from app.database import Base, engine
    from app import models  # noqa: F401  (registra todas as tabelas)
    from app.services.schema_sync import plan, sync_schema

    aplicar = "--aplicar" in sys.argv
    with engine.connect() as conn:
        tables, columns = plan(conn, Base.metadata)
    if not tables and not columns:
        print("✅ O banco já tem tudo o que o código precisa.")
        if aplicar:
            sync_schema(engine, Base.metadata, force=True)
        return 0
    print("Faltando no banco:")
    for table in tables:
        print(f"  + tabela {table.name}")
    for table, column in columns:
        print(f"  + coluna {table.name}.{column.name} ({column.type})")
    if not aplicar:
        print("\nNada foi alterado. Rode novamente com --aplicar para criar.")
        return 1
    report = sync_schema(engine, Base.metadata, force=True)
    print(f"\n✅ Aplicado: {report.summary()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
